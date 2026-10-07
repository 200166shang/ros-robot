#include <cmath>
#include <cstdint>
#include <chrono>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_srvs/srv/empty.hpp"
#include "src/CYdLidar.h"

class YdLidarNode : public rclcpp::Node {
public:
  YdLidarNode() : Node("ydlidar") {
    scan_publisher_ = create_publisher<sensor_msgs::msg::LaserScan>("scan", 1);
    stop_scan_service_ = create_service<std_srvs::srv::Empty>(
        "stop_scan", [this](
                         std::shared_ptr<std_srvs::srv::Empty::Request>,
                         std::shared_ptr<std_srvs::srv::Empty::Response>) {
          RCLCPP_INFO(get_logger(), "Stop scan requested");
          auto_start_pending_ = false;
          if (scanning_ && !laser_.turnOff()) {
            RCLCPP_ERROR(get_logger(), "Failed to stop scan: %s",
                         laser_.DescribeError());
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
            scanning_ = laser_.turnOn();
            if (!scanning_) {
              RCLCPP_ERROR(get_logger(), "Failed to start scan: %s",
                           laser_.DescribeError());
            }
          }
        });

    configure_lidar();
    if (!laser_.initialize()) {
      RCLCPP_FATAL(get_logger(), "YDLIDAR initialization failed: %s",
                   laser_.DescribeError());
    } else {
      initialized_ = true;
      scanning_ = laser_.turnOn();
      if (!scanning_) {
        RCLCPP_WARN(get_logger(), "Could not start scan yet: %s",
                    laser_.DescribeError());
      }
    }

    scan_timer_ = create_wall_timer(
        std::chrono::milliseconds(33), std::bind(&YdLidarNode::publish_scan, this));
  }

  ~YdLidarNode() override {
    if (scanning_) {
      laser_.turnOff();
      scanning_ = false;
    }
    if (initialized_) {
      laser_.disconnecting();
      initialized_ = false;
    }
  }

private:
  template<typename T>
  T declare_value(const std::string &name, const T &default_value) {
    return declare_parameter<T>(name, default_value);
  }

