#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "usb_camera/frame_divider.hpp"
#include "usb_camera/frame_rate_stats.hpp"
#include "usb_camera/v4l2_camera.hpp"

class UsbCameraNode : public rclcpp::Node {
public:
    // 初始化相机参数、ROS topic 和采集线程。
    UsbCameraNode() : Node("usb_camera"), running_(true) {
        const std::string device = declare_parameter<std::string>("device", "/dev/video0");
        device_candidates_       = declare_parameter<std::vector<std::string>>("device_candidates", {});
        if (device_candidates_.empty()) {
            device_candidates_.push_back(device);
        }

        topic_         = declare_parameter<std::string>("topic", "/image_raw/compressed");
        frame_id_      = declare_parameter<std::string>("frame_id", "camera");
        width_         = declare_parameter<int>("width", 1280);
        height_        = declare_parameter<int>("height", 720);
        fps_           = declare_parameter<int>("fps", 30);
        frame_divider_ = declare_parameter<int>("frame_divider", 1);
        lazy_          = declare_parameter<bool>("lazy", true);

        const bool invalid_frame_divider = frame_divider_ < 1;
        if (invalid_frame_divider) {
            throw std::invalid_argument("frame_divider must be at least 1");
        }
        const bool has_empty_device_candidate =
            std::any_of(device_candidates_.begin(), device_candidates_.end(), [](const std::string& candidate) { return candidate.empty(); });
        if (has_empty_device_candidate) {
            throw std::invalid_argument("device_candidates must not contain empty paths");
        }

        const auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
        publisher_     = create_publisher<sensor_msgs::msg::CompressedImage>(topic_, qos);
        enable_subscription_ =
            create_subscription<std_msgs::msg::Bool>("/enable_camera", 10, [this](std_msgs::msg::Bool::SharedPtr message) { enabled_.store(message->data); });

        worker_ = std::thread([this] { capture_loop(); });
    }

    // 停止采集线程并释放 V4L2 资源。
    ~UsbCameraNode() override {
        running_.store(false);
        if (worker_.joinable()) {
            worker_.join();
        }
        camera_.close_device();
    }

private:
    // 按使能状态和订阅者数量管理相机，并发布符合帧间隔的 JPEG 图像。
    void capture_loop() {
        usb_camera::FrameDivider divider(static_cast<uint32_t>(frame_divider_));
        usb_camera::FrameRateStats stats;
        std::vector<uint8_t> jpeg;
        std::string error;
        auto last_log          = std::chrono::steady_clock::now() - std::chrono::seconds(10);
        size_t candidate_index = 0;

        while (rclcpp::ok() && running_.load()) {
            const bool no_subscriber = lazy_ && publisher_->get_subscription_count() == 0;
            if (!enabled_.load() || no_subscriber) {
                stats.resetWindow();
                camera_.close_device();
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                continue;
            }

            if (!camera_.is_open()) {
                const std::string& candidate = device_candidates_[candidate_index];
                if (!camera_.open_device(candidate, width_, height_, fps_, error)) {
                    const auto now = std::chrono::steady_clock::now();
                    if (now - last_log > std::chrono::seconds(2)) {
                        RCLCPP_WARN(get_logger(), "%s; retrying", error.c_str());
                        last_log = now;
                    }
                    candidate_index = (candidate_index + 1) % device_candidates_.size();
                    std::this_thread::sleep_for(std::chrono::seconds(1));
                    continue;
                }
                RCLCPP_INFO(get_logger(), "opened %s as MJPEG %ux%u", candidate.c_str(), camera_.width(), camera_.height());
            }

            // capture 返回独立 JPEG 数据；V4L2 缓冲区已归还驱动后仍可安全构造 ROS 消息。
            if (!camera_.capture(jpeg, 2000, error)) {
                RCLCPP_WARN(get_logger(), "%s; reopening camera", error.c_str());
                stats.resetWindow();
                camera_.close_device();
                continue;
            }

            stats.onCaptured();
            if (divider.shouldPublish()) {
                sensor_msgs::msg::CompressedImage message;
                message.header.stamp    = now();
                message.header.frame_id = frame_id_;
                message.format          = "jpeg";
                // 复制可复用采集缓冲区的数据，确保 ROS 消息独立拥有 JPEG 字节。
                message.data = jpeg;
                publisher_->publish(std::move(message));
                stats.onPublished();
            }

            usb_camera::FpsSnapshot snapshot;
            if (stats.reportIfDue(snapshot)) {
                RCLCPP_INFO(get_logger(),
                            "capture %.1f fps, publish %.1f fps, subscribers=%zu",
                            snapshot.capture_fps,
                            snapshot.publish_fps,
                            publisher_->get_subscription_count());
            }
        }
    }

    usb_camera::V4l2Camera camera_;
    std::vector<std::string> device_candidates_;

    std::atomic<bool> enabled_{true};
    std::atomic<bool> running_;
    std::thread worker_;

    std::string topic_;
    std::string frame_id_;
    int width_;
    int height_;
    int fps_;
    int frame_divider_;
    bool lazy_;

    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
    rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
};

// 启动 ROS 2 相机发布节点并在退出时关闭 ROS。
int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<UsbCameraNode>());
    rclcpp::shutdown();
    return 0;
}
