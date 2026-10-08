#include <sys/stat.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <fstream>
#include <memory>
#include <mutex>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "usb_camera/camera_bench_metrics.hpp"
#include "usb_camera/v4l2_camera.hpp"

class CameraBenchNode : public rclcpp::Node {
public:
    CameraBenchNode() : Node("camera_bench") {
        // 基准配置从 ROS 参数读取；先用有符号整数校验，避免负数转换成超大的无符号值。
        config_.device             = declare_parameter<std::string>("device", "/dev/video0");
        const int requested_width  = declare_parameter<int>("width", 1280);
        const int requested_height = declare_parameter<int>("height", 720);
        const int requested_fps    = declare_parameter<int>("fps", 30);
        config_.duration_seconds   = declare_parameter<double>("duration_seconds", 30.0);
        csv_path_                  = declare_parameter<std::string>("csv", "camera_bench.csv");
        if (requested_width <= 0 || requested_height <= 0 || requested_fps <= 0 ||
            !std::isfinite(config_.duration_seconds) || config_.duration_seconds <= 0.0) {
            throw std::runtime_error("width, height, fps, and duration_seconds must be positive");
        }
        config_.width         = static_cast<uint32_t>(requested_width);
        config_.height        = static_cast<uint32_t>(requested_height);
        config_.requested_fps = static_cast<uint32_t>(requested_fps);
        metrics_              = std::make_unique<usb_camera::CameraBenchMetrics>(config_);
        // 发布者和接收者共用私有话题，确保统计的是 ROS 消息链路而非直接函数调用。
        publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(
            "~/benchmark/image/compressed", rclcpp::QoS(10).reliable());
        receiver_ = create_subscription<sensor_msgs::msg::CompressedImage>(
            "~/benchmark/image/compressed",
            rclcpp::QoS(10).reliable(),
            [this](sensor_msgs::msg::CompressedImage::ConstSharedPtr message) {
                const auto clock_type = get_clock()->get_clock_type();
                const rclcpp::Time stamp(message->header.stamp, clock_type);
                const rclcpp::Time start(start_ros_ns_.load(), clock_type);
                const rclcpp::Time end(end_ros_ns_.load(), clock_type);
                if (start_ros_ns_.load() != 0 && stamp >= start && stamp < end) {
                    // 使用消息时间戳计算发布到接收延迟，只统计测量窗口内的消息。
                    const double latency = (now() - stamp).seconds() * 1000.0;
                    // 单调时钟用于接收端静默期判断，不受系统时间校准影响。
                    last_receive_steady_ns_.store(steady_now_ns());
                    std::lock_guard<std::mutex> lock(metrics_mutex_);
                    metrics_->observe_receive(latency);
                }
            });
        // ROS 回调由 executor 处理；采集放到工作线程，避免阻塞接收回调。
        timer_  = create_wall_timer(std::chrono::milliseconds(100), [this] { check_finish(); });
        worker_ = std::thread([this] { capture_run(); });
    }

    bool failed() const { return failed_.load(); }

    ~CameraBenchNode() override {
        stopping_.store(true);
        if (worker_.joinable()) worker_.join();
        camera_.close_device();
    }

private:
    using Clock = std::chrono::steady_clock;