  void configure_lidar() {
    const auto driver_type = declare_value<std::string>("lidar_driver_type", "ydlidar");
    if (driver_type != "ydlidar") {
      throw std::runtime_error("Only lidar_driver_type=ydlidar is supported");
    }

    auto port = declare_value<std::string>(
        "port", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0");
    laser_.setlidaropt(LidarPropSerialPort, port.c_str(), port.size());
    int int_value = declare_value<int>("baudrate", 115200);
    laser_.setlidaropt(LidarPropSerialBaudrate, &int_value, sizeof(int));

    const auto ignore_array = declare_value<std::string>("ignore_array", "");
    laser_.setlidaropt(LidarPropIgnoreArray, ignore_array.c_str(), ignore_array.size());

    int_value = declare_value<int>("lidar_type", TYPE_TRIANGLE);
    laser_.setlidaropt(LidarPropLidarType, &int_value, sizeof(int));
    int_value = declare_value<int>("device_type", YDLIDAR_TYPE_SERIAL);
    laser_.setlidaropt(LidarPropDeviceType, &int_value, sizeof(int));
    int_value = declare_value<int>("sample_rate", 3);
    laser_.setlidaropt(LidarPropSampleRate, &int_value, sizeof(int));
    int_value = declare_value<int>("abnormal_check_count", 4);
    laser_.setlidaropt(LidarPropAbnormalCheckCount, &int_value, sizeof(int));

    bool bool_value = declare_value<bool>("fixed_resolution", true);
    laser_.setlidaropt(LidarPropFixedResolution, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("reversion", false);
    laser_.setlidaropt(LidarPropReversion, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("inverted", true);
    laser_.setlidaropt(LidarPropInverted, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("auto_reconnect", true);
    laser_.setlidaropt(LidarPropAutoReconnect, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("isSingleChannel", true);
    laser_.setlidaropt(LidarPropSingleChannel, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("intensity", false);
    laser_.setlidaropt(LidarPropIntenstiy, &bool_value, sizeof(bool));
    bool_value = declare_value<bool>("support_motor_dtr", true);
    laser_.setlidaropt(LidarPropSupportMotorDtrCtrl, &bool_value, sizeof(bool));

    float float_value = declare_value<double>("angle_max", 180.0);
    laser_.setlidaropt(LidarPropMaxAngle, &float_value, sizeof(float));
    float_value = declare_value<double>("angle_min", 0.0);
    laser_.setlidaropt(LidarPropMinAngle, &float_value, sizeof(float));
    float_value = declare_value<double>("range_max", 10.0);
    laser_.setlidaropt(LidarPropMaxRange, &float_value, sizeof(float));
    float_value = declare_value<double>("range_min", 0.1);
    laser_.setlidaropt(LidarPropMinRange, &float_value, sizeof(float));
    float_value = declare_value<double>("frequency", 10.0);
    laser_.setlidaropt(LidarPropScanFrequency, &float_value, sizeof(float));

    frame_id_ = declare_value<std::string>("frame_id", "laser_link");
    invalid_range_is_inf_ = declare_value<bool>("invalid_range_is_inf", false);
  }

  void publish_scan() {
    if (!initialized_) {
      return;
    }
    if (!scanning_) {
      if (auto_start_pending_) {
        scanning_ = laser_.turnOn();
        if (!scanning_) {
          RCLCPP_WARN_THROTTLE(
              get_logger(), *get_clock(), 5000, "Could not start scan: %s",
              laser_.DescribeError());
        }
      }
      return;
    }

    LaserScan scan;
    if (laser_.doProcessSimple(scan) && scan.config.angle_increment > 0.0f) {
      sensor_msgs::msg::LaserScan message;
      message.header.stamp = rclcpp::Time(
          static_cast<int64_t>(scan.stamp), RCL_ROS_TIME).to_msg();
      message.header.frame_id = frame_id_;
      message.angle_min = scan.config.min_angle;
      message.angle_max = scan.config.max_angle;
      message.angle_increment = scan.config.angle_increment;
      message.scan_time = scan.config.scan_time;
      message.time_increment = scan.config.time_increment;
      message.range_min = scan.config.min_range;
      message.range_max = scan.config.max_range;

      const auto count = static_cast<int>(
          (scan.config.max_angle - scan.config.min_angle) /
          scan.config.angle_increment) + 1;
      const auto invalid_range = invalid_range_is_inf_
          ? std::numeric_limits<float>::infinity() : 0.0f;
      message.ranges.resize(count, invalid_range);
      message.intensities.resize(count, 0.0f);
      for (const auto &point : scan.points) {
        const auto index = static_cast<int>(std::ceil(
            (point.angle - scan.config.min_angle) / scan.config.angle_increment));
        if (index >= 0 && index < count && point.range >= scan.config.min_range) {
          message.ranges[index] = point.range;
          message.intensities[index] = point.intensity;
        }
      }
      scan_publisher_->publish(message);
    }
  }

  CYdLidar laser_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr scan_publisher_;
  rclcpp::Service<std_srvs::srv::Empty>::SharedPtr start_scan_service_;
  rclcpp::Service<std_srvs::srv::Empty>::SharedPtr stop_scan_service_;
  rclcpp::TimerBase::SharedPtr scan_timer_;
  std::string frame_id_;
  bool invalid_range_is_inf_{false};
  bool initialized_{false};
  bool scanning_{false};
  bool auto_start_pending_{true};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<YdLidarNode>();
    rclcpp::spin(node);
  } catch (const std::exception &error) {
    RCLCPP_FATAL(rclcpp::get_logger("ydlidar"), "YDLIDAR driver failed: %s", error.what());
  }
  rclcpp::shutdown();
  return 0;
}
