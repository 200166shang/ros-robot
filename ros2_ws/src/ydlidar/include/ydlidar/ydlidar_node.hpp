#pragma once

#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_srvs/srv/empty.hpp"
#include "ydlidar/lidar_source.hpp"

class YdLidarNode : public rclcpp::Node {
public:
    // 注入扫描数据源：生产入口传 SDK adapter，ROS 接口测试传模拟数据源。
    explicit YdLidarNode(std::unique_ptr<ydlidar::LidarSource> source);
    ~YdLidarNode() override;

private:
    // 定时读取一帧扫描，映射为 sensor_msgs/LaserScan 后发布到相对话题 scan。
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
