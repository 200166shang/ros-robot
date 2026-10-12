#include <message_filters/subscriber.h>
#include <message_filters/sync_policies/exact_time.h>
#include <message_filters/synchronizer.h>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <geometry_msgs/msg/twist.hpp>
#include <memory>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <string>
#include <utility>

#include "object_track/tracking_math.hpp"
#include "object_track/tracking_output.hpp"

namespace {

using Image                      = sensor_msgs::msg::Image;
using Detections                 = robot_interfaces::msg::Dets;
using ExactTimePolicy            = message_filters::sync_policies::ExactTime<Image, Detections>;
using ImageDetectionSynchronizer = message_filters::Synchronizer<ExactTimePolicy>;

constexpr std::uint32_t kSynchronizationQueueSize = 10;
constexpr double kLogicalWidth                    = 640.0;
constexpr double kLogicalHeight                   = 360.0;

// 提供可观察的 dry-run 预览和按需创建的 ROS 速度输出端口。
class RosVelocityOutputPort final : public object_track::VelocityOutputPort {
public:
    // 保存节点引用和安全输出话题，暂不创建实际 Twist publisher。
    RosVelocityOutputPort(rclcpp::Node& node, std::string output_topic) : node_(node), output_topic_(std::move(output_topic)) {}

    // 通过 ROS 日志显示计算值，但不产生运动话题副作用。
    void preview(const object_track::VelocityCommand& command, const std::string& reason) override {
        RCLCPP_INFO_THROTTLE(node_.get_logger(),
                             *node_.get_clock(),
                             1000,
                             "dry-run preview (%s): linear.x=%.3f angular.z=%.3f; not published",
                             reason.c_str(),
                             command.linear_x,
                             command.angular_z);
    }

    // 仅在显式关闭 dry-run 后创建并发布安全 Twist 消息。
    void publish(const object_track::VelocityCommand& command, const std::string& reason) override {
        if (!publisher_) {
            publisher_ = node_.create_publisher<geometry_msgs::msg::Twist>(output_topic_, 10);
        }

        geometry_msgs::msg::Twist message;
        message.linear.x  = command.linear_x;
        message.angular.z = command.angular_z;
        publisher_->publish(message);
        RCLCPP_INFO_THROTTLE(node_.get_logger(),
                             *node_.get_clock(),
                             1000,
                             "published velocity (%s): linear.x=%.3f angular.z=%.3f",
                             reason.c_str(),
                             command.linear_x,
                             command.angular_z);
    }

private:
    rclcpp::Node& node_;
    std::string output_topic_;
    rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr publisher_;
};

// 按实际图像宽高将检测框转换到 ROS 1 tracker 的逻辑坐标系。
cv::Rect logical_box(const robot_interfaces::msg::Det& detection, std::uint32_t image_width, std::uint32_t image_height) {
    const double width_scale  = kLogicalWidth / static_cast<double>(image_width);
    const double height_scale = kLogicalHeight / static_cast<double>(image_height);
    const int x1              = static_cast<int>(detection.x1 * width_scale);
    const int y1              = static_cast<int>(detection.y1 * height_scale);
    const int x2              = static_cast<int>(detection.x2 * width_scale);
    const int y2              = static_cast<int>(detection.y2 * height_scale);
    return {x1, y1, x2 - x1, y2 - y1};
}

// 按 ROS 1 规则选出面积严格大于阈值的最大 person 检测。
const robot_interfaces::msg::Det* select_target(
    const Detections& detections, std::uint32_t image_width, std::uint32_t image_height, const std::string& target_class, int minimum_area) {
    if (image_width == 0 || image_height == 0) return nullptr;

    const robot_interfaces::msg::Det* selected = nullptr;
    std::int64_t selected_area                 = minimum_area;
    for (const auto& detection : detections.detections) {
        if (detection.class_name != target_class || detection.x2 <= detection.x1 || detection.y2 <= detection.y1) {
            continue;
        }

        const cv::Rect box      = logical_box(detection, image_width, image_height);
        const std::int64_t area = static_cast<std::int64_t>(box.width) * box.height;
        if (area > selected_area) {
            selected      = &detection;
            selected_area = area;
        }
    }
    return selected;
}

// 接收图像与检测，按 header stamp 精确同步后生成跟踪输出。
class ObjectTrackNode : public rclcpp::Node {
public:
    // 声明兼容源行为的控制参数并连接输入、输出话题。
    ObjectTrackNode() : Node("object_track") {
        image_topic_      = declare_parameter<std::string>("image_topic", "/camera/image_det");
        detections_topic_ = declare_parameter<std::string>("input_topic", "/ai_msg_det");
        annotated_topic_  = declare_parameter<std::string>("annotated_topic", "/camera/image_det_track");
        output_topic_     = declare_parameter<std::string>("output_topic", "/tracking/cmd_vel_safe");
        target_class_     = declare_parameter<std::string>("target_class", "person");
        gain_             = declare_parameter<double>("angular_gain", 0.01);
        maximum_          = declare_parameter<double>("max_angular", 3.0);
        minimum_area_     = declare_parameter<int>("minimum_area", 20);
        dry_run_          = declare_parameter<bool>("dry_run", true);

        output_                     = std::make_unique<RosVelocityOutputPort>(*this, output_topic_);
        const auto sensor_qos       = rclcpp::QoS(rclcpp::KeepLast(10)).best_effort().durability_volatile();
        const auto image_output_qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable().durability_volatile();
        annotated_publisher_        = create_publisher<Image>(annotated_topic_, image_output_qos);
        image_subscription_.subscribe(this, image_topic_, sensor_qos.get_rmw_qos_profile());
        detections_subscription_.subscribe(this, detections_topic_, sensor_qos.get_rmw_qos_profile());
        synchronizer_ = std::make_unique<ImageDetectionSynchronizer>(ExactTimePolicy(kSynchronizationQueueSize), image_subscription_, detections_subscription_);
        synchronizer_->registerCallback(std::bind(&ObjectTrackNode::sync_callback, this, std::placeholders::_1, std::placeholders::_2));
        enable_subscription_ =
            create_subscription<std_msgs::msg::Bool>("/enable_tracking", 10, [this](std_msgs::msg::Bool::SharedPtr message) { set_enabled(message->data); });

        RCLCPP_INFO(get_logger(),
                    "dry_run=%s image_topic=%s detections_topic=%s annotated_topic=%s output_topic=%s",
                    dry_run_ ? "true" : "false",
                    image_topic_.c_str(),
                    detections_topic_.c_str(),
                    annotated_topic_.c_str(),
                    output_topic_.c_str());
    }

private:
    // 接收 ExactTime 同步器提供的图像和检测，并生成跟踪输出。
    void sync_callback(const Image::ConstSharedPtr& image, const Detections::ConstSharedPtr& detections) {
        const auto* selected = select_target(*detections, image->width, image->height, target_class_, minimum_area_);
        if (enabled_ && selected != nullptr) {
            const cv::Rect target = logical_box(*selected, image->width, image->height);
            const double center_x = target.x + target.width * 0.5;
            emit_command({0.0, object_track::angular_command(center_x, kLogicalWidth, gain_, maximum_)}, "target acquired/updated");
        } else if (enabled_ && has_target_) {
            emit_stop("target lost");
        }
        has_target_ = selected != nullptr;
        publish_annotation(*image, selected);
    }

