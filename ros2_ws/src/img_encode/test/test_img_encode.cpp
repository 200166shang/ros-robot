#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <opencv2/imgcodecs.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <thread>

#include "img_encode/image_encode_node.hpp"

// 验证 ROS topic 接口输出可解码 JPEG，并保留输入 header。
TEST(ImageEncodeTopicTest, PublishesDecodableJpegAndPreservesHeader) {
    int argc    = 0;
    char** argv = nullptr;
    rclcpp::init(argc, argv);

    auto encoder = std::make_shared<img_encode::ImageEncodeNode>();
    auto probe   = std::make_shared<rclcpp::Node>("img_encode_topic_probe");
    std::shared_ptr<sensor_msgs::msg::CompressedImage> received;
    const auto qos           = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    auto output_subscription = probe->create_subscription<sensor_msgs::msg::CompressedImage>(
        "/camera/image_raw/compressed", qos, [&received](sensor_msgs::msg::CompressedImage::ConstSharedPtr message) {
            received = std::make_shared<sensor_msgs::msg::CompressedImage>(*message);
        });
    auto input_publisher = probe->create_publisher<sensor_msgs::msg::Image>("/camera/image_raw", qos);

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(encoder);
    executor.add_node(probe);

    const auto discovery_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (input_publisher->get_subscription_count() == 0 && std::chrono::steady_clock::now() < discovery_deadline) {
        executor.spin_some();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    ASSERT_GT(input_publisher->get_subscription_count(), 0U);

    sensor_msgs::msg::Image image;
    image.header.stamp.sec     = 12;
    image.header.stamp.nanosec = 345678;
    image.header.frame_id      = "camera_optical_frame";
    image.height               = 24;
    image.width                = 32;
    image.encoding             = "rgb8";
    image.is_bigendian         = false;
    image.step                 = image.width * 3;
    image.data.resize(image.step * image.height);
    for (uint32_t y = 0; y < image.height; ++y) {
        for (uint32_t x = 0; x < image.width; ++x) {
            const size_t offset    = static_cast<size_t>(y) * image.step + x * 3;
            image.data[offset]     = static_cast<uint8_t>(x * 7);
            image.data[offset + 1] = static_cast<uint8_t>(y * 9);
            image.data[offset + 2] = 120;
        }
    }

    input_publisher->publish(image);
    const auto output_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!received && std::chrono::steady_clock::now() < output_deadline) {
        executor.spin_some();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    ASSERT_NE(received, nullptr);
    EXPECT_EQ(received->header, image.header);
    EXPECT_EQ(received->format, "jpeg");
    ASSERT_GT(received->data.size(), 4U);
    EXPECT_EQ(received->data[0], 0xFF);
    EXPECT_EQ(received->data[1], 0xD8);

    const cv::Mat encoded(1, static_cast<int>(received->data.size()), CV_8UC1, received->data.data());
    const cv::Mat decoded = cv::imdecode(encoded, cv::IMREAD_COLOR);
    ASSERT_FALSE(decoded.empty());
    EXPECT_EQ(decoded.cols, static_cast<int>(image.width));
    EXPECT_EQ(decoded.rows, static_cast<int>(image.height));

    executor.remove_node(encoder);
    executor.remove_node(probe);
    (void)output_subscription;
    rclcpp::shutdown();
}
