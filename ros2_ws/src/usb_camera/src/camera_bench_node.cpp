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

namespace {

// USB 摄像头启动后的首帧可能晚于后续帧；首帧使用单独的有限等待窗口。
constexpr int kFirstFrameStartupTimeoutSeconds = 15;
constexpr int kCaptureTimeoutMs                = 2000;
constexpr int kWarmupDurationSeconds           = 2;

}  // namespace

class CameraBenchNode : public rclcpp::Node {
public:
    // 读取基准配置并接好 ROS 通信；所有回调对象就绪后才启动采集线程。
    CameraBenchNode() : Node("camera_bench") {
        // 先用有符号类型校验参数，再转换为配置所用的无符号类型。
        config_.device             = declare_parameter<std::string>("device", "/dev/video0");
        const int requested_width  = declare_parameter<int>("width", 1280);
        const int requested_height = declare_parameter<int>("height", 720);
        const int requested_fps    = declare_parameter<int>("fps", 30);
        config_.duration_seconds   = declare_parameter<double>("duration_seconds", 30.0);
        csv_path_                  = declare_parameter<std::string>("csv", "camera_bench.csv");

        const bool valid_camera_settings = requested_width > 0 && requested_height > 0 && requested_fps > 0;
        const bool valid_duration        = std::isfinite(config_.duration_seconds) && config_.duration_seconds > 0.0;
        if (!valid_camera_settings || !valid_duration) {
            throw std::runtime_error("width, height, fps, and duration_seconds must be positive");
        }

        config_.width         = static_cast<uint32_t>(requested_width);
        config_.height        = static_cast<uint32_t>(requested_height);
        config_.requested_fps = static_cast<uint32_t>(requested_fps);

        // 统计对象使用校验后的配置；发布端和接收端共用私有话题。
        metrics_   = std::make_unique<usb_camera::CameraBenchMetrics>(config_);
        publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>("~/benchmark/image/compressed", rclcpp::QoS(10).reliable());
        receiver_  = create_subscription<sensor_msgs::msg::CompressedImage>(
            "~/benchmark/image/compressed", rclcpp::QoS(10).reliable(), [this](sensor_msgs::msg::CompressedImage::ConstSharedPtr message) {
                on_image_received(std::move(message));
            });

        // 定时器由 executor 处理；相机采集在线程中运行，避免阻塞接收回调。
        timer_  = create_wall_timer(std::chrono::milliseconds(100), [this] { check_finish(); });
        worker_ = std::thread([this] { capture_run(); });
    }

    // 供 main() 在 spin 结束后生成成功或失败的进程退出码。
    bool failed() const { return failed_.load(); }

    // 请求工作线程停止并 join 后再关闭相机，避免与正在进行的 capture() 并发。
    ~CameraBenchNode() override {
        stopping_.store(true);
        if (worker_.joinable()) worker_.join();
        camera_.close_device();
    }

private:
    using Clock = std::chrono::steady_clock;

