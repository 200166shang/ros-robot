#include "img_encode/jpeg_encoder.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>

#if IMG_ENCODE_USE_MPP
#include <rga/im2d.h>
#include <rockchip/rk_mpi.h>
#include <rockchip/rk_mpi_cmd.h>
#endif

namespace img_encode {

#if IMG_ENCODE_USE_MPP
class JpegEncoder::MppEncoder {
public:
    // 保留所需质量值，MPP 编码器在首次收到图像时按分辨率创建。
    explicit MppEncoder(int quality) : quality_(quality) {}

    // 释放 MPP frame、buffer 和 context。
    ~MppEncoder() { release(); }

    // 将 RGB 图像经 RGA 转为 YUV420P，再由 MPP 编码为 JPEG。
    bool encode(const cv::Mat &rgb, std::vector<uint8_t> &jpeg, std::string &error) {
        if ((rgb.cols % 2) != 0 || (rgb.rows % 2) != 0) {
            error = "MPP JPEG backend requires even image dimensions";
            return false;
        }

        if (!context_ || width_ != rgb.cols || height_ != rgb.rows) {
            release();
            if (!initialize(rgb.cols, rgb.rows, error)) {
                return false;
            }
        }

        cv::Mat yuv(height_ * 3 / 2, hor_stride_, CV_8UC1);
        auto source                    = wrapbuffer_virtualaddr(const_cast<uint8_t *>(rgb.data), rgb.cols, rgb.rows, RK_FORMAT_RGB_888, rgb.cols, rgb.rows);
        auto destination               = wrapbuffer_virtualaddr(yuv.data, width_, height_, RK_FORMAT_YCbCr_420_P, hor_stride_, height_);
        const IM_STATUS convert_status = imcvtcolor(source, destination, source.format, destination.format);
        if (convert_status != IM_STATUS_SUCCESS) {
            error = std::string("RGA RGB to YUV conversion failed: ") + imStrError(convert_status);
            return false;
        }

        std::memcpy(mpp_buffer_get_ptr(frame_buffer_), yuv.data, frame_size_);
        MPP_RET result = api_->encode_put_frame(context_, frame_);
        if (result != MPP_OK) {
            error = "MPP rejected the input frame";
            return false;
        }

        MppPacket packet = nullptr;
        result           = api_->encode_get_packet(context_, &packet);
        if (result != MPP_OK || packet == nullptr) {
            error = "MPP did not return a JPEG packet";
            return false;
        }

        const auto *data  = static_cast<const uint8_t *>(mpp_packet_get_pos(packet));
        const size_t size = mpp_packet_get_length(packet);
        if (data == nullptr || size == 0) {
            mpp_packet_deinit(&packet);
            error = "MPP returned an empty JPEG packet";
            return false;
        }

        jpeg.assign(data, data + size);
        mpp_packet_deinit(&packet);
        return true;
    }

private:
    // 根据当前分辨率配置 RGA 输出面、MPP 输入 frame 和 JPEG 质量。
    bool initialize(int width, int height, std::string &error) {
        const auto fail = [this, &error](const char *message) {
            error = message;
            release();
            return false;
        };

        width_      = width;
        height_     = height;
        hor_stride_ = MPP_ALIGN(width_, 16);
        ver_stride_ = height_;
        frame_size_ = static_cast<size_t>(hor_stride_) * ver_stride_ * 3 / 2;

        MPP_RET result = mpp_buffer_get(nullptr, &frame_buffer_, frame_size_);
        if (result != MPP_OK) {
            return fail("MPP input buffer allocation failed");
        }

        result = mpp_create(&context_, &api_);
        if (result != MPP_OK) {
            return fail("MPP context creation failed");
        }

        result = mpp_init(context_, MPP_CTX_ENC, MPP_VIDEO_CodingMJPEG);
        if (result != MPP_OK) {
            return fail("MPP JPEG encoder initialization failed");
        }

        MppEncPrepCfg prep{};
        prep.change     = MPP_ENC_PREP_CFG_CHANGE_INPUT | MPP_ENC_PREP_CFG_CHANGE_FORMAT;
        prep.width      = width_;
        prep.height     = height_;
        prep.hor_stride = hor_stride_;
        prep.ver_stride = ver_stride_;
        prep.format     = MPP_FMT_YUV420P;
        result          = api_->control(context_, MPP_ENC_SET_PREP_CFG, &prep);
        if (result != MPP_OK) {
            return fail("MPP JPEG input format setup failed");
        }

        MppEncCodecCfg codec_cfg{};
        codec_cfg.coding      = MPP_VIDEO_CodingMJPEG;
        codec_cfg.jpeg.change = MPP_ENC_JPEG_CFG_CHANGE_QFACTOR;
        // MPP 的 q_factor 上限为 99；将通用 JPEG 质量 100 映射到硬件最大值。
        const int mpp_quality   = std::min(quality_, 99);
        codec_cfg.jpeg.q_factor = mpp_quality;
        codec_cfg.jpeg.qf_max   = mpp_quality;
        codec_cfg.jpeg.qf_min   = mpp_quality;
        result                  = api_->control(context_, MPP_ENC_SET_CODEC_CFG, &codec_cfg);
        if (result != MPP_OK) {
            return fail("MPP JPEG quality setup failed");
        }

        result = mpp_frame_init(&frame_);
        if (result != MPP_OK) {
            return fail("MPP frame allocation failed");
        }

        mpp_frame_set_width(frame_, width_);
        mpp_frame_set_height(frame_, height_);
        mpp_frame_set_hor_stride(frame_, hor_stride_);
        mpp_frame_set_ver_stride(frame_, ver_stride_);
        mpp_frame_set_fmt(frame_, MPP_FMT_YUV420P);
        mpp_frame_set_buffer(frame_, frame_buffer_);
        return true;
    }

