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
#include <std_srvs/srv/set_bool.hpp>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "object_track/tracking_math.hpp"
#include "object_track/tracking_output.hpp"

namespace {

using Image                      = sensor_msgs::msg::Image;
using Detections                 = robot_interfaces::msg::Dets;
using LaserScan                  = sensor_msgs::msg::LaserScan;
using SetBool                    = std_srvs::srv::SetBool;
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
        // 1. publisher 按需创建，保持 dry-run 路径不会意外创建速度话题。
        if (!publisher_) {
            publisher_ = node_.create_publisher<geometry_msgs::msg::Twist>(output_topic_, 10);
        }

        // 2. 只填写 tracker 当前控制的平移 x 和旋转 z 分量，再发布并记录节流日志。
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

// 按 x/y 方向分别缩放检测框，将实际图像坐标转换到 ROS 1 tracker 的 640×360 逻辑坐标系。
cv::Rect logical_box(const robot_interfaces::msg::Det& detection, std::uint32_t image_width, std::uint32_t image_height) {
    // x 方向比例为 640/图像宽度，y 方向比例为 360/图像高度。
    const double width_scale  = kLogicalWidth / static_cast<double>(image_width);
    const double height_scale = kLogicalHeight / static_cast<double>(image_height);
    const int x1              = static_cast<int>(detection.x1 * width_scale);
    const int y1              = static_cast<int>(detection.y1 * height_scale);
    const int x2              = static_cast<int>(detection.x2 * width_scale);
    const int y2              = static_cast<int>(detection.y2 * height_scale);
    return {x1, y1, x2 - x1, y2 - y1};
}

// 依次过滤类别与无效框，再选出逻辑坐标面积严格大于阈值的最大目标框。
const robot_interfaces::msg::Det* select_target(
    const Detections& detections, std::uint32_t image_width, std::uint32_t image_height, const std::string& target_class, int minimum_area) {
    // 无效图像尺寸无法换算检测面积，直接返回“未选到目标”。
    if (image_width == 0 || image_height == 0) return nullptr;

    const robot_interfaces::msg::Det* selected = nullptr;
    std::int64_t selected_area                 = minimum_area;
    for (const auto& detection : detections.detections) {
        // 类别不匹配、宽或高不为正的检测框都不参与面积比较。
        if (detection.class_name != target_class || detection.x2 <= detection.x1 || detection.y2 <= detection.y1) {
            continue;
        }

        // 把面积统一换算到 640×360 逻辑坐标，保持阈值与 ROS 1 tracker 一致。
        const cv::Rect box      = logical_box(detection, image_width, image_height);
        const std::int64_t area = static_cast<std::int64_t>(box.width) * box.height;

        // 仅当 area > minimum_area（或当前最大面积）时替换所选目标，面积相同时保留先出现者。
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
    // 初始化链路：读取参数 → 等待平台 TF → 创建输出/同步器和控制服务。
    ObjectTrackNode() : Node("object_track"), tf_buffer_(get_clock()) {
        // 1. 读取输入输出话题、目标筛选条件、角速度控制参数和 dry-run 开关。
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
        lidar_scan_timeout_sec_            = declare_parameter<double>("lidar_scan_timeout_sec", 1.0);

        if (!std::isfinite(lidar_scan_timeout_sec_) || lidar_scan_timeout_sec_ <= 0.0) {
            RCLCPP_FATAL(get_logger(), "lidar_scan_timeout_sec must be finite and greater than zero");
            throw std::invalid_argument("lidar_scan_timeout_sec must be greater than zero");
        }

        // 所有运行都使用距离安全门控；TF 可晚于节点到达，因此由定时器异步等待。
        tf_listener_ = std::make_unique<tf2_ros::TransformListener>(tf_buffer_);
        start_lidar_transform_wait(transform_timeout_sec);

        // 2. 创建 RosVelocityOutputPort 和标注 publisher；image/detections subscriber 接入 ExactTime 同步器并绑定 sync_callback。
        output_                     = std::make_unique<RosVelocityOutputPort>(*this, output_topic_);
        const auto sensor_qos       = rclcpp::QoS(rclcpp::KeepLast(10)).best_effort().durability_volatile();
        const auto image_output_qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable().durability_volatile();
        annotated_publisher_        = create_publisher<Image>(annotated_topic_, image_output_qos);
        image_subscription_.subscribe(this, image_topic_, sensor_qos.get_rmw_qos_profile());
        detections_subscription_.subscribe(this, detections_topic_, sensor_qos.get_rmw_qos_profile());
        synchronizer_ = std::make_unique<ImageDetectionSynchronizer>(ExactTimePolicy(kSynchronizationQueueSize), image_subscription_, detections_subscription_);
        synchronizer_->registerCallback(std::bind(&ObjectTrackNode::sync_callback, this, std::placeholders::_1, std::placeholders::_2));

        // 3. ROS 服务提供有回执的 Follow 与 LiDAR 融合控制。
        enable_service_       = create_service<SetBool>("/tracking/set_enabled",
                                                  [this](const std::shared_ptr<SetBool::Request> request, std::shared_ptr<SetBool::Response> response) {
                                                      response->success = apply_enabled(request->data, response->message);
                                                  });
        lidar_enable_service_ = create_service<SetBool>("/tracking/set_lidar_enabled",
                                                        [this](const std::shared_ptr<SetBool::Request> request, std::shared_ptr<SetBool::Response> response) {
                                                            response->success = apply_lidar_enabled(request->data, response->message);
                                                        });
        // 相机同步输入可能同时中断，因此扫描超时必须由独立定时检查触发安全停止。
        lidar_freshness_timer_ = create_wall_timer(std::chrono::milliseconds(100), std::bind(&ObjectTrackNode::check_lidar_scan_freshness, this));
        RCLCPP_INFO(get_logger(),
                    "follow standby; dry_run=%s image_topic=%s detections_topic=%s annotated_topic=%s output_topic=%s lidar_topic=%s",
                    dry_run_ ? "true" : "false",
                    image_topic_.c_str(),
                    detections_topic_.c_str(),
                    annotated_topic_.c_str(),
                    output_topic_.c_str(),
                    lidar_topic_.c_str());
    }

private:
    // 记录 TF 等待期限并每 100 ms 检查一次；等待期间节点的图像和控制订阅仍可正常工作。
    void start_lidar_transform_wait(double timeout_sec) {
        // 负超时按 0 秒处理，第一次轮询未找到 TF 时就会结束等待。
        const auto timeout  = std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(std::max(0.0, timeout_sec)));
        transform_deadline_ = std::chrono::steady_clock::now() + timeout;
        transform_timer_    = create_wall_timer(std::chrono::milliseconds(100), std::bind(&ObjectTrackNode::poll_lidar_transform, this));
    }

    // 把 TF 树中的 camera_frame <- laser_frame 变换读入投影参数。
    bool load_lidar_transform() {
        // 1. 先确认两个 frame 都已注册，避免 TF 尚未到达时反复执行失败查询。
        const bool frames_ready = tf_buffer_._frameExists(camera_frame_) && tf_buffer_._frameExists(laser_frame_);
        if (!frames_ready) {
            return false;
        }

        try {
            // 2. 查询目标 camera、源 laser 的变换，即把雷达点转换到相机投影坐标系。
            const auto transform    = tf_buffer_.lookupTransform(camera_frame_, laser_frame_, rclcpp::Time(0));
            const auto& translation = transform.transform.translation;
            const auto& rotation    = transform.transform.rotation;

            // 3. 直接保存 TF 旋转矩阵，避免平台 pitch=-π/2 时欧拉角分解丢失旋转。
            const tf2::Quaternion quaternion(rotation.x, rotation.y, rotation.z, rotation.w);
            const tf2::Matrix3x3 rotation_matrix(quaternion);
            for (int row = 0; row < 3; ++row) {
                for (int column = 0; column < 3; ++column) {
                    lidar_transform_.rotation[row * 3 + column] = rotation_matrix[row][column];
                }
            }
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

    // 轮询加载 TF；加载成功或超过截止时间后都取消定时器，避免重复处理。
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

    // 处理链路：select_target → 保存目标横边界 → 计算线/角速度 → emit_command → publish_annotation。
    void sync_callback(const Image::ConstSharedPtr& image, const Detections::ConstSharedPtr& detections) {
        // ExactTime 同步已证明本节点至少收到一组成对输入；空检测集也表示输入就绪。
        inputs_ready_ = true;

        // 1. select_target 选最大目标框；保存当前横边界，目标丢失时清空区间和距离。
        const auto* selected = select_target(*detections, image->width, image->height, target_class_, minimum_area_);
        if (selected != nullptr) {
            target_left_  = selected->x1;
            target_right_ = selected->x2;
        } else {
            target_left_  = 0.0;
            target_right_ = 0.0;
            target_range_ = std::numeric_limits<double>::infinity();
        }

        const bool scan_is_recent = has_recent_lidar_scan();
        const bool scan_expired   = is_lidar_scan_expired(scan_is_recent);
        const bool range_ready    = lidar_enabled_ && lidar_transform_ready_ && scan_is_recent;
        if (!range_ready) {
            // 距离融合未就绪时不按图像继续跟随，避免缺少量程时仍输出非零控制。
            stop_follow_without_fresh_lidar_scan(scan_expired);
            publish_annotation(*image, selected);
            return;
        }

        // 2. 按当前目标重新筛选新鲜投影点，避免切换目标时沿用前一个框的距离。
        target_range_         = object_track::nearest_range_in_horizontal_span(projected_points_, target_left_, target_right_);
        last_angular_command_ = 0.0;
        last_linear_command_  = 0.0;
        if (selected != nullptr && std::isfinite(target_range_)) {
            // 缺少当前目标量程时两个速度分量都保持零，禁止仅按图像转向。
            last_linear_command_  = object_track::linear_command(target_range_, linear_control_);
            const cv::Rect target = logical_box(*selected, image->width, image->height);
            const double center_x = target.x + target.width * 0.5;

            // 角速度公式为 w=angular_gain*(320-center_x)：目标在图像左侧时 w 为正，函数内再做 ±max_angular 限幅。
            last_angular_command_ = object_track::angular_command(center_x, kLogicalWidth, gain_, maximum_);
        }

        // 3. 使能时 emit_command → emit_velocity → preview/publish；dry_run=true 只预览，不发布 Twist。
        if (enabled_) {
            const std::string reason = selected == nullptr ? "no target found" : "target acquired/updated range=" + std::to_string(target_range_) + "m";
            emit_command({last_linear_command_, last_angular_command_}, reason.c_str());
        }

        // 4. publish_annotation 在输入图像副本上画点、目标框和状态，控制关闭时也照常发布图像。
        publish_annotation(*image, selected);
    }

    // 扫描处理链路：校验 TF → project_laser_scan → nearest_range_in_horizontal_span → 保存点和距离。
    void scan_callback(LaserScan::ConstSharedPtr scan) {
        // 1. TF 未就绪时不使用默认外参，避免产生看似有效但坐标错误的投影点。
        if (!lidar_transform_ready_) {
            return;
        }

        last_lidar_scan_at_         = std::chrono::steady_clock::now();
        lidar_scan_received_        = true;
        lidar_timeout_stop_emitted_ = false;

        // 2. 用当前 scan 元数据解释 ranges；图像大小按 2*cx × 2*cy 推得（默认 1280×720）。
        const object_track::LaserScanGeometry scan_geometry{scan->angle_min, scan->angle_increment, scan->range_min, scan->range_max};
        const object_track::ImageSize image_size{camera_model_.cx * 2.0, camera_model_.cy * 2.0};

        // 3. project_laser_scan 返回图像内点；nearest_range_in_horizontal_span 只检查目标框横向开区间。
        projected_points_ = object_track::project_laser_scan(scan->ranges, scan_geometry, lidar_transform_, camera_model_, image_size);
        target_range_     = object_track::nearest_range_in_horizontal_span(projected_points_, target_left_, target_right_);
    }

    // 校验融合依赖后切换 tracker 的 LiDAR 使用状态，不控制 LiDAR 驱动进程。
    bool apply_lidar_enabled(bool enabled, std::string& message) {
        if (enabled == lidar_enabled_) {
            message = enabled ? "LiDAR fusion enabled" : "LiDAR fusion disabled";
            return true;
        }

        // 启动等待超时后，操作员仍可在 TF 就绪时通过服务重新加载并开启融合。
        if (enabled && !lidar_transform_ready_ && !load_lidar_transform()) {
            message = "LiDAR fusion is not ready: waiting for camera <- laser TF";
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        if (enabled && count_publishers(lidar_topic_) == 0) {
            message = "LiDAR fusion is not ready: no active publisher on " + lidar_topic_;
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        lidar_enabled_ = enabled;
        if (lidar_enabled_) {
            // 只有显式开启融合后才订阅扫描，并使用与扫描发布端兼容的 best-effort QoS。
            const auto sensor_qos = rclcpp::QoS(rclcpp::KeepLast(10)).best_effort().durability_volatile();
            scan_subscription_ =
                create_subscription<LaserScan>(lidar_topic_, sensor_qos, std::bind(&ObjectTrackNode::scan_callback, this, std::placeholders::_1));
        } else {
            // 先销毁订阅，再清空点位和距离，后续图像不再受已停用的扫描影响。
            scan_subscription_.reset();
            clear_lidar_control_state();
            lidar_scan_received_        = false;
            lidar_timeout_stop_emitted_ = false;
            if (enabled_) {
                enabled_ = false;
                emit_stop("LiDAR fusion disabled");
                RCLCPP_INFO(get_logger(), "tracking standby because LiDAR fusion was disabled");
            }
        }
        message = lidar_enabled_ ? "LiDAR fusion enabled" : "LiDAR fusion disabled";
        RCLCPP_INFO(get_logger(), "%s", message.c_str());
        return true;
    }

    // 校验图像布局后，在副本上画投影点、目标框和控制状态，最后保留原始 header 发布。
    void publish_annotation(const Image& image, const robot_interfaces::msg::Det* selected) {
        // 1. 仅接受有效尺寸、步长和三通道 RGB/BGR 图像；布局异常时不发布损坏输出。
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

        // 2. 点半径按相机深度反比缩放：r=2/|Z|，并限制在 1 到 10 像素之间。
        for (const auto& point : projected_points_) {
            const double radius = std::max(1.0, std::min(2.0 / std::abs(point.depth), 10.0));
            cv::circle(frame, cv::Point(static_cast<int>(point.x), static_cast<int>(point.y)), static_cast<int>(radius), highlight, cv::FILLED);
        }

        // 3. 有目标时显示像素中心、距离和速度；没有目标时显示源节点的提示文字。
        if (selected != nullptr) {
            cv::rectangle(frame, cv::Point(selected->x1, selected->y1), cv::Point(selected->x2, selected->y2), highlight, 3);
            const int object_center_x = selected->x1 + (selected->x2 - selected->x1) / 2;
            const auto status = cv::format("[px:%d,dis:%.2f] [vx:%.2f,vz:%.2f]", object_center_x, target_range_, last_linear_command_, last_angular_command_);
            cv::putText(frame, status, cv::Point(20, 20), cv::FONT_HERSHEY_SIMPLEX, 0.8, highlight, 2);
        } else {
            cv::putText(frame, "[No target found]", cv::Point(20, 20), cv::FONT_HERSHEY_SIMPLEX, 0.8, highlight, 2);
        }

        // 4. 从输入图像复制像素再绘制，因此 header、时间戳和 frame_id 都保持不变。
        annotated_publisher_->publish(std::move(annotated));
    }

    // 校验数据就绪后切换 Follow 状态；没有 person 仍允许开启并等待后续检测。
    bool apply_enabled(bool enabled, std::string& message) {
        if (enabled && !inputs_ready_) {
            message = "Follow is not ready: waiting for the first synchronized image and detection inputs";
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        if (enabled && !lidar_enabled_) {
            message = "Follow is not ready: enable LiDAR fusion first";
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        if (enabled && !lidar_transform_ready_) {
            message = "Follow is not ready: waiting for camera <- laser TF";
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        if (enabled && !has_recent_lidar_scan()) {
            message = "Follow is not ready: waiting for a recent LaserScan on " + lidar_topic_;
            RCLCPP_WARN(get_logger(), "%s", message.c_str());
            return false;
        }

        if (enabled == enabled_) {
            message = enabled ? "Follow enabled" : "Follow standby";
            return true;
        }

        // 1. 更新状态并清理启停之间不可复用的距离、点位和上次控制量。
        enabled_ = enabled;
        projected_points_.clear();
        target_range_         = 0.0;
        last_linear_command_  = 0.0;
        last_angular_command_ = 0.0;

        // 2. emit_stop 生成零命令并复用统一出口：dry-run 只预览，关闭 dry-run 才发布 Twist。
        emit_stop(enabled_ ? "enabled" : "disabled");
        RCLCPP_INFO(get_logger(), "tracking %s", enabled_ ? "enabled" : "disabled");
        message = enabled_ ? "Follow enabled" : "Follow standby";
        return true;
    }

    // 只接受超时窗口内的扫描，防止沿用过期距离结果。
    bool has_recent_lidar_scan() const {
        if (!lidar_scan_received_) {
            return false;
        }
        const auto scan_age = std::chrono::steady_clock::now() - last_lidar_scan_at_;
        return scan_age <= std::chrono::duration<double>(lidar_scan_timeout_sec_);
    }

    // 只有融合与 TF 已就绪且至少收到过扫描时，才将扫描判定为超时。
    bool is_lidar_scan_expired(bool scan_is_recent) const { return lidar_enabled_ && lidar_transform_ready_ && lidar_scan_received_ && !scan_is_recent; }

    // 扫描过期时清除不可继续用于控制或标注的距离、投影点和速度状态。
    void clear_lidar_control_state() {
        projected_points_.clear();
        target_range_         = 0.0;
        last_linear_command_  = 0.0;
        last_angular_command_ = 0.0;
    }

    // 统一处理量程不可用：清除旧控制状态，并在 Follow 运行时通过统一输出端口请求停止。
    void stop_follow_without_fresh_lidar_scan(bool scan_expired) {
        clear_lidar_control_state();
        if (!enabled_) {
            return;
        }

        // 同步输入分支先处理超时后设置此标志，定时器不会重复发送同一次停止。
        lidar_timeout_stop_emitted_ = scan_expired;
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "tracking paused: waiting for a recent LiDAR scan and camera <- laser TF");
        emit_stop("tracking waiting for LiDAR range");
    }

    // 即使没有新的相机帧，也在 Follow 使用 LiDAR 时监视扫描新鲜度并只发送一次超时停止。
    void check_lidar_scan_freshness() {
        const bool scan_expired = is_lidar_scan_expired(has_recent_lidar_scan());
        if (!enabled_ || !scan_expired || lidar_timeout_stop_emitted_) {
            return;
        }

        stop_follow_without_fresh_lidar_scan(true);
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
    bool inputs_ready_{false};
    bool lidar_transform_ready_{false};
    bool lidar_scan_received_{false};
    bool lidar_timeout_stop_emitted_{false};
    double lidar_scan_timeout_sec_{1.0};
    std::chrono::steady_clock::time_point last_lidar_scan_at_{};
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
    std::unique_ptr<tf2_ros::TransformListener> tf_listener_;
    std::chrono::steady_clock::time_point transform_deadline_;
    rclcpp::TimerBase::SharedPtr transform_timer_;
    rclcpp::TimerBase::SharedPtr lidar_freshness_timer_;
    std::unique_ptr<object_track::VelocityOutputPort> output_;
    rclcpp::Publisher<Image>::SharedPtr annotated_publisher_;
    message_filters::Subscriber<Image> image_subscription_;
    message_filters::Subscriber<Detections> detections_subscription_;
    std::unique_ptr<ImageDetectionSynchronizer> synchronizer_;
    rclcpp::Service<SetBool>::SharedPtr enable_service_;
    rclcpp::Service<SetBool>::SharedPtr lidar_enable_service_;
    rclcpp::Subscription<LaserScan>::SharedPtr scan_subscription_;
};

}  // namespace

// 入口顺序：初始化 ROS 2 → 构造并 spin 跟踪节点 → executor 退出后关闭 ROS 2。
int main(int argc, char** argv) {
    // 1. 初始化客户端库，使节点、订阅和发布端口可以创建。
    rclcpp::init(argc, argv);

    // 2. 节点构造时完成参数和接口接线；spin 持续处理图像、检测、扫描与开关回调。
    rclcpp::spin(std::make_shared<ObjectTrackNode>());

    // 3. spin 返回表示收到退出请求，随后统一释放 ROS 2 资源。
    rclcpp::shutdown();
    return 0;
}
