#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include "img_decode/image_processor.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"
#include "sensor_msgs/msg/image.hpp"

class ImageDecodeNode : public rclcpp::Node {
public:
    // 构造 JPEG 解码节点并连接 ROS 图像话题。
    explicit ImageDecodeNode(const rclcpp::NodeOptions &options = rclcpp::NodeOptions());

private:
    // 按输入帧序号筛选消息并发布解码后的 RGB 图像。
    void decode(const sensor_msgs::msg::CompressedImage::SharedPtr &compressed);
    // 有输出订阅者时才接收输入图像，减少闲置处理。
    void update_subscription();
    // 创建压缩图像订阅并绑定解码回调。
    void subscribe();

    std::string input_topic_;
    std::string output_topic_;
    double scale_{0.5};
    int64_t max_width_{1280};
    int64_t max_height_{720};
    int64_t frame_divider_{1};
    bool lazy_{true};
    uint64_t input_count_{0};
    std::unique_ptr<img_decode::ImageProcessor> processor_;
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr publisher_;
    rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr subscription_;
    rclcpp::TimerBase::SharedPtr timer_;
};
