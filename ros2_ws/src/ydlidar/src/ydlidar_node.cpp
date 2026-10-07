#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_srvs/srv/empty.hpp"
#include "ydlidar/ydlidar_node.hpp"

YdLidarNode::YdLidarNode(std::unique_ptr<ydlidar::LidarSource> source)
: Node("ydlidar"), source_(std::move(source)) {
  if (!source_) {
    throw std::invalid_argument("YdLidarNode requires a scan source");
  }

  const auto driver_type = declare_parameter<std::string>("lidar_driver_type", "ydlidar");
  if (driver_type != "ydlidar") {
    throw std::invalid_argument("Only lidar_driver_type=ydlidar is supported");
  }
  configuration_.port = declare_parameter<std::string>(
      "port", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0");
  configuration_.frame_id = declare_parameter<std::string>("frame_id", "laser_link");
  configuration_.ignore_array = declare_parameter<std::string>("ignore_array", "");
  configuration_.baudrate = declare_parameter<int>("baudrate", 115200);
  configuration_.lidar_type = declare_parameter<int>("lidar_type", 1);
  configuration_.device_type = declare_parameter<int>("device_type", 0);
  configuration_.sample_rate = declare_parameter<int>("sample_rate", 3);
  configuration_.abnormal_check_count = declare_parameter<int>("abnormal_check_count", 4);
  configuration_.fixed_resolution = declare_parameter<bool>("fixed_resolution", true);
  configuration_.auto_reconnect = declare_parameter<bool>("auto_reconnect", true);
  configuration_.reversion = declare_parameter<bool>("reversion", false);
  configuration_.inverted = declare_parameter<bool>("inverted", true);
  configuration_.single_channel = declare_parameter<bool>("isSingleChannel", true);
  configuration_.intensity = declare_parameter<bool>("intensity", false);
  configuration_.support_motor_dtr = declare_parameter<bool>("support_motor_dtr", true);
  configuration_.invalid_range_is_inf = declare_parameter<bool>("invalid_range_is_inf", false);
  configuration_.angle_min = static_cast<float>(declare_parameter<double>("angle_min", 0.0));
  configuration_.angle_max = static_cast<float>(declare_parameter<double>("angle_max", 180.0));
  configuration_.range_min = static_cast<float>(declare_parameter<double>("range_min", 0.1));
  configuration_.range_max = static_cast<float>(declare_parameter<double>("range_max", 10.0));
  configuration_.frequency = static_cast<float>(declare_parameter<double>("frequency", 10.0));

  scan_publisher_ = create_publisher<sensor_msgs::msg::LaserScan>("scan", 1);
  stop_scan_service_ = create_service<std_srvs::srv::Empty>(
      "stop_scan", [this](
          std::shared_ptr<std_srvs::srv::Empty::Request>,
          std::shared_ptr<std_srvs::srv::Empty::Response>) {
        RCLCPP_INFO(get_logger(), "Stop scan requested");
        auto_start_pending_ = false;
        if (scanning_ && !source_->stop()) {
          RCLCPP_ERROR(get_logger(), "Failed to stop scan: %s", source_->error().c_str());
          return;
        }
        scanning_ = false;
      });
  start_scan_service_ = create_service<std_srvs::srv::Empty>(
      "start_scan", [this](
          std::shared_ptr<std_srvs::srv::Empty::Request>,
          std::shared_ptr<std_srvs::srv::Empty::Response>) {
        RCLCPP_INFO(get_logger(), "Start scan requested");
        if (!initialized_) {
          RCLCPP_ERROR(get_logger(), "Cannot start scan before SDK initialization");
          return;
        }
        auto_start_pending_ = false;
        if (!scanning_) {
          scanning_ = source_->start();
          if (!scanning_) {
            RCLCPP_ERROR(get_logger(), "Failed to start scan: %s", source_->error().c_str());
          }
        }
      });

  initialized_ = source_->initialize(configuration_);
  if (!initialized_) {
    RCLCPP_FATAL(get_logger(), "YDLIDAR initialization failed: %s", source_->error().c_str());
  } else {
    scanning_ = source_->start();
    if (!scanning_) {
      RCLCPP_WARN(get_logger(), "Could not start scan yet: %s", source_->error().c_str());
    }
  }

  scan_timer_ = create_wall_timer(
      std::chrono::milliseconds(33), std::bind(&YdLidarNode::publish_scan, this));
}

YdLidarNode::~YdLidarNode() {
  if (scanning_) {
    source_->stop();
    scanning_ = false;
  }
  if (initialized_) {
    source_->disconnect();
    initialized_ = false;
  }
}

void YdLidarNode::publish_scan() {
  if (!initialized_) {
    return;
  }
  if (!scanning_) {
    if (auto_start_pending_) {
      scanning_ = source_->start();
      if (!scanning_) {
        RCLCPP_WARN_THROTTLE(
            get_logger(), *get_clock(), 5000, "Could not start scan: %s",
            source_->error().c_str());
      }
    }
    return;
  }

  ydlidar::Scan scan;
  if (!source_->read(scan) || scan.angle_increment <= 0.0F) {
    return;
  }
  sensor_msgs::msg::LaserScan message;
  message.header.stamp.sec = static_cast<int32_t>(scan.stamp_ns / 1000000000ULL);
  message.header.stamp.nanosec = static_cast<uint32_t>(scan.stamp_ns % 1000000000ULL);
  message.header.frame_id = configuration_.frame_id;
  message.angle_min = scan.angle_min;
  message.angle_max = scan.angle_max;
  message.angle_increment = scan.angle_increment;
  message.scan_time = scan.scan_time;
  message.time_increment = scan.time_increment;
  message.range_min = scan.range_min;
  message.range_max = scan.range_max;

  const auto count = static_cast<int>(
      (scan.angle_max - scan.angle_min) / scan.angle_increment) + 1;
  const auto invalid_range = configuration_.invalid_range_is_inf
      ? std::numeric_limits<float>::infinity() : 0.0F;
  message.ranges.resize(count, invalid_range);
  message.intensities.resize(count, 0.0F);
  for (const auto &point : scan.points) {
    const auto index = static_cast<int>(
        std::ceil((point.angle - scan.angle_min) / scan.angle_increment));
    if (index >= 0 && index < count && point.range >= scan.range_min) {
      message.ranges[index] = point.range;
      message.intensities[index] = point.intensity;
    }
  }
  scan_publisher_->publish(message);
}
