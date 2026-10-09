#include "img_encode/jpeg_encoder.hpp"

#include <limits>
#include <opencv2/imgproc.hpp>
#include <stdexcept>

#include "jpeg_encoder_backend.hpp"

namespace img_encode {
namespace {

// 按 ROS 消息 encoding 将像素数据规整为连续 RGB8 矩阵。
bool to_rgb(const sensor_msgs::msg::Image& image, cv::Mat& rgb, std::string& error) {
    const bool dimensions_valid = image.width > 0 && image.height > 0 && image.width <= static_cast<uint32_t>(std::numeric_limits<int>::max()) &&
                                  image.height <= static_cast<uint32_t>(std::numeric_limits<int>::max());
    if (!dimensions_valid) {
        error = "image dimensions must be nonzero and fit OpenCV limits";
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

    const size_t minimum_step     = static_cast<size_t>(image.width) * channels;
    const size_t required_bytes   = static_cast<size_t>(image.step) * image.height;
    const bool image_buffer_valid = image.step >= minimum_step && image.data.size() >= required_bytes;
    if (!image_buffer_valid) {
        error = "image step or data size is smaller than its dimensions require";
        return false;
    }

    const cv::Mat source(static_cast<int>(image.height), static_cast<int>(image.width), source_type, const_cast<uint8_t*>(image.data.data()), image.step);
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

}  // namespace

// 校验 JPEG 质量，并创建当前构建选定的编码 adapter。
JpegEncoder::JpegEncoder(int quality) {
    if (quality < 1 || quality > 100) {
        throw std::invalid_argument("JPEG quality must be in [1, 100]");
    }

    backend_ = create_jpeg_encoder_backend(quality);
}

// 通过虚析构函数释放当前后端及其专属资源。
JpegEncoder::~JpegEncoder() = default;

// 校验并规范化输入图像，再委托当前 adapter 输出 JPEG 字节。
bool JpegEncoder::encode(const sensor_msgs::msg::Image& image, std::vector<uint8_t>& jpeg, std::string& error) {
    cv::Mat rgb;
    if (!to_rgb(image, rgb, error)) {
        return false;
    }

    return backend_->encode(rgb, jpeg, error);
}

}  // namespace img_encode