    // 逆序释放 frame、MPP context 与输入 buffer。
    void release() {
        if (frame_ != nullptr) {
            mpp_frame_deinit(&frame_);
        }
        if (context_ != nullptr) {
            if (api_ != nullptr) {
                api_->reset(context_);
            }
            mpp_destroy(context_);
            context_ = nullptr;
            api_     = nullptr;
        }
        if (frame_buffer_ != nullptr) {
            mpp_buffer_put(frame_buffer_);
            frame_buffer_ = nullptr;
        }
        width_      = 0;
        height_     = 0;
        hor_stride_ = 0;
        ver_stride_ = 0;
        frame_size_ = 0;
    }

    // 对齐 MPP 输入面宽度，以满足编码器 stride 要求。
    static constexpr int MPP_ALIGN(int value, int alignment) { return (value + alignment - 1) & ~(alignment - 1); }

    int quality_;
    int width_{0};
    int height_{0};
    int hor_stride_{0};
    int ver_stride_{0};
    size_t frame_size_{0};
    MppCtx context_{nullptr};
    MppApi *api_{nullptr};
    MppBuffer frame_buffer_{nullptr};
    MppFrame frame_{nullptr};
};
#endif

// 验证质量范围，并创建构建时选择的编码后端。
JpegEncoder::JpegEncoder(int quality) : quality_(quality) {
    if (quality_ < 1 || quality_ > 100) {
        throw std::invalid_argument("JPEG quality must be in [1, 100]");
    }
#if IMG_ENCODE_USE_MPP
    mpp_encoder_ = std::make_unique<MppEncoder>(quality_);
#endif
}

// 释放由 MPP adapter 持有的硬件资源。
JpegEncoder::~JpegEncoder() = default;

// 按 ROS Image 编码解释输入像素，并交给当前 JPEG 后端。
bool JpegEncoder::encode(const sensor_msgs::msg::Image &image, std::vector<uint8_t> &jpeg, std::string &error) {
    cv::Mat rgb;
    if (!to_rgb(image, rgb, error)) {
        return false;
    }

#if IMG_ENCODE_USE_MPP
    return mpp_encoder_->encode(rgb, jpeg, error);
#else
    return encode_opencv(rgb, jpeg, error);
#endif
}

// 按消息 step 和 encoding 读取图像，并规整出 RGB8 数据。
bool JpegEncoder::to_rgb(const sensor_msgs::msg::Image &image, cv::Mat &rgb, std::string &error) const {
    if (image.width == 0 || image.height == 0 || image.width > static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
        image.height > static_cast<uint32_t>(std::numeric_limits<int>::max())) {
        error = "image dimensions must be nonzero";
        return false;
    }

    int channels    = 0;
    int source_type = CV_8UC1;
    if (image.encoding == "rgb8" || image.encoding == "bgr8") {
        channels    = 3;
        source_type = CV_8UC3;
    } else if (image.encoding == "rgba8" || image.encoding == "bgra8") {
        channels    = 4;
        source_type = CV_8UC4;
    } else if (image.encoding == "mono8") {
        channels = 1;
    } else {
        error = "supported encodings are rgb8, bgr8, rgba8, bgra8, and mono8";
        return false;
    }

    const size_t minimum_step   = static_cast<size_t>(image.width) * channels;
    const size_t required_bytes = static_cast<size_t>(image.step) * image.height;
    if (image.step < minimum_step || image.data.size() < required_bytes) {
        error = "image step or data size is smaller than its dimensions require";
        return false;
    }

    cv::Mat source(static_cast<int>(image.height), static_cast<int>(image.width), source_type, const_cast<uint8_t *>(image.data.data()), image.step);
    if (image.encoding == "rgb8") {
        rgb = source.clone();
    } else if (image.encoding == "bgr8") {
        cv::cvtColor(source, rgb, cv::COLOR_BGR2RGB);
    } else if (image.encoding == "rgba8") {
        cv::cvtColor(source, rgb, cv::COLOR_RGBA2RGB);
    } else if (image.encoding == "bgra8") {
        cv::cvtColor(source, rgb, cv::COLOR_BGRA2RGB);
    } else {
        cv::cvtColor(source, rgb, cv::COLOR_GRAY2RGB);
    }
    return true;
}

// 将 RGB8 转为 OpenCV 期望的 BGR 顺序并生成 JPEG 字节。
bool JpegEncoder::encode_opencv(const cv::Mat &rgb, std::vector<uint8_t> &jpeg, std::string &error) const {
    cv::Mat bgr;
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
    const std::vector<int> options{cv::IMWRITE_JPEG_QUALITY, quality_};
    if (!cv::imencode(".jpg", bgr, jpeg, options)) {
        error = "OpenCV JPEG encoder failed";
        return false;
    }
    return true;
}

}  // namespace img_encode
