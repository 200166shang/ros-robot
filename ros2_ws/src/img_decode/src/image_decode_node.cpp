#include "img_decode/image_decode_node.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace {

constexpr int64_t kMaxConfiguredDimension = 8192;

}  // namespace

// 中文：读取节点参数、创建处理 Adapter，并建立输出话题。
ImageDecodeNode::ImageDecodeNode(const rclcpp::NodeOptions &options) : Node("img_decode", options) {
    input_topic_                           = declare_parameter<std::string>("input_topic", "/image_raw/compressed");
    output_topic_                          = declare_parameter<std::string>("output_topic", "/camera/image_raw");
    scale_                                 = declare_parameter<double>("scale", 0.5);
    max_width_                             = declare_parameter<int64_t>("width", 1280);
    max_height_                            = declare_parameter<int64_t>("height", 720);
    const int64_t configured_frame_divider = declare_parameter<int64_t>("frame_divider", 1);
    frame_divider_                         = std::max<int64_t>(1, configured_frame_divider);
    lazy_                                  = declare_parameter<bool>("lazy", true);

    const bool valid_scale = std::isfinite(scale_) && scale_ > 0.0 && scale_ <= 1.0;
    if (!valid_scale) {
        throw std::runtime_error("scale must be in (0, 1]");
    }

    const bool valid_processor_dimensions =
        max_width_ > 0 && max_height_ > 0 && max_width_ <= kMaxConfiguredDimension && max_height_ <= kMaxConfiguredDimension;
    if (!valid_processor_dimensions) {
        throw std::runtime_error("width and height must be in [1, 8192]");
    }
    processor_ = img_decode::make_image_processor(static_cast<uint32_t>(max_width_), static_cast<uint32_t>(max_height_));
    auto qos   = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    publisher_ = create_publisher<sensor_msgs::msg::Image>(output_topic_, qos);
    timer_     = create_wall_timer(std::chrono::milliseconds(100), [this]() { update_subscription(); });

    if (!lazy_) {
        subscribe();
    }
    RCLCPP_INFO(get_logger(),
                "%s -> %s, %s backend, scale %.3f, frame divider %lld",
                input_topic_.c_str(),
                output_topic_.c_str(),
                img_decode::image_processor_backend(),
                scale_,
                static_cast<long long>(frame_divider_));
}

// 中文：只在需要图像输出时维持输入订阅。
void ImageDecodeNode::update_subscription() {
    const bool output_needed = !lazy_ || publisher_->get_subscription_count() > 0;
    if (output_needed && !subscription_) {
        subscribe();
    }
    if (!output_needed && subscription_) {
        subscription_.reset();
        RCLCPP_INFO(get_logger(), "no output subscribers; decoder paused");
    }
}

// 中文：创建压缩图像订阅并绑定处理入口。
void ImageDecodeNode::subscribe() {
    auto qos      = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    subscription_ = create_subscription<sensor_msgs::msg::CompressedImage>(
        input_topic_, qos, [this](sensor_msgs::msg::CompressedImage::SharedPtr message) { decode(message); });
    RCLCPP_INFO(get_logger(), "decoder subscribed");
}

// 中文：按输入帧 divider 解码 JPEG，并保留 header 发布 rgb8 图像。
void ImageDecodeNode::decode(const sensor_msgs::msg::CompressedImage::SharedPtr &compressed) {
    ++input_count_;
    if (input_count_ % static_cast<uint64_t>(frame_divider_) != 0) {
        return;
    }

    img_decode::DecodedImage decoded;
    std::string error;
    if (!processor_->process(compressed->data, scale_, decoded, error)) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "JPEG processing failed: %s", error.c_str());
        return;
    }

    sensor_msgs::msg::Image output;
    output.header       = compressed->header;
    output.height       = decoded.height;
    output.width        = decoded.width;
    output.encoding     = "rgb8";
    output.is_bigendian = false;
    output.step         = output.width * 3;
    output.data         = std::move(decoded.rgb);
    publisher_->publish(std::move(output));
}