    // 生成稳定的单调时钟纳秒值，供跨线程传递接收静默起点。
    static int64_t steady_now_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count(); }

    // 串起相机准备、预热和测量；采集错误会提前退出，测量循环退出后交由定时器收尾。
    void capture_run() {
        // 初始化错误已记录给定时器处理；没有可用相机时不继续。
        if (!open_camera()) return;

        // 预热和正式测量共用缓冲，保留 vector 容量以减少逐帧内存分配。
        std::vector<uint8_t> jpeg;
        // 预热只稳定相机状态，不计入指标；失败或停止时不启动正式测量。
        if (!warm_up_camera(jpeg)) {
            if (stopping_.load()) camera_.close_device();
            return;
        }

        if (!measure_and_publish(jpeg)) return;

        // 测量成功后通知定时器进入排空和报告阶段。
        complete_capture();
    }

    // 打开并配置相机；失败原因交给 executor 定时器统一记录和退出。
    bool open_camera() {
        std::string error;
        // 相机初始化失败时只报告错误，不生成看似成功的 CSV 记录。
        if (!camera_.open_device(config_.device, config_.width, config_.height, config_.requested_fps, error)) {
            failure_ = "camera setup failed: " + error;
            failed_.store(true);
            return false;
        }

        RCLCPP_INFO(get_logger(),
                    "waiting up to %d seconds for the first frame on %s (%ux%u)",
                    kFirstFrameStartupTimeoutSeconds,
                    config_.device.c_str(),
                    camera_.width(),
                    camera_.height());
        return true;
    }

    // 首帧到达后再完整预热 2 秒；预热帧不计入基准指标。
    bool warm_up_camera(std::vector<uint8_t> &jpeg) {
        if (!wait_for_first_frame(jpeg)) return false;

        const auto warmup_end = Clock::now() + std::chrono::seconds(kWarmupDurationSeconds);
        std::string error;
        // 首帧启动等待与稳定预热分开计时，避免启动慢的相机挤掉预热窗口。
        RCLCPP_INFO(get_logger(), "first frame received; warming up for %d seconds", kWarmupDurationSeconds);
        while (Clock::now() < warmup_end && !stopping_.load()) {
            if (!camera_.capture(jpeg, kCaptureTimeoutMs, error)) {
                if (Clock::now() >= warmup_end && error == "capture timeout") {
                    break;
                }
                fail_capture(error);
                return false;
            }
        }
        return !stopping_.load();
    }

    // 首帧可能因 USB 摄像头启动或重置而延迟；短轮询保留停止线程的响应性。
    bool wait_for_first_frame(std::vector<uint8_t> &jpeg) {
        const auto startup_deadline = Clock::now() + std::chrono::seconds(kFirstFrameStartupTimeoutSeconds);
        std::string error;
        while (!stopping_.load()) {
            const auto remaining_ms = std::chrono::duration_cast<std::chrono::milliseconds>(startup_deadline - Clock::now()).count();
            if (remaining_ms <= 0) break;

            const int timeout_ms = static_cast<int>(remaining_ms < kCaptureTimeoutMs ? remaining_ms : kCaptureTimeoutMs);
            if (camera_.capture(jpeg, timeout_ms, error)) return true;
            if (error != "capture timeout") {
                fail_capture(error);
                return false;
            }
        }

        if (!stopping_.load()) {
            fail_capture("no frame received within " + std::to_string(kFirstFrameStartupTimeoutSeconds) + " seconds");
        }
        return false;
    }

    // 建立测量时间窗口，循环采集并把窗口内的帧交给 ROS 发布路径。
    bool measure_and_publish(std::vector<uint8_t> &jpeg) {
        std::string error;
        uint32_t sequence = 0;

        // 用单调时钟控制真实测量时长，ROS 时钟只用于消息时间戳和延迟计算。
        const auto measurement_start = Clock::now();
        const auto measurement_end   = measurement_start + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(config_.duration_seconds));
        const auto ros_start         = now();
        start_ros_ns_.store(ros_start.nanoseconds());
        end_ros_ns_.store(ros_start.nanoseconds() + static_cast<int64_t>(config_.duration_seconds * 1.0e9));

        RCLCPP_INFO(get_logger(), "measuring for %.2f seconds", config_.duration_seconds);
        uint64_t measurement_frames = 0;
        while (Clock::now() < measurement_end && !stopping_.load()) {
            if (!camera_.capture(jpeg, kCaptureTimeoutMs, error, &sequence)) {
                if (measurement_frames > 0 && Clock::now() >= measurement_end && error == "capture timeout") {
                    break;
                }
                fail_capture(error);
                return false;
            }
            // 测量截止后才完成的帧属于有意跳过，不计入采集数，也不算作 V4L2 丢帧。
            if (Clock::now() >= measurement_end) break;
            publish_benchmark_frame(jpeg, sequence);
            ++measurement_frames;
        }
        return true;
    }

    // 将一帧 JPEG 转为 ROS 消息，同时记录采集和发布指标。
    void publish_benchmark_frame(const std::vector<uint8_t> &jpeg, uint32_t sequence) {
        sensor_msgs::msg::CompressedImage message;
        message.header.stamp    = now();
        message.header.frame_id = "camera_bench";
        message.format          = "jpeg";
        // 这里把复用的 JPEG 缓冲复制进 ROS 消息；移动消息对象不会消除这次字节复制。
        message.data = jpeg;

        {
            // 发布计数统计 publish() 调用；接收计数由订阅回调独立累计。
            std::lock_guard<std::mutex> lock(metrics_mutex_);
            metrics_->observe_capture(sequence, jpeg.size());
            metrics_->observe_publish();
        }

        publisher_->publish(std::move(message));
    }

    // 保存报告所需的相机结果并通知定时器；必须在关闭设备清零分辨率前读取尺寸。
    void complete_capture() {
        actual_width_.store(camera_.width());
        actual_height_.store(camera_.height());
        finished_at_ = Clock::now();
        last_receive_steady_ns_.store(steady_now_ns());
        finished_.store(true);
        camera_.close_device();
    }

    // 统一记录采集错误并释放设备，阻止定时器写出成功报告。
    void fail_capture(const std::string &error) {
        failure_ = "camera capture failed: " + error;
        failed_.store(true);
        camera_.close_device();
    }

    // executor 收到自发图像时，只累计消息时间戳落在测量窗口内的帧。
    void on_image_received(sensor_msgs::msg::CompressedImage::ConstSharedPtr message) {
        const auto clock_type = get_clock()->get_clock_type();
        const rclcpp::Time stamp(message->header.stamp, clock_type);
        const int64_t start_ns = start_ros_ns_.load();
        if (start_ns == 0) return;

        const rclcpp::Time start(start_ns, clock_type);
        const rclcpp::Time end(end_ros_ns_.load(), clock_type);
        if (stamp < start || stamp >= end) return;

        // ROS 时间戳计算发布到接收延迟；单调时钟用于稳定判断接收端静默期。
        const double latency = (now() - stamp).seconds() * 1000.0;
        last_receive_steady_ns_.store(steady_now_ns());
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_->observe_receive(latency);
    }

    // 定时器检查失败或完成状态；成功时先等回调排空，再写出最终报告。
    void check_finish() {
        if (failed_.load()) {
            RCLCPP_ERROR(get_logger(), "%s", failure_.c_str());
            stop_node();
            return;
        }

        if (!finished_.load()) return;
        const auto current = Clock::now();
        if (current - finished_at_ < std::chrono::milliseconds(250)) return;
        usb_camera::CameraBenchSummary summary;
        {
            std::lock_guard<std::mutex> lock(metrics_mutex_);
            summary = metrics_->summarize(actual_width_.load(), actual_height_.load());
        }

        if (!receiver_drain_complete(current, summary)) return;
        if (!write_summary(summary)) failed_.store(true);
        stop_node();
    }

    // 数量相等即可汇总；数量不足时需等最后一次接收后静默一秒。
    bool receiver_drain_complete(Clock::time_point current, const usb_camera::CameraBenchSummary &summary) const {
        const auto quiet_since = Clock::time_point(Clock::duration(std::chrono::nanoseconds(last_receive_steady_ns_.load())));
        return summary.receive_count >= summary.publish_count || current - quiet_since >= std::chrono::seconds(1);
    }

    // 追加一行 CSV，空文件先写表头；写入失败返回 false 供调用方设置退出状态。
    bool write_summary(const usb_camera::CameraBenchSummary &summary) {
        struct stat info {};
        const bool has_content = stat(csv_path_.c_str(), &info) == 0 && info.st_size > 0;
        std::ofstream csv(csv_path_, std::ios::out | std::ios::app);
        if (!csv) {
            RCLCPP_ERROR(get_logger(), "cannot append benchmark CSV: %s", csv_path_.c_str());
            return false;
        }
        if (!has_content) csv << usb_camera::CameraBenchMetrics::csv_header() << '\n';
        csv << usb_camera::CameraBenchMetrics::csv_row(summary) << '\n';
        if (!csv) {
            RCLCPP_ERROR(get_logger(), "failed writing benchmark CSV: %s", csv_path_.c_str());
            return false;
        }

        RCLCPP_INFO(get_logger(), "%s", usb_camera::CameraBenchMetrics::console_summary(summary).c_str());
        RCLCPP_INFO(get_logger(), "appended %s", csv_path_.c_str());
        return true;
    }

    // 停止周期性收尾并退出 ROS spin。
    void stop_node() {
        timer_->cancel();
        rclcpp::shutdown();
    }

    // 基准参数与本次报告路径。
    usb_camera::CameraBenchConfig config_;
    std::string csv_path_;

    // 采集资源和共享统计；指标同时被工作线程和 executor 回调更新。
    usb_camera::V4l2Camera camera_;
    std::unique_ptr<usb_camera::CameraBenchMetrics> metrics_;
    std::mutex metrics_mutex_;

    // 析构线程通知工作线程停止，并等待它退出后再关闭相机。
    std::atomic<bool> stopping_{false};
    std::thread worker_;

    // 工作线程通过这两个标志把错误或完成状态交给 ROS executor。
    std::atomic<bool> failed_{false};
    std::atomic<bool> finished_{false};

    // 接收回调用 ROS 时间戳筛选测量帧；排空判断使用单调时钟。
    std::atomic<int64_t> start_ros_ns_{0}, end_ros_ns_{0};
    std::atomic<int64_t> last_receive_steady_ns_{0};

    // 工作线程先保存设备尺寸和完成时刻，再置位 finished_ 供定时器读取。
    std::atomic<uint32_t> actual_width_{0}, actual_height_{0};
    std::string failure_;
    Clock::time_point finished_at_{};

    // ROS 通信对象在构造时创建，在线程开始前完成初始化。
    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
    rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr receiver_;
    rclcpp::TimerBase::SharedPtr timer_;
};

// 初始化 ROS，运行基准节点，并将节点失败状态映射为进程退出码。
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
