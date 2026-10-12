#include <message_filters/subscriber.h>
#include <message_filters/sync_policies/exact_time.h>
#include <message_filters/synchronizer.h>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/exceptions.h>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

#include <algorithm>
#include <chrono>
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
    ObjectTrackNode() : Node("object_track"), tf_buffer_(get_clock()), tf_listener_(tf_buffer_) {
        image_topic_                       = declare_parameter<std::string>("image_topic", "/camera/image_det");
        detections_topic_                  = declare_parameter<std::string>("input_topic", "/ai_msg_det");
        annotated_topic_                   = declare_parameter<std::string>("annotated_topic", "/camera/image_det_track");
        output_topic_                      = declare_parameter<std::string>("output_topic", "/tracking/cmd_vel_safe");
        target_class_                      = declare_parameter<std::string>("target_class", "person");
        gain_                              = declare_parameter<double>("angular_gain", 0.01);
        maximum_                           = declare_parameter<double>("max_angular", 3.0);
        minimum_area_                      = declare_parameter<int>("minimum_area", 20);
        dry_run_                           = declare_parameter<bool>("dry_run", true);
        lidar_topic_                       = declare_parameter<std::string>("lidar_topic", "/scan");
        linear_control_.enabled            = declare_parameter<bool>("control_linear", true);
        linear_control_.gain               = declare_parameter<double>("linear_gain", 0.5);
        linear_control_.maximum_speed      = declare_parameter<double>("max_linear", 0.15);
        linear_control_.keep_distance      = declare_parameter<double>("keep_distance", 0.3);
        linear_control_.minimum_range      = declare_parameter<double>("minimum_range", 0.05);
        linear_control_.maximum_range      = declare_parameter<double>("maximum_range", 5.0);
        camera_model_.fx                   = declare_parameter<double>("camera_fx", 1410.6);
        camera_model_.fy                   = declare_parameter<double>("camera_fy", 1410.6);
        camera_model_.cx                   = declare_parameter<double>("camera_cx", 640.0);
        camera_model_.cy                   = declare_parameter<double>("camera_cy", 360.0);
        camera_frame_                      = declare_parameter<std::string>("camera_frame", "camera");
        laser_frame_                       = declare_parameter<std::string>("laser_frame", "laser_link");
        const double transform_timeout_sec = declare_parameter<double>("transform_timeout_sec", 10.0);
        start_lidar_transform_wait(transform_timeout_sec);

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
    // 等待固定 laser 到 camera optical frame 的 TF，并在截止时间内完成一次读取。
    void start_lidar_transform_wait(double timeout_sec) {
        const auto timeout  = std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(std::max(0.0, timeout_sec)));
        transform_deadline_ = std::chrono::steady_clock::now() + timeout;
        transform_timer_    = create_wall_timer(std::chrono::milliseconds(100), std::bind(&ObjectTrackNode::poll_lidar_transform, this));
    }

    // 在 TF 到达后读取固定 laser 到 camera optical frame 的变换。
    bool load_lidar_transform() {
        const bool frames_ready = tf_buffer_._frameExists(camera_frame_) && tf_buffer_._frameExists(laser_frame_);
        if (!frames_ready) {
            return false;
        }

        try {
            const auto transform    = tf_buffer_.lookupTransform(camera_frame_, laser_frame_, rclcpp::Time(0));
            const auto& translation = transform.transform.translation;
            const auto& rotation    = transform.transform.rotation;
            const tf2::Quaternion quaternion(rotation.x, rotation.y, rotation.z, rotation.w);
            tf2::Matrix3x3(quaternion).getRPY(lidar_transform_.roll, lidar_transform_.pitch, lidar_transform_.yaw);
            lidar_transform_.x     = translation.x;
            lidar_transform_.y     = translation.y;
            lidar_transform_.z     = translation.z;
            lidar_transform_ready_ = true;
            RCLCPP_INFO(get_logger(), "loaded transform %s <- %s", camera_frame_.c_str(), laser_frame_.c_str());
            return true;
        } catch (const tf2::TransformException& error) {
            RCLCPP_DEBUG(get_logger(), "waiting for transform %s <- %s: %s", camera_frame_.c_str(), laser_frame_.c_str(), error.what());
            return false;
        }
    }

    // 定期检查 TF 到达状态，并在超时后停止等待。
    void poll_lidar_transform() {
        if (load_lidar_transform()) {
            transform_timer_->cancel();
            return;
        }
        if (std::chrono::steady_clock::now() >= transform_deadline_) {
            RCLCPP_ERROR(get_logger(), "timed out waiting for transform %s <- %s", camera_frame_.c_str(), laser_frame_.c_str());
            transform_timer_->cancel();
        }
    }

    // 接收 ExactTime 同步器提供的图像和检测，并生成跟踪输出。
    void sync_callback(const Image::ConstSharedPtr& image, const Detections::ConstSharedPtr& detections) {
        const auto* selected = select_target(*detections, image->width, image->height, target_class_, minimum_area_);
        if (selected != nullptr) {
            target_left_  = selected->x1;
            target_right_ = selected->x2;
        }
        last_angular_command_ = 0.0;
        last_linear_command_  = selected == nullptr ? 0.0 : object_track::linear_command(target_range_, linear_control_);
        if (selected != nullptr) {
            const cv::Rect target = logical_box(*selected, image->width, image->height);
            const double center_x = target.x + target.width * 0.5;
            last_angular_command_ = object_track::angular_command(center_x, kLogicalWidth, gain_, maximum_);
        }
        if (enabled_) {
            const std::string reason = selected == nullptr ? "no target found" : "target acquired/updated range=" + std::to_string(target_range_) + "m";
            emit_command({last_linear_command_, last_angular_command_}, reason.c_str());
        }
        publish_annotation(*image, selected);
    }

    // 收到独立 LaserScan 后变换并投影点位，同时更新目标水平跨度内的最近距离。
    void scan_callback(LaserScan::ConstSharedPtr scan) {
        if (!lidar_transform_ready_) {
            return;
        }

        const object_track::LaserScanGeometry scan_geometry{scan->angle_min, scan->angle_increment, scan->range_min, scan->range_max};
        const object_track::ImageSize image_size{camera_model_.cx * 2.0, camera_model_.cy * 2.0};
        projected_points_ = object_track::project_laser_scan(scan->ranges, scan_geometry, lidar_transform_, camera_model_, image_size);
        target_range_     = object_track::nearest_range_in_horizontal_span(projected_points_, target_left_, target_right_);
        if (!std::isfinite(target_range_)) {
            target_range_ = scan->range_max;
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
                create_subscription<LaserScan>(lidar_topic_, sensor_qos, std::bind(&ObjectTrackNode::scan_callback, this, std::placeholders::_1));
        } else {
            scan_subscription_.reset();
            projected_points_.clear();
            target_range_        = 0.0;
            last_linear_command_ = 0.0;
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
        const cv::Scalar highlight(0, 255, 0);
        for (const auto& point : projected_points_) {
            const double radius = std::max(1.0, std::min(2.0 / std::abs(point.depth), 10.0));
            cv::circle(frame, cv::Point(static_cast<int>(point.x), static_cast<int>(point.y)), static_cast<int>(radius), highlight, cv::FILLED);
        }
        if (selected != nullptr) {
            cv::rectangle(frame, cv::Point(selected->x1, selected->y1), cv::Point(selected->x2, selected->y2), highlight, 3);
            const int object_center_x = selected->x1 + (selected->x2 - selected->x1) / 2;
            const auto status = cv::format("[px:%d,dis:%.2f] [vx:%.2f,vz:%.2f]", object_center_x, target_range_, last_linear_command_, last_angular_command_);
            cv::putText(frame, status, cv::Point(20, 20), cv::FONT_HERSHEY_SIMPLEX, 0.8, highlight, 2);
        } else {
            cv::putText(frame, "[No target found]", cv::Point(20, 20), cv::FONT_HERSHEY_SIMPLEX, 0.8, highlight, 2);
        }
        annotated_publisher_->publish(std::move(annotated));
    }

    // 应用 enable 状态切换，立即清零输出并重置扫描投影状态。
    void set_enabled(bool enabled) {
        enabled_ = enabled;
        projected_points_.clear();
        target_range_         = 0.0;
        last_linear_command_  = 0.0;
        last_angular_command_ = 0.0;
        emit_stop(enabled_ ? "enabled" : "disabled");
        RCLCPP_INFO(get_logger(), "tracking %s", enabled_ ? "enabled" : "disabled");
    }

    // 通过统一输出端口处理 dry-run 预览或安全 Twist 发布。
    void emit_command(const object_track::VelocityCommand& command, const char* reason) { object_track::emit_velocity(*output_, dry_run_, command, reason); }

    // 将目标丢失或禁用状态转换为零速度命令。
    void emit_stop(const char* reason) { emit_command(object_track::VelocityCommand{0.0, 0.0}, reason); }

    std::string image_topic_, detections_topic_, annotated_topic_, output_topic_, target_class_;
    std::string lidar_topic_, camera_frame_, laser_frame_;
    double gain_{0.01};
    double maximum_{3.0};
    int minimum_area_{20};
    bool dry_run_{true};
    bool enabled_{false};
    bool lidar_enabled_{false};
    bool lidar_transform_ready_{false};
    object_track::LinearControl linear_control_;
    double target_range_{0.0};
    double target_left_{0.0};
    double target_right_{0.0};
    double last_linear_command_{0.0};
    double last_angular_command_{0.0};
    object_track::CameraProjectionModel camera_model_;
    object_track::LidarToCameraTransform lidar_transform_;
    std::vector<object_track::ProjectedScanPoint> projected_points_;
    tf2_ros::Buffer tf_buffer_;
    tf2_ros::TransformListener tf_listener_;
    std::chrono::steady_clock::time_point transform_deadline_;
    rclcpp::TimerBase::SharedPtr transform_timer_;
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
