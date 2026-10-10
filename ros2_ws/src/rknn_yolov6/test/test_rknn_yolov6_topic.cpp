#include <gtest/gtest.h>
#include <sys/stat.h>
#include <unistd.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <string>
#include <thread>
#include <vector>

#include "rknn_yolov6/rknn_yolov6_node.hpp"

namespace {

// 在测试退出时关闭本进程中的 ROS 2 上下文。
class RosContext {
public:
    // 初始化 ROS 2 上下文供节点话题测试使用。
    RosContext() {
        int argc    = 0;
        char** argv = nullptr;
        rclcpp::init(argc, argv);
    }

    // 释放测试启动的 ROS 2 上下文。
    ~RosContext() {
        if (rclcpp::ok()) {
            rclcpp::shutdown();
        }
    }
};

// 读取测试所需外部模型或级联文件的环境变量。
std::string test_asset(const char* name) {
    const char* value = std::getenv(name);
    return value == nullptr ? std::string() : std::string(value);
}

// 通过 ROS 话题验证图像输入、检测消息和标注图像的公开契约。
TEST(RknnYolov6TopicTest, PublishesDetectionsAndAnnotatedRgbImage) {
    const std::string model_path   = test_asset("RKNN_YOLOV6_TEST_MODEL");
    const std::string labels_path  = test_asset("RKNN_YOLOV6_TEST_LABELS");
    const std::string cascade_path = test_asset("RKNN_YOLOV6_TEST_CASCADE");
#ifdef RKNN_YOLOV6_TEST_RKNN
    if (model_path.empty() || labels_path.empty()) {
        GTEST_SKIP() << "set RKNN_YOLOV6_TEST_MODEL and RKNN_YOLOV6_TEST_LABELS to external files";
    }
#else
    if (cascade_path.empty()) {
        GTEST_SKIP() << "set RKNN_YOLOV6_TEST_CASCADE to an external Haar cascade file";
    }
#endif

    RosContext ros_context;
    std::vector<rclcpp::Parameter> parameters{rclcpp::Parameter("input_topic", "/camera/image_raw"),
                                              rclcpp::Parameter("detections_topic", "/ai_msg_det"),
                                              rclcpp::Parameter("annotated_topic", "/camera/image_det"),
                                              rclcpp::Parameter("confidence_threshold", 0.30),
                                              rclcpp::Parameter("nms_threshold", 0.30),
                                              rclcpp::Parameter("always_process", false)};
#ifdef RKNN_YOLOV6_TEST_RKNN
    parameters.emplace_back("model_path", model_path);
    parameters.emplace_back("labels_path", labels_path);
#else
    parameters.emplace_back("haar_cascade_path", cascade_path);
#endif

    auto detector = std::make_shared<rknn_yolov6::RknnYolov6Node>(rclcpp::NodeOptions().parameter_overrides(parameters));
    auto probe    = std::make_shared<rclcpp::Node>("rknn_yolov6_topic_probe");
    std::shared_ptr<robot_interfaces::msg::Dets> received_detections;
    std::shared_ptr<sensor_msgs::msg::Image> received_image;
    const auto qos               = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    auto detections_subscription = probe->create_subscription<robot_interfaces::msg::Dets>(
        "/ai_msg_det", qos, [&received_detections](robot_interfaces::msg::Dets::ConstSharedPtr message) {
            received_detections = std::make_shared<robot_interfaces::msg::Dets>(*message);
        });
    auto image_subscription =
        probe->create_subscription<sensor_msgs::msg::Image>("/camera/image_det", qos, [&received_image](sensor_msgs::msg::Image::ConstSharedPtr message) {
            received_image = std::make_shared<sensor_msgs::msg::Image>(*message);
        });
    auto input_publisher = probe->create_publisher<sensor_msgs::msg::Image>("/camera/image_raw", qos);

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(detector);
    executor.add_node(probe);
    const auto outputs_discovered = [&probe]() {
        return !probe->get_publishers_info_by_topic("/ai_msg_det").empty() && !probe->get_publishers_info_by_topic("/camera/image_det").empty();
    };
    const auto discovery_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while ((input_publisher->get_subscription_count() == 0 || !outputs_discovered()) && std::chrono::steady_clock::now() < discovery_deadline) {
        executor.spin_some();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    ASSERT_GT(input_publisher->get_subscription_count(), 0U);

    sensor_msgs::msg::Image image;
    image.header.stamp.sec     = 12;
    image.header.stamp.nanosec = 345678;
    image.header.frame_id      = "camera_optical_frame";
    image.height               = 240;
    image.width                = 320;
    image.encoding             = "rgb8";
    image.is_bigendian         = false;
    image.step                 = image.width * 3;
    image.data.resize(static_cast<std::size_t>(image.step) * image.height);
    for (std::uint32_t y = 0; y < image.height; ++y) {
        for (std::uint32_t x = 0; x < image.width; ++x) {
            const std::size_t offset = static_cast<std::size_t>(y) * image.step + x * 3;
            image.data[offset]       = static_cast<std::uint8_t>(x * 7);
            image.data[offset + 1]   = static_cast<std::uint8_t>(y * 9);
            image.data[offset + 2]   = 120;
        }
    }
    input_publisher->publish(image);

    const auto output_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while ((!received_detections || !received_image) && std::chrono::steady_clock::now() < output_deadline) {
        executor.spin_some();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    executor.remove_node(detector);
    executor.remove_node(probe);
    (void)detections_subscription;
    (void)image_subscription;

    ASSERT_NE(received_detections, nullptr);
    EXPECT_EQ(received_detections->header, image.header);
    EXPECT_EQ(received_detections->image_width, image.width);
    EXPECT_EQ(received_detections->image_height, image.height);
    for (const auto& detection : received_detections->detections) {
        EXPECT_LE(detection.x1, detection.x2);
        EXPECT_LE(detection.y1, detection.y2);
        EXPECT_GE(detection.confidence, 0.0F);
        EXPECT_LE(detection.confidence, 1.0F);
    }

    ASSERT_NE(received_image, nullptr);
    EXPECT_EQ(received_image->header, image.header);
    EXPECT_EQ(received_image->encoding, "rgb8");
    EXPECT_EQ(received_image->width, image.width);
    EXPECT_EQ(received_image->height, image.height);
    EXPECT_EQ(received_image->step, image.step);
    EXPECT_EQ(received_image->data.size(), image.data.size());
}

// 验证离线模式读取外部图像并保存标注结果。
TEST(RknnYolov6OfflineTest, SavesAnnotatedImageToConfiguredDirectory) {
    const std::string image_path   = test_asset("RKNN_YOLOV6_TEST_IMAGE");
    const std::string model_path   = test_asset("RKNN_YOLOV6_TEST_MODEL");
    const std::string labels_path  = test_asset("RKNN_YOLOV6_TEST_LABELS");
    const std::string cascade_path = test_asset("RKNN_YOLOV6_TEST_CASCADE");
    if (image_path.empty()) {
        GTEST_SKIP() << "set RKNN_YOLOV6_TEST_IMAGE to an external image file";
    }
#ifdef RKNN_YOLOV6_TEST_RKNN
    if (model_path.empty() || labels_path.empty()) {
        GTEST_SKIP() << "set RKNN_YOLOV6_TEST_MODEL and RKNN_YOLOV6_TEST_LABELS to external files";
    }
#else
    if (cascade_path.empty()) {
        GTEST_SKIP() << "set RKNN_YOLOV6_TEST_CASCADE to an external Haar cascade file";
    }
#endif

    RosContext ros_context;
    const std::string output_directory = "/tmp/rknn_yolov6_offline_test_" + std::to_string(getpid());
    ASSERT_EQ(mkdir(output_directory.c_str(), 0777), 0);
    const std::string output_path = output_directory + "/0.jpg";
    std::vector<rclcpp::Parameter> parameters{rclcpp::Parameter("is_offline_image_mode", true),
                                              rclcpp::Parameter("offline_images_path", image_path),
                                              rclcpp::Parameter("offline_output_path", output_directory)};
#ifdef RKNN_YOLOV6_TEST_RKNN
    parameters.emplace_back("model_path", model_path);
    parameters.emplace_back("labels_path", labels_path);
#else
    parameters.emplace_back("haar_cascade_path", cascade_path);
#endif

    auto detector              = std::make_shared<rknn_yolov6::RknnYolov6Node>(rclcpp::NodeOptions().parameter_overrides(parameters));
    const auto output_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    bool output_exists         = false;
    while (!output_exists && std::chrono::steady_clock::now() < output_deadline) {
        std::ifstream output(output_path);
        output_exists = output.good();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    detector.reset();

    EXPECT_TRUE(output_exists);
    std::remove(output_path.c_str());
    rmdir(output_directory.c_str());
}

}  // namespace
