#pragma once

#include <memory>

#include "rclcpp/rclcpp.hpp"

namespace monitor_client {

// 为一个 ROS 节点登记并维护 monitor 租约；应在 ROS context 关闭前调用 close()。
class MonitorRegistration {
public:
    explicit MonitorRegistration(const rclcpp::Node::SharedPtr &owner);

    // 析构会调用 close()；对象必须在 ROS context 关闭前销毁。
    ~MonitorRegistration();

    MonitorRegistration(const MonitorRegistration &) = delete;
    MonitorRegistration &operator=(const MonitorRegistration &) = delete;

    // 幂等关闭：停止续租并尽力注销。
    void close();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace monitor_client
