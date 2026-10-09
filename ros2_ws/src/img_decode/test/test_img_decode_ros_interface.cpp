#include <gtest/gtest.h>

#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <opencv2/imgcodecs.hpp>
#include <thread>
#include <utility>
#include <vector>

#include "img_decode/image_decode_node.hpp"

namespace {

class ExecutorThread {
public:
    // 在独立线程中运行 ROS executor 以观测真实 topic 接口。
    explicit ExecutorThread(rclcpp::executors::SingleThreadedExecutor &executor) : executor_(executor), thread_([this]() { executor_.spin(); }) {}
    // 停止并等待 ROS executor 线程结束。
    ~ExecutorThread() {
        executor_.cancel();
        if (thread_.joinable()) {
            thread_.join();
        }
    }

private:
    rclcpp::executors::SingleThreadedExecutor &executor_;
    std::thread thread_;
};

// 生成带固定 header 的 JPEG 样本供公开 topic 接口测试使用。
sensor_msgs::msg::CompressedImage make_jpeg_message(int width = 323, int height = 243) {
    cv::Mat bgr(height, width, CV_8UC3, cv::Scalar(20, 80, 180));
    std::vector<uint8_t> jpeg;
    EXPECT_TRUE(cv::imencode(".jpg", bgr, jpeg));

    sensor_msgs::msg::CompressedImage message;
    message.header.stamp.sec     = 12;
    message.header.stamp.nanosec = 345678901U;
    message.header.frame_id      = "camera_optical_frame";
    message.format               = "jpeg";
    message.data                 = std::move(jpeg);
    return message;
}

// 等待输入 publisher 与解码节点建立 ROS topic 连接。
template <typename PublisherT>
bool wait_for_subscription(PublisherT &publisher) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (publisher->get_subscription_count() == 0 && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    return publisher->get_subscription_count() > 0;
}

class ImgDecodeRosInterfaceTest : public ::testing::Test {
protected:
    // 为节点 topic 接口测试初始化 ROS context。
    static void SetUpTestCase() {
        int argc = 0;
        rclcpp::init(argc, nullptr);
    }
    // 释放 topic 接口测试使用的 ROS context。
    static void TearDownTestCase() { rclcpp::shutdown(); }
};

// 验证默认缩放、RGB 输出布局与输入 header 保留行为。
TEST_F(ImgDecodeRosInterfaceTest, PublishesHalfScaleRgbImageAndPreservesHeader) {
    rclcpp::NodeOptions options;
    options.parameter_overrides({
        rclcpp::Parameter("input_topic", "/img_decode_test/default/input"),
        rclcpp::Parameter("output_topic", "/img_decode_test/default/output"),
    });
    auto decoder  = std::make_shared<ImageDecodeNode>(options);
    auto observer = std::make_shared<rclcpp::Node>("img_decode_default_observer");
    std::mutex message_mutex;
    std::condition_variable message_ready;
    sensor_msgs::msg::Image::SharedPtr received;
    auto output_subscription = observer->create_subscription<sensor_msgs::msg::Image>(
        "/img_decode_test/default/output", rclcpp::QoS(1).best_effort(), [&](sensor_msgs::msg::Image::SharedPtr message) {
            {
                std::lock_guard<std::mutex> lock(message_mutex);
                received = std::move(message);
            }
            message_ready.notify_one();
        });
    auto input_publisher = observer->create_publisher<sensor_msgs::msg::CompressedImage>("/img_decode_test/default/input", rclcpp::QoS(1).best_effort());

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(decoder);
    executor.add_node(observer);
    ExecutorThread spin_thread(executor);
    ASSERT_TRUE(wait_for_subscription(input_publisher));
    input_publisher->publish(make_jpeg_message());

    {
        std::unique_lock<std::mutex> lock(message_mutex);
        ASSERT_TRUE(message_ready.wait_for(lock, std::chrono::seconds(4), [&received]() { return static_cast<bool>(received); }));
    }
    std::lock_guard<std::mutex> lock(message_mutex);
    EXPECT_EQ(received->header.stamp.sec, 12);
    EXPECT_EQ(received->header.stamp.nanosec, 345678901U);
    EXPECT_EQ(received->header.frame_id, "camera_optical_frame");
    EXPECT_EQ(received->encoding, "rgb8");
    EXPECT_EQ(received->width, 162U);
    EXPECT_EQ(received->height, 122U);
    EXPECT_EQ(received->step, received->width * 3U);
    EXPECT_EQ(received->data.size(), static_cast<size_t>(received->step) * received->height);
    ASSERT_GE(received->data.size(), 3U);
    EXPECT_GT(received->data[0], received->data[2]);
}

// 验证相机常用分辨率下的 MPP stride 能正确交给 RGA 处理。
TEST_F(ImgDecodeRosInterfaceTest, ProcessesCameraResolutionFrame) {
    rclcpp::NodeOptions options;
    options.parameter_overrides({
        rclcpp::Parameter("input_topic", "/img_decode_test/camera/input"),
        rclcpp::Parameter("output_topic", "/img_decode_test/camera/output"),
    });
    auto decoder  = std::make_shared<ImageDecodeNode>(options);
    auto observer = std::make_shared<rclcpp::Node>("img_decode_camera_observer");
    std::mutex message_mutex;
    std::condition_variable message_ready;
    sensor_msgs::msg::Image::SharedPtr received;
    auto output_subscription = observer->create_subscription<sensor_msgs::msg::Image>(
        "/img_decode_test/camera/output", rclcpp::QoS(1).best_effort(), [&](sensor_msgs::msg::Image::SharedPtr message) {
            {
                std::lock_guard<std::mutex> lock(message_mutex);
                received = std::move(message);
            }
            message_ready.notify_one();
        });
    auto input_publisher = observer->create_publisher<sensor_msgs::msg::CompressedImage>("/img_decode_test/camera/input", rclcpp::QoS(1).best_effort());

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(decoder);
    executor.add_node(observer);
    ExecutorThread spin_thread(executor);
    ASSERT_TRUE(wait_for_subscription(input_publisher));
    input_publisher->publish(make_jpeg_message(1280, 720));

    {
        std::unique_lock<std::mutex> lock(message_mutex);
        ASSERT_TRUE(message_ready.wait_for(lock, std::chrono::seconds(4), [&received]() { return static_cast<bool>(received); }));
    }
    std::lock_guard<std::mutex> lock(message_mutex);
    EXPECT_EQ(received->encoding, "rgb8");
    EXPECT_EQ(received->width, 640U);
    EXPECT_EQ(received->height, 360U);
    EXPECT_EQ(received->step, received->width * 3U);
    EXPECT_EQ(received->data.size(), static_cast<size_t>(received->step) * received->height);
}

// 验证配置缩放比例和每 N 帧处理一次的行为。
TEST_F(ImgDecodeRosInterfaceTest, AppliesConfiguredScaleAndEveryNthInputDivider) {
    rclcpp::NodeOptions options;
    options.parameter_overrides({
        rclcpp::Parameter("input_topic", "/img_decode_test/divider/input"),
        rclcpp::Parameter("output_topic", "/img_decode_test/divider/output"),
        rclcpp::Parameter("scale", 0.25),
        rclcpp::Parameter("frame_divider", 2),
        rclcpp::Parameter("lazy", false),
    });
    auto decoder  = std::make_shared<ImageDecodeNode>(options);
    auto observer = std::make_shared<rclcpp::Node>("img_decode_divider_observer");
    std::mutex message_mutex;
    std::condition_variable message_ready;
    std::vector<sensor_msgs::msg::Image::SharedPtr> received;
    auto output_subscription = observer->create_subscription<sensor_msgs::msg::Image>(
        "/img_decode_test/divider/output", rclcpp::QoS(1).best_effort(), [&](sensor_msgs::msg::Image::SharedPtr message) {
            {
                std::lock_guard<std::mutex> lock(message_mutex);
                received.push_back(std::move(message));
            }
            message_ready.notify_one();
        });
    auto input_publisher = observer->create_publisher<sensor_msgs::msg::CompressedImage>("/img_decode_test/divider/input", rclcpp::QoS(1).best_effort());

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(decoder);
    executor.add_node(observer);
    ExecutorThread spin_thread(executor);
    ASSERT_TRUE(wait_for_subscription(input_publisher));
    input_publisher->publish(make_jpeg_message());
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    {
        std::lock_guard<std::mutex> lock(message_mutex);
        EXPECT_TRUE(received.empty());
    }

    input_publisher->publish(make_jpeg_message());
    {
        std::unique_lock<std::mutex> lock(message_mutex);
        ASSERT_TRUE(message_ready.wait_for(lock, std::chrono::seconds(4), [&received]() { return !received.empty(); }));
        ASSERT_EQ(received.size(), 1U);
        EXPECT_EQ(received.front()->width, 81U);
        EXPECT_EQ(received.front()->height, 61U);
    }
}

}  // namespace
