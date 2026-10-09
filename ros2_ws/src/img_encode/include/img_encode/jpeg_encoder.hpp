#ifndef IMG_ENCODE__JPEG_ENCODER_HPP_
#define IMG_ENCODE__JPEG_ENCODER_HPP_

#include <cstdint>
#include <memory>
#include <sensor_msgs/msg/image.hpp>
#include <string>
#include <vector>

namespace img_encode {

class JpegEncoderBackend;

// JPEG 编码模块负责校验 ROS 图像并交给选定的编码 adapter。
class JpegEncoder {
public:
    // 校验 JPEG 质量并创建构建时选定的编码 adapter。
    explicit JpegEncoder(int quality);

    // 释放编码 adapter 持有的资源。
    ~JpegEncoder();

    // 将 ROS 图像编码为 JPEG，失败时返回 false 并填写可读原因。
    bool encode(const sensor_msgs::msg::Image& image, std::vector<uint8_t>& jpeg, std::string& error);

private:
    std::unique_ptr<JpegEncoderBackend> backend_;
};

}  // namespace img_encode

#endif  // IMG_ENCODE__JPEG_ENCODER_HPP_
