#include <cstddef>

// RGA headers rely on the NULL definition from cstddef.
#include <rga/im2d.h>
#include <rockchip/rk_mpi.h>
#include <rockchip/rk_mpi_cmd.h>

#include <algorithm>
#include <cstring>

#include "jpeg_encoder_backend.hpp"

namespace img_encode {
namespace {

// 封装 RGA 颜色转换和 MPP JPEG 编码所需的硬件资源。
class MppJpegEncoderBackend final : public JpegEncoderBackend {
public:
    // 保存质量参数，延迟到首帧时按图像分辨率初始化 MPP。
    explicit MppJpegEncoderBackend(int quality) : quality_(quality) {}

    // 释放此 adapter 持有的 MPP frame、context 和输入 buffer。
    ~MppJpegEncoderBackend() override { release(); }

    // 检查硬件格式约束，准备输入面，再执行 RGB 转换和 JPEG 编码。
    bool encode(const cv::Mat& rgb, std::vector<uint8_t>& jpeg, std::string& error) override {
        const bool even_dimensions = (rgb.cols % 2) == 0 && (rgb.rows % 2) == 0;
        if (!even_dimensions) {
            error = "MPP JPEG backend requires even image dimensions";
            return false;
        }

        const bool resolution_changed = context_ == nullptr || width_ != rgb.cols || height_ != rgb.rows;
        if (resolution_changed) {
            release();
            if (!initialize(rgb.cols, rgb.rows, error)) {
                return false;
            }
        }

        cv::Mat yuv;
        if (!convert_rgb_to_yuv(rgb, yuv, error)) {
            return false;
        }

        return encode_yuv_frame(yuv, jpeg, error);
    }

private:
    // 初始化匹配当前分辨率的 MPP frame、buffer 和 JPEG 配置。
    bool initialize(int width, int height, std::string& error) {
        width_             = width;
        height_            = height;
        horizontal_stride_ = align_width(width_, 16);
        vertical_stride_   = height_;
        frame_size_        = static_cast<size_t>(horizontal_stride_) * vertical_stride_ * 3 / 2;

        MPP_RET result = mpp_buffer_get(nullptr, &frame_buffer_, frame_size_);
        if (result != MPP_OK) {
            return fail_initialization("MPP input buffer allocation failed", error);
        }

        result = mpp_create(&context_, &api_);
        if (result != MPP_OK) {
            return fail_initialization("MPP context creation failed", error);
        }

        result = mpp_init(context_, MPP_CTX_ENC, MPP_VIDEO_CodingMJPEG);
        if (result != MPP_OK) {
            return fail_initialization("MPP JPEG encoder initialization failed", error);
        }

        MppEncPrepCfg prep{};
        prep.change     = MPP_ENC_PREP_CFG_CHANGE_INPUT | MPP_ENC_PREP_CFG_CHANGE_FORMAT;
        prep.width      = width_;
        prep.height     = height_;
        prep.hor_stride = horizontal_stride_;
        prep.ver_stride = vertical_stride_;
        prep.format     = MPP_FMT_YUV420P;
        result          = api_->control(context_, MPP_ENC_SET_PREP_CFG, &prep);
        if (result != MPP_OK) {
            return fail_initialization("MPP JPEG input format setup failed", error);
        }

        MppEncCodecCfg codec_config{};
        codec_config.coding      = MPP_VIDEO_CodingMJPEG;
        codec_config.jpeg.change = MPP_ENC_JPEG_CFG_CHANGE_QFACTOR;
        // MPP 的 q_factor 上限为 99，因此将通用质量 100 映射到硬件最大值。
        const int mpp_quality      = std::min(quality_, 99);
        codec_config.jpeg.q_factor = mpp_quality;
        codec_config.jpeg.qf_max   = mpp_quality;
        codec_config.jpeg.qf_min   = mpp_quality;
        result                     = api_->control(context_, MPP_ENC_SET_CODEC_CFG, &codec_config);
        if (result != MPP_OK) {
            return fail_initialization("MPP JPEG quality setup failed", error);
        }

        result = mpp_frame_init(&frame_);
        if (result != MPP_OK) {
            return fail_initialization("MPP frame allocation failed", error);
        }

        mpp_frame_set_width(frame_, width_);
        mpp_frame_set_height(frame_, height_);
        mpp_frame_set_hor_stride(frame_, horizontal_stride_);
        mpp_frame_set_ver_stride(frame_, vertical_stride_);
        mpp_frame_set_fmt(frame_, MPP_FMT_YUV420P);
        mpp_frame_set_buffer(frame_, frame_buffer_);
        return true;
    }

    // 用 RGA 将 RGB8 转换到带 MPP stride 的 YUV420P 输入面。
    bool convert_rgb_to_yuv(const cv::Mat& rgb, cv::Mat& yuv, std::string& error) const {
        yuv.create(height_ * 3 / 2, horizontal_stride_, CV_8UC1);

        auto source            = wrapbuffer_virtualaddr(const_cast<uint8_t*>(rgb.data), rgb.cols, rgb.rows, RK_FORMAT_RGB_888, rgb.cols, rgb.rows);
        auto destination       = wrapbuffer_virtualaddr(yuv.data, width_, height_, RK_FORMAT_YCbCr_420_P, horizontal_stride_, vertical_stride_);
        const IM_STATUS result = imcvtcolor(source, destination, source.format, destination.format);
        if (result != IM_STATUS_SUCCESS) {
            error = std::string("RGA RGB to YUV conversion failed: ") + imStrError(result);
            return false;
        }
        return true;
    }

    // 提交 YUV frame 到 MPP，并复制返回 packet 的 JPEG 字节。
    bool encode_yuv_frame(const cv::Mat& yuv, std::vector<uint8_t>& jpeg, std::string& error) {
        std::memcpy(mpp_buffer_get_ptr(frame_buffer_), yuv.data, frame_size_);

        MPP_RET result = api_->encode_put_frame(context_, frame_);
        if (result != MPP_OK) {
            error = "MPP rejected the input frame";
            return false;
        }

        MppPacket packet = nullptr;
        result           = api_->encode_get_packet(context_, &packet);
        if (result != MPP_OK || packet == nullptr) {
            if (packet != nullptr) {
                mpp_packet_deinit(&packet);
            }
            error = "MPP did not return a JPEG packet";
            return false;
        }

        const auto* data  = static_cast<const uint8_t*>(mpp_packet_get_pos(packet));
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

    // 记录初始化失败并统一释放可能已经分配的部分资源。
    bool fail_initialization(const char* message, std::string& error) {
        error = message;
        release();
        return false;
    }

    // 按 frame、context、buffer 的依赖顺序逆向释放硬件资源。
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

        width_             = 0;
        height_            = 0;
        horizontal_stride_ = 0;
        vertical_stride_   = 0;
        frame_size_        = 0;
    }

    // 将面宽度向上对齐到 MPP 要求的 stride 边界。
    static constexpr int align_width(int width, int alignment) { return (width + alignment - 1) & ~(alignment - 1); }

    int quality_;

    int width_{0};
    int height_{0};
    int horizontal_stride_{0};
    int vertical_stride_{0};
    size_t frame_size_{0};

    MppCtx context_{nullptr};
    MppApi* api_{nullptr};
    MppBuffer frame_buffer_{nullptr};
    MppFrame frame_{nullptr};
};

}  // namespace

// 创建 MPP/RGA 硬件编码 adapter。
std::unique_ptr<JpegEncoderBackend> create_jpeg_encoder_backend(int quality) { return std::make_unique<MppJpegEncoderBackend>(quality); }

}  // namespace img_encode
