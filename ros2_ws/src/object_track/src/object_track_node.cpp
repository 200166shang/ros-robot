#include <message_filters/subscriber.h>
#include <message_filters/sync_policies/exact_time.h>
#include <message_filters/synchronizer.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <geometry_msgs/msg/twist.hpp>
#include <limits>
#include <memory>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <std_msgs/msg/bool.hpp>
#include <string>
#include <utility>
#include <vector>

#include "object_track/tracking_math.hpp"
#include "object_track/tracking_output.hpp"

namespace {

using Image                      = sensor_msgs::msg::Image;
using Detections                 = robot_interfaces::msg::Dets;
using LaserScan                  = sensor_msgs::msg::LaserScan;
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
        image_topic_                  = declare_parameter<std::string>("image_topic", "/camera/image_det");
        detections_topic_             = declare_parameter<std::string>("input_topic", "/ai_msg_det");
        annotated_topic_              = declare_parameter<std::string>("annotated_topic", "/camera/image_det_track");
        output_topic_                 = declare_parameter<std::string>("output_topic", "/tracking/cmd_vel_safe");
        target_class_                 = declare_parameter<std::string>("target_class", "person");
        gain_                         = declare_parameter<double>("angular_gain", 0.01);
        maximum_                      = declare_parameter<double>("max_angular", 3.0);
        minimum_area_                 = declare_parameter<int>("minimum_area", 20);
        dry_run_                      = declare_parameter<bool>("dry_run", true);
        lidar_topic_                  = declare_parameter<std::string>("lidar_topic", "/scan");
        linear_control_.enabled       = declare_parameter<bool>("control_linear", true);
        linear_control_.gain          = declare_parameter<double>("linear_gain", 0.5);
        linear_control_.maximum_speed = declare_parameter<double>("max_linear", 0.15);
        linear_control_.keep_distance = declare_parameter<double>("keep_distance", 0.3);
        linear_control_.minimum_range = declare_parameter<double>("minimum_range", 0.05);
        linear_control_.maximum_range = declare_parameter<double>("maximum_range", 5.0);
        camera_model_.fx              = declare_parameter<double>("camera_fx", 1410.6);
        camera_model_.fy              = declare_parameter<double>("camera_fy", 1410.6);
        camera_model_.cx              = declare_parameter<double>("camera_cx", 640.0);
        camera_model_.cy              = declare_parameter<double>("camera_cy", 360.0);
        lidar_transform_.x            = declare_parameter<double>("lidar_to_camera_x", 0.20);
        lidar_transform_.y            = declare_parameter<double>("lidar_to_camera_y", 0.0);
        lidar_transform_.z            = declare_parameter<double>("lidar_to_camera_z", 0.0);
        lidar_transform_.roll         = declare_parameter<double>("lidar_to_camera_roll", 1.5707963267948966);
        lidar_transform_.pitch        = declare_parameter<double>("lidar_to_camera_pitch", -1.5707963267948966);
        lidar_transform_.yaw          = declare_parameter<double>("lidar_to_camera_yaw", 0.0);

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
        lidar_enable_subscription_ =
            create_subscription<std_msgs::msg::Bool>("/enable_lidar", 10, [this](std_msgs::msg::Bool::SharedPtr message) { set_lidar_enabled(message->data); });

        RCLCPP_INFO(get_logger(),
                    "dry_run=%s image_topic=%s detections_topic=%s annotated_topic=%s output_topic=%s lidar_topic=%s",
                    dry_run_ ? "true" : "false",
                    image_topic_.c_str(),
                    detections_topic_.c_str(),
                    annotated_topic_.c_str(),
                    output_topic_.c_str(),
                    lidar_topic_.c_str());
    }

