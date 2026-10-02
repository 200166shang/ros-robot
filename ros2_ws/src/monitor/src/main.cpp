#include <cstdlib>
#include <memory>
#include <string>
#include <vector>

#include "monitor/cpu_load_monitor.h"
#include "monitor/cpu_softirq_monitor.h"
#include "monitor/cpu_stat_monitor.h"
#include "monitor/mem_monitor.h"
#include "monitor/monitor_bag_writer.h"
#include "monitor/net_monitor.h"
#include "monitor/process_monitor.h"
#include "monitor/ros2_types.hpp"
#include "monitor_interfaces/srv/register_node.hpp"
#include "monitor_interfaces/srv/unregister_node.hpp"
#include "rclcpp/rclcpp.hpp"

class MonitorNode final : public rclcpp::Node {
public:
    MonitorNode() : Node("monitor_node"), process_monitor_() {
        register_service_ = create_service<monitor_interfaces::srv::RegisterNode>(
            "/monitor/register_node",
            [this](std::shared_ptr<monitor_interfaces::srv::RegisterNode::Request> request,
                   std::shared_ptr<monitor_interfaces::srv::RegisterNode::Response> response) {
                Register(request, response);
            });
        unregister_service_ = create_service<monitor_interfaces::srv::UnregisterNode>(
            "/monitor/unregister_node",
            [this](std::shared_ptr<monitor_interfaces::srv::UnregisterNode::Request> request,
                   std::shared_ptr<monitor_interfaces::srv::UnregisterNode::Response> response) {
                Unregister(request, response);
            });

        monitor_topic_ = declare_parameter<std::string>("monitor_topic", "/monitor_info");
        bag_file_path_ = declare_parameter<std::string>("bag_file_path", "monitor_data.bag");

        const auto qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable().durability_volatile();
        monitor_pub_ = create_publisher<monitor_interfaces::msg::MonitorInfo>(monitor_topic_, qos);
        bag_writer_.reset(new monitor::MonitorBagWriter(bag_file_path_, monitor_topic_));
        runners_.emplace_back(std::make_shared<monitor::CpuSoftIrqMonitor>());
        runners_.emplace_back(std::make_shared<monitor::CpuLoadMonitor>());
        runners_.emplace_back(std::make_shared<monitor::CpuStatMonitor>());
        runners_.emplace_back(std::make_shared<monitor::MemMonitor>());
        runners_.emplace_back(std::make_shared<monitor::NetMonitor>());

        // 保持 ROS 1 的三秒采样周期。
        sample_timer_ = create_wall_timer(std::chrono::seconds(3), [this]() { Sample(); });
        RCLCPP_INFO(get_logger(),
                    "monitor ready; services: /monitor/register_node, "
                    "/monitor/unregister_node");
    }

private:
    void Register(const std::shared_ptr<monitor_interfaces::srv::RegisterNode::Request> request,
                  std::shared_ptr<monitor_interfaces::srv::RegisterNode::Response> response) {
        std::string message;
        response->success = process_monitor_.RegisterNode(request->node_name,
                                                          request->process_name,
                                                          request->pid,
                                                          request->process_starttime_ticks,
                                                          request->registration_id,
                                                          &message);
        response->message = message;

        if (response->success && message == "Node registered") {
            RCLCPP_INFO(
                get_logger(), "REGISTER name=%s pid=%d", request->node_name.c_str(), request->pid);
        } else if (response->success) {
            RCLCPP_DEBUG(get_logger(), "REFRESH name=%s", request->node_name.c_str());
        } else {
            RCLCPP_WARN(get_logger(),
                        "REGISTRATION_REJECTED name=%s: %s",
                        request->node_name.c_str(),
                        message.c_str());
        }
    }

    void Unregister(const std::shared_ptr<monitor_interfaces::srv::UnregisterNode::Request> request,
                    std::shared_ptr<monitor_interfaces::srv::UnregisterNode::Response> response) {
        std::string message;
        response->success = process_monitor_.UnregisterNode(request->node_name,
                                                            request->pid,
                                                            request->process_starttime_ticks,
                                                            request->registration_id,
                                                            &message);
        response->message = message;

        if (response->success) {
            RCLCPP_INFO(get_logger(),
                        "UNREGISTER name=%s pid=%d: %s",
                        request->node_name.c_str(),
                        request->pid,
                        message.c_str());
        } else {
            RCLCPP_WARN(get_logger(),
                        "UNREGISTER_REJECTED name=%s: %s",
                        request->node_name.c_str(),
                        message.c_str());
        }
    }

    void Sample() {
        process_monitor_.UpdateAll();
        for (const auto &event : process_monitor_.TakeCleanupEvents())
            RCLCPP_WARN(get_logger(), "%s", event.c_str());

        monitor_interfaces::msg::MonitorInfo message;
        message.header.stamp    = now();
        message.header.frame_id = "monitor";
        const char *user        = std::getenv("USER");
        message.name            = user ? user : "unknown";
        // 各采集器用前后两次读数计算速率；首次采样只建立基线。
        for (auto &runner : runners_) {
            runner->UpdateOnce(&message);
        }

        process_monitor_.GetAllNodeInfo(message.node_monitors);

        // 发布与 bag 使用同一采样时间戳，便于回放时和其他话题对齐。
        const auto timestamp_ns = rclcpp::Time(message.header.stamp).nanoseconds();

        // 保留旧行为：仅有订阅者时发布，但每轮采样都写入 rosbag。
        if (monitor_pub_->get_subscription_count() > 0) {
            monitor_pub_->publish(message);
        }

        try {
            bag_writer_->Write(message, timestamp_ns);
        } catch (const std::exception &error) {
            RCLCPP_ERROR(get_logger(), "failed to write monitor sample to bag: %s", error.what());
        }
    }

    monitor::ProcessMonitor process_monitor_;
    std::string monitor_topic_;
    std::string bag_file_path_;
    std::unique_ptr<monitor::MonitorBagWriter> bag_writer_;
    rclcpp::Service<monitor_interfaces::srv::RegisterNode>::SharedPtr register_service_;
    rclcpp::Service<monitor_interfaces::srv::UnregisterNode>::SharedPtr unregister_service_;
    rclcpp::Publisher<monitor_interfaces::msg::MonitorInfo>::SharedPtr monitor_pub_;
    rclcpp::TimerBase::SharedPtr sample_timer_;
    std::vector<std::shared_ptr<monitor::MonitorInter>> runners_;
};

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    try {
        rclcpp::spin(std::make_shared<MonitorNode>());
    } catch (const std::exception &error) {
        RCLCPP_FATAL(rclcpp::get_logger("monitor_node"), "%s", error.what());
        rclcpp::shutdown();
        return 1;
    }
    rclcpp::shutdown();
    return 0;
}
