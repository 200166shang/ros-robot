#ifndef IMG_ENCODE__JPEG_ENCODER_HPP_
#define IMG_ENCODE__JPEG_ENCODER_HPP_

#include <cstdint>
#include <memory>
#include <opencv2/core/mat.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <string>
#include <vector>

namespace img_encode {

// JPEG 编码模块将 ROS 图像校验、颜色转换和所选硬件/软件编码集中在一个接口中。
class JpegEncoder {
public:
    // 初始化 JPEG 编码质量和所选后端资源。
    explicit JpegEncoder(int quality);

    // 释放所选后端持有的编码资源。
    ~JpegEncoder();

    // 将 ROS 图像编码为 JPEG，失败时返回 false 并填写可读原因。
    bool encode(const sensor_msgs::msg::Image& image, std::vector<uint8_t>& jpeg, std::string& error);

private:
    // 将常用 ROS 像素编码规整为 RGB8 连续矩阵。
    bool to_rgb(const sensor_msgs::msg::Image& image, cv::Mat& rgb, std::string& error) const;

    // 使用 OpenCV 软件编码 RGB 图像。
    bool encode_opencv(const cv::Mat& rgb, std::vector<uint8_t>& jpeg, std::string& error) const;

#if IMG_ENCODE_USE_MPP
    class MppEncoder;
    std::unique_ptr<MppEncoder> mpp_encoder_;
#endif

    int quality_;
};

}  // namespace img_encode

#endif  // IMG_ENCODE__JPEG_ENCODER_HPP_