    static int64_t steady_now_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch())
            .count();
    }

    void capture_run() {
        std::string error;
        // 相机初始化失败时只报告错误，不生成看似成功的 CSV 记录。
        if (!camera_.open_device(
                config_.device, config_.width, config_.height, config_.requested_fps, error)) {
            failure_ = "camera setup failed: " + error;
            failed_.store(true);
            return;
        }
        const uint32_t actual_width  = camera_.width();
        const uint32_t actual_height = camera_.height();
        RCLCPP_INFO(get_logger(),
                    "warming up for 2 seconds on %s (%ux%u)",
                    config_.device.c_str(),
                    actual_width,
                    actual_height);
        const auto warmup_end = Clock::now() + std::chrono::seconds(2);
        std::vector<uint8_t> jpeg;
        uint32_t sequence      = 0;
        uint64_t warmup_frames = 0;
        // 预热期间只让相机进入稳定状态，不把帧计入任何基准指标。
        while (Clock::now() < warmup_end && !stopping_.load()) {
            if (!camera_.capture(jpeg, 2000, error)) {
                if (warmup_frames > 0 && Clock::now() >= warmup_end && error == "capture timeout") {
                    break;
                }
                fail_capture(error);
                return;
            }
            ++warmup_frames;
        }
        if (stopping_.load()) return;

        // 用单调时钟控制真实测量时长，ROS 时钟只用于消息时间戳和延迟计算。
        const auto measurement_start = Clock::now();
        const auto measurement_end =
            measurement_start + std::chrono::duration_cast<Clock::duration>(
                                    std::chrono::duration<double>(config_.duration_seconds));
        const auto ros_start = now();
        start_ros_ns_.store(ros_start.nanoseconds());
        end_ros_ns_.store(ros_start.nanoseconds() +
                          static_cast<int64_t>(config_.duration_seconds * 1.0e9));
        RCLCPP_INFO(get_logger(), "measuring for %.2f seconds", config_.duration_seconds);
        uint64_t measurement_frames = 0;
        while (Clock::now() < measurement_end && !stopping_.load()) {
            if (!camera_.capture(jpeg, 2000, error, &sequence)) {
                if (measurement_frames > 0 && Clock::now() >= measurement_end &&
                    error == "capture timeout") {
                    break;
                }
                fail_capture(error);
                return;
            }
            // 测量截止后才完成的帧属于有意跳过，不计入采集数，也不算作 V4L2 丢帧。
            if (Clock::now() >= measurement_end) break;
            const rclcpp::Time stamp = now();
            sensor_msgs::msg::CompressedImage message;
            message.header.stamp    = stamp;
            message.header.frame_id = "camera_bench";
            message.format          = "jpeg";
            message.data            = jpeg;
            {
                // 记录本帧采集和发布调用；接收数由订阅回调独立累计。
                std::lock_guard<std::mutex> lock(metrics_mutex_);
                metrics_->observe_capture(sequence, jpeg.size());
                metrics_->observe_publish();
            }
            publisher_->publish(std::move(message));
            ++measurement_frames;
        }
        actual_width_.store(actual_width);
        actual_height_.store(actual_height);
        finished_at_ = Clock::now();
        last_receive_steady_ns_.store(steady_now_ns());
        finished_.store(true);
        camera_.close_device();
    }

    void fail_capture(const std::string &error) {
        // 统一关闭设备并标记失败，后续收尾逻辑不会写入完成记录。
        failure_ = "camera capture failed: " + error;
        failed_.store(true);
        camera_.close_device();
    }

    void check_finish() {
        if (failed_.load()) {
            RCLCPP_ERROR(get_logger(), "%s", failure_.c_str());
            timer_->cancel();
            rclcpp::shutdown();
            return;
        }
        if (!finished_.load()) return;
        const auto current = Clock::now();
        if (current - finished_at_ < std::chrono::milliseconds(250)) return;
        const auto quiet_since = Clock::time_point(
            Clock::duration(std::chrono::nanoseconds(last_receive_steady_ns_.load())));
        usb_camera::CameraBenchSummary summary;
        {
            std::lock_guard<std::mutex> lock(metrics_mutex_);
            summary = metrics_->summarize(actual_width_.load(), actual_height_.load());
        }
        // 数量一致时已收齐；数量不一致时，等接收端连续静默一秒，让排队回调有机会完成。
        // 每次迟到的接收回调都会重置静默窗口，再计算发布与接收的总数差。
        if (summary.receive_count < summary.publish_count &&
            current - quiet_since < std::chrono::seconds(1)) {
            return;
        }
        struct stat info {};
        const bool has_content = stat(csv_path_.c_str(), &info) == 0 && info.st_size > 0;
        std::ofstream csv(csv_path_, std::ios::out | std::ios::app);
        if (!csv) {
            RCLCPP_ERROR(get_logger(), "cannot append benchmark CSV: %s", csv_path_.c_str());
            failed_.store(true);
            timer_->cancel();
            rclcpp::shutdown();
            return;
        }
        if (!has_content) csv << usb_camera::CameraBenchMetrics::csv_header() << '\n';
        csv << usb_camera::CameraBenchMetrics::csv_row(summary) << '\n';
        if (!csv) {
            RCLCPP_ERROR(get_logger(), "failed writing benchmark CSV: %s", csv_path_.c_str());
            failed_.store(true);
            timer_->cancel();
            rclcpp::shutdown();
            return;
        }
        RCLCPP_INFO(
            get_logger(), "%s", usb_camera::CameraBenchMetrics::console_summary(summary).c_str());
        RCLCPP_INFO(get_logger(), "appended %s", csv_path_.c_str());
        timer_->cancel();
        rclcpp::shutdown();
    }

    usb_camera::CameraBenchConfig config_;
    std::string csv_path_;
    usb_camera::V4l2Camera camera_;
    std::unique_ptr<usb_camera::CameraBenchMetrics> metrics_;
    std::mutex metrics_mutex_;
    std::atomic<bool> stopping_{false}, failed_{false}, finished_{false};
    std::atomic<int64_t> start_ros_ns_{0}, end_ros_ns_{0};
    std::atomic<int64_t> last_receive_steady_ns_{0};
    std::atomic<uint32_t> actual_width_{0}, actual_height_{0};
    std::string failure_;
    Clock::time_point finished_at_{};
    std::thread worker_;
    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
    rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr receiver_;
    rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    try {
        const auto node = std::make_shared<CameraBenchNode>();
        rclcpp::spin(node);
        return node->failed() ? 1 : 0;
    } catch (const std::exception &error) {
        RCLCPP_FATAL(rclcpp::get_logger("camera_bench"), "%s", error.what());
        rclcpp::shutdown();
        return 1;
    }
    return 0;
}