    // 在输入图像副本上绘制目标框和当前跟踪状态并保留原始 header。
    void publish_annotation(const Image& image, const robot_interfaces::msg::Det* selected) {
        if (image.width == 0 || image.height == 0 || image.step < image.width * 3U || image.data.size() < static_cast<std::size_t>(image.step) * image.height ||
            (image.encoding != "rgb8" && image.encoding != "bgr8")) {
            RCLCPP_WARN_THROTTLE(get_logger(),
                                 *get_clock(),
                                 5000,
                                 "unsupported tracking image layout: encoding=%s width=%u height=%u step=%u",
                                 image.encoding.c_str(),
                                 image.width,
                                 image.height,
                                 image.step);
            return;
        }

        Image annotated = image;
        cv::Mat frame(static_cast<int>(annotated.height), static_cast<int>(annotated.width), CV_8UC3, annotated.data.data(), annotated.step);
        const cv::Scalar highlight = image.encoding == "rgb8" ? cv::Scalar(255, 0, 0) : cv::Scalar(0, 0, 255);
        std::string status         = enabled_ ? "tracking enabled" : "tracking disabled";
        if (selected != nullptr) {
            cv::rectangle(frame, cv::Point(selected->x1, selected->y1), cv::Point(selected->x2, selected->y2), highlight, 3);
            status += " target=" + std::to_string(selected->x1 + (selected->x2 - selected->x1) / 2);
        } else {
            status += " target=none";
        }
        cv::putText(frame, status, cv::Point(12, 28), cv::FONT_HERSHEY_SIMPLEX, 0.7, highlight, 2);
        annotated_publisher_->publish(std::move(annotated));
    }

    // 应用 enable 控制，并在关闭时立即输出零命令。
    void set_enabled(bool enabled) {
        enabled_ = enabled;
        if (!enabled_) {
            has_target_ = false;
            emit_stop("disabled");
        }
        RCLCPP_INFO(get_logger(), "tracking %s", enabled_ ? "enabled" : "disabled");
    }

    // 通过统一输出端口处理 dry-run 预览或安全 Twist 发布。
    void emit_command(const object_track::VelocityCommand& command, const char* reason) { object_track::emit_velocity(*output_, dry_run_, command, reason); }

    // 将目标丢失或禁用状态转换为零速度命令。
    void emit_stop(const char* reason) { emit_command(object_track::VelocityCommand{0.0, 0.0}, reason); }

    std::string image_topic_, detections_topic_, annotated_topic_, output_topic_, target_class_;
    double gain_{0.01};
    double maximum_{3.0};
    int minimum_area_{20};
    bool dry_run_{true};
    bool enabled_{false};
    bool has_target_{false};
    std::unique_ptr<object_track::VelocityOutputPort> output_;
    rclcpp::Publisher<Image>::SharedPtr annotated_publisher_;
    message_filters::Subscriber<Image> image_subscription_;
    message_filters::Subscriber<Detections> detections_subscription_;
    std::unique_ptr<ImageDetectionSynchronizer> synchronizer_;
    rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
};

}  // namespace

// 启动跟踪节点并运行 ROS 2 executor。
int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<ObjectTrackNode>());
    rclcpp::shutdown();
    return 0;
}
