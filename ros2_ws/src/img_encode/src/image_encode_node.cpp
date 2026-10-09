#include "img_encode/image_encode_node.hpp"

#include <utility>

namespace img_encode {

// 读取编码参数，并建立输入图像到 JPEG 主题的 ROS 连接。
ImageEncodeNode::ImageEncodeNode() : Node("img_encode") {
    input_topic_      = declare_parameter<std::string>("input_topic", "/camera/image_raw");
    output_topic_     = declare_parameter<std::string>("output_topic", "/camera/image_raw/compressed");
    const int quality = declare_parameter<int>("jpeg_quality", 80);

    encoder_       = std::make_unique<JpegEncoder>(quality);
    const auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    publisher_     = create_publisher<sensor_msgs::msg::CompressedImage>(output_topic_, qos);
    subscription_ =
        create_subscription<sensor_msgs::msg::Image>(input_topic_, qos, [this](sensor_msgs::msg::Image::ConstSharedPtr image) { encode_image(image); });

    RCLCPP_INFO(get_logger(), "JPEG encoder %s -> %s, quality %d", input_topic_.c_str(), output_topic_.c_str(), quality);
}

// 编码输入消息，保留其 header 后发布标准 jpeg CompressedImage。
void ImageEncodeNode::encode_image(const sensor_msgs::msg::Image::ConstSharedPtr& image) {
    sensor_msgs::msg::CompressedImage compressed;
    compressed.header = image->header;
    compressed.format = "jpeg";
    std::string error;

    if (!encoder_->encode(*image, compressed.data, error)) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "JPEG encode skipped: %s", error.c_str());
        return;
    }

    publisher_->publish(std::move(compressed));
}

}  // namespace img_encode