private:
    // 接收 ExactTime 同步器提供的图像和检测，并生成跟踪输出。
    void sync_callback(const Image::ConstSharedPtr& image, const Detections::ConstSharedPtr& detections) {
        const auto* selected = select_target(*detections, image->width, image->height, target_class_, minimum_area_);
        update_projected_scan(image->width, image->height, selected);
        last_angular_command_ = 0.0;
        last_linear_command_  = !enabled_ || selected == nullptr ? 0.0 : object_track::linear_command(target_range_, linear_control_);
        if (enabled_ && selected != nullptr) {
            const cv::Rect target = logical_box(*selected, image->width, image->height);
            const double center_x = target.x + target.width * 0.5;
            last_angular_command_ = object_track::angular_command(center_x, kLogicalWidth, gain_, maximum_);
            const std::string reason =
                std::isfinite(target_range_) ? "target acquired/updated range=" + std::to_string(target_range_) + "m" : "target acquired/updated range=--";
            emit_command({last_linear_command_, last_angular_command_}, reason.c_str());
        } else if (enabled_ && has_target_) {
            emit_stop("target lost");
            last_linear_command_  = 0.0;
            last_angular_command_ = 0.0;
        }
        has_target_ = selected != nullptr;
        publish_annotation(*image, selected);
    }

    // 将当前扫描投影到图像，并按所选目标的水平范围更新距离估计。
    void update_projected_scan(std::uint32_t image_width, std::uint32_t image_height, const robot_interfaces::msg::Det* selected) {
        projected_points_.clear();
        target_range_ = std::numeric_limits<double>::quiet_NaN();
        if (!lidar_enabled_ || !latest_scan_) {
            return;
        }

        const object_track::LaserScanGeometry scan_geometry{
            latest_scan_->angle_min, latest_scan_->angle_increment, latest_scan_->range_min, latest_scan_->range_max};
        const object_track::ImageSize image_size{static_cast<double>(image_width), static_cast<double>(image_height)};
        projected_points_ = object_track::project_laser_scan(latest_scan_->ranges, scan_geometry, lidar_transform_, camera_model_, image_size);
        if (selected != nullptr) {
            target_range_ = object_track::nearest_range_in_horizontal_span(projected_points_, selected->x1, selected->x2);
        }
    }

    // 按 /enable_lidar 延迟创建或销毁扫描订阅，并清理禁用后的传感器状态。
    void set_lidar_enabled(bool enabled) {
        if (enabled == lidar_enabled_) {
            return;
        }
        lidar_enabled_ = enabled;
        if (lidar_enabled_) {
            const auto sensor_qos = rclcpp::QoS(rclcpp::KeepLast(10)).best_effort().durability_volatile();
            scan_subscription_ =
                create_subscription<LaserScan>(lidar_topic_, sensor_qos, [this](LaserScan::ConstSharedPtr message) { latest_scan_ = std::move(message); });
        } else {
            scan_subscription_.reset();
            latest_scan_.reset();
            projected_points_.clear();
            target_range_        = std::numeric_limits<double>::quiet_NaN();
            last_linear_command_ = 0.0;
            if (has_target_) {
                emit_command({0.0, last_angular_command_}, "lidar disabled range=--");
            }
        }
        RCLCPP_INFO(get_logger(), "lidar %s", lidar_enabled_ ? "enabled" : "disabled");
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
        const cv::Scalar projected_color(0, 255, 0);
        std::string status = enabled_ ? "tracking enabled" : "tracking disabled";
        for (const auto& point : projected_points_) {
            cv::circle(frame, cv::Point(static_cast<int>(std::lround(point.x)), static_cast<int>(std::lround(point.y))), 3, projected_color, cv::FILLED);
        }
        if (selected != nullptr) {
            cv::rectangle(frame, cv::Point(selected->x1, selected->y1), cv::Point(selected->x2, selected->y2), highlight, 3);
            status += " target=" + std::to_string(selected->x1 + (selected->x2 - selected->x1) / 2);
        } else {
            status += " target=none";
        }
        status += std::isfinite(target_range_) ? " range=" + std::to_string(target_range_) + "m" : " range=--";
        status += " linear=" + std::to_string(last_linear_command_);
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
    std::string lidar_topic_;
    double gain_{0.01};
    double maximum_{3.0};
    int minimum_area_{20};
    bool dry_run_{true};
    bool enabled_{false};
    bool has_target_{false};
    bool lidar_enabled_{false};
    object_track::LinearControl linear_control_;
    double target_range_{std::numeric_limits<double>::quiet_NaN()};
    double last_linear_command_{0.0};
    double last_angular_command_{0.0};
    object_track::CameraProjectionModel camera_model_;
    object_track::LidarToCameraTransform lidar_transform_;
    std::vector<object_track::ProjectedScanPoint> projected_points_;
    LaserScan::ConstSharedPtr latest_scan_;
    std::unique_ptr<object_track::VelocityOutputPort> output_;
    rclcpp::Publisher<Image>::SharedPtr annotated_publisher_;
    message_filters::Subscriber<Image> image_subscription_;
    message_filters::Subscriber<Detections> detections_subscription_;
    std::unique_ptr<ImageDetectionSynchronizer> synchronizer_;
    rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
    rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr lidar_enable_subscription_;
    rclcpp::Subscription<LaserScan>::SharedPtr scan_subscription_;
};

}  // namespace

// 初始化 ROS 2 并运行跟踪节点 executor。
int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<ObjectTrackNode>());
    rclcpp::shutdown();
    return 0;
}
