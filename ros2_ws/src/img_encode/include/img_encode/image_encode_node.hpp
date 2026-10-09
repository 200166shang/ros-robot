#ifndef IMG_ENCODE__IMAGE_ENCODE_NODE_HPP_
#define IMG_ENCODE__IMAGE_ENCODE_NODE_HPP_

#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <string>

#include "img_encode/jpeg_encoder.hpp"

namespace img_encode {

// ROS node adapts Image topic input to the standalone JPEG encoder and output topic.
class ImageEncodeNode : public rclcpp::Node {
public:
    // 读取编码参数，并建立输入图像到 JPEG 主题的 ROS 连接。
    ImageEncodeNode();

private:
    // 编码输入消息，保留其 header 后发布标准 jpeg CompressedImage。
    void encode_image(const sensor_msgs::msg::Image::ConstSharedPtr& image);

    std::string input_topic_;
    std::string output_topic_;
    std::unique_ptr<JpegEncoder> encoder_;
    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr subscription_;
};

}  // namespace img_encode

#endif  // IMG_ENCODE__IMAGE_ENCODE_NODE_HPP_
