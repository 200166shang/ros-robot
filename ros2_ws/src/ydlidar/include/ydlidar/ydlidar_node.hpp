#pragma once

#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_srvs/srv/empty.hpp"
#include "ydlidar/lidar_source.hpp"

class YdLidarNode : public rclcpp::Node {
 public:
  explicit YdLidarNode(std::unique_ptr<ydlidar::LidarSource> source);
  ~YdLidarNode() override;

 private:
  void publish_scan();

  std::unique_ptr<ydlidar::LidarSource> source_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr scan_publisher_;
  rclcpp::Service<std_srvs::srv::Empty>::SharedPtr start_scan_service_;
  rclcpp::Service<std_srvs::srv::Empty>::SharedPtr stop_scan_service_;
  rclcpp::TimerBase::SharedPtr scan_timer_;
  ydlidar::Configuration configuration_;
  bool initialized_{false};
  bool scanning_{false};
  bool auto_start_pending_{true};
};
