#include "object_track/tracking_math.hpp"
#include "object_track/tracking_output.hpp"

#include <geometry_msgs/msg/twist.hpp>
#include <rclcpp/rclcpp.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <std_msgs/msg/bool.hpp>

#include <algorithm>
#include <chrono>
#include <memory>
#include <string>
#include <utility>

class RosVelocityOutputPort final : public object_track::VelocityOutputPort {
 public:
  RosVelocityOutputPort(rclcpp::Node & node, std::string output_topic)
  : node_(node), output_topic_(std::move(output_topic)) {}

  void preview(const object_track::VelocityCommand & command,
               const std::string & reason) override {
    RCLCPP_INFO_THROTTLE(node_.get_logger(), *node_.get_clock(), 1000,
      "dry-run preview (%s): linear.x=%.3f angular.z=%.3f; not published",
      reason.c_str(), command.linear_x, command.angular_z);
  }

  void publish(const object_track::VelocityCommand & command,
               const std::string & reason) override {
    if (!publisher_) {
      publisher_ = node_.create_publisher<geometry_msgs::msg::Twist>(output_topic_, 10);
    }
    geometry_msgs::msg::Twist message;
    message.linear.x = command.linear_x;
    message.angular.z = command.angular_z;
    publisher_->publish(message);
    RCLCPP_INFO_THROTTLE(node_.get_logger(), *node_.get_clock(), 1000,
      "published velocity (%s): linear.x=%.3f angular.z=%.3f",
      reason.c_str(), command.linear_x, command.angular_z);
  }

 private:
  rclcpp::Node & node_;
  std::string output_topic_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr publisher_;
};

class ObjectTrackNode : public rclcpp::Node {
 public:
  ObjectTrackNode() : Node("object_track") {
    input_topic_ = declare_parameter<std::string>("input_topic", "/ai_msg_det");
    output_topic_ = declare_parameter<std::string>("output_topic", "/tracking/cmd_vel_safe");
    target_class_ = declare_parameter<std::string>("target_class", "person");
    gain_ = declare_parameter<double>("angular_gain", 0.003);
    maximum_ = declare_parameter<double>("max_angular", 1.0);
    minimum_area_ = declare_parameter<int>("minimum_area", 400);
    timeout_ms_ = declare_parameter<int>("target_timeout_ms", 500);
    dry_run_ = declare_parameter<bool>("dry_run", true);

    output_ = std::make_unique<RosVelocityOutputPort>(*this, output_topic_);
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    detection_subscription_ = create_subscription<robot_interfaces::msg::Dets>(
      input_topic_, qos, [this](robot_interfaces::msg::Dets::SharedPtr message) { update(message); });
    enable_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "/enable_tracking", 10, [this](std_msgs::msg::Bool::SharedPtr message) {
        enabled_ = message->data;
        if (!enabled_) emit_stop("disabled");
        RCLCPP_INFO(get_logger(), "tracking %s", enabled_ ? "enabled" : "disabled");
      });
    watchdog_ = create_wall_timer(std::chrono::milliseconds(100), [this] {
      if (enabled_ && has_target_ &&
          std::chrono::steady_clock::now() - last_target_ > std::chrono::milliseconds(timeout_ms_)) {
        has_target_ = false;
        emit_stop("target timeout");
      }
    });
    RCLCPP_INFO(get_logger(), "dry_run=%s configured_topic=%s",
      dry_run_ ? "true" : "false", output_topic_.c_str());
  }

 private:
  void update(const robot_interfaces::msg::Dets::SharedPtr & message) {
    if (!enabled_) return;
    const robot_interfaces::msg::Det * selected = nullptr;
    uint64_t selected_area = static_cast<uint64_t>(minimum_area_);
    for (const auto & detection : message->detections) {
      if (detection.class_name != target_class_ || detection.x2 <= detection.x1 || detection.y2 <= detection.y1) continue;
      const uint64_t area = static_cast<uint64_t>(detection.x2 - detection.x1) * (detection.y2 - detection.y1);
      if (area > selected_area) { selected = &detection; selected_area = area; }
    }
    if (!selected) {
      if (has_target_) emit_stop("target lost");
      has_target_ = false;
      return;
    }

    const double center = 0.5 * (selected->x1 + selected->x2);
    const object_track::VelocityCommand command{
      0.0, object_track::angular_command(center, message->image_width, gain_, maximum_)};
    emit_command(command, "target acquired/updated");
    has_target_ = true;
    last_target_ = std::chrono::steady_clock::now();
  }

  void emit_command(const object_track::VelocityCommand & command, const char * reason) {
    object_track::emit_velocity(*output_, dry_run_, command, reason);
  }

  void emit_stop(const char * reason) {
    emit_command(object_track::VelocityCommand{0.0, 0.0}, reason);
  }

  std::string input_topic_, output_topic_, target_class_;
  double gain_, maximum_;
  int minimum_area_, timeout_ms_;
  bool dry_run_, enabled_{false}, has_target_{false};
  std::chrono::steady_clock::time_point last_target_{};
  std::unique_ptr<object_track::VelocityOutputPort> output_;
  rclcpp::Subscription<robot_interfaces::msg::Dets>::SharedPtr detection_subscription_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
  rclcpp::TimerBase::SharedPtr watchdog_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ObjectTrackNode>());
  rclcpp::shutdown();
  return 0;
}
