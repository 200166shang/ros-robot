#include <unistd.h>

#include <chrono>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <thread>

#include "monitor_client/monitor_registration.hpp"
#include "monitor_interfaces/msg/monitor_info.hpp"

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);

    // 两个业务节点放在同一个进程中，用来验证同 PID 下的注册身份能否独立管理。
    auto first_node  = std::make_shared<rclcpp::Node>("shared_process_one");
    auto second_node = std::make_shared<rclcpp::Node>("shared_process_two");

    // 订阅 monitor 汇总消息，记录节点名及每条记录上报的 PID。
    auto observer = std::make_shared<rclcpp::Node>("multi_node_observer");
    std::map<std::string, int32_t> active;
    auto subscription = observer->create_subscription<monitor_interfaces::msg::MonitorInfo>(
        "/monitor_info",
        10,
        [&active](const monitor_interfaces::msg::MonitorInfo::SharedPtr message) {
            active.clear();
            for (const auto &entry : message->node_monitors) {
                active[entry.node_name] = entry.pid;
            }
        });

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(observer);

    // MonitorRegistration 会在后台登记并续租；close() 请求注销。
    monitor_client::MonitorRegistration first(first_node);
    monitor_client::MonitorRegistration second(second_node);

    const int32_t expected_pid             = static_cast<int32_t>(::getpid());
    bool ok                                = false;
    bool reported_pids_match               = false;
    bool first_removed_while_second_active = false;

    // 等待两条节点记录都出现在 monitor 的采样消息中，最多等待 8 秒。
    const auto registration_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (std::chrono::steady_clock::now() < registration_deadline &&
           !(active.count("/shared_process_one") && active.count("/shared_process_two"))) {
        executor.spin_some();
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }

    const bool both_nodes_reported =
        active.count("/shared_process_one") && active.count("/shared_process_two");
    reported_pids_match = both_nodes_reported && active.at("/shared_process_one") == expected_pid &&
                          active.at("/shared_process_two") == expected_pid;
    ok = reported_pids_match;
    if (ok) {
        // 只注销第一个节点；第二个仍存在，证明注销按注册身份区分而非按 PID 清理。
        first.close();
        first_node.reset();

        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
        while (std::chrono::steady_clock::now() < deadline &&
               (active.count("/shared_process_one") || !active.count("/shared_process_two"))) {
            executor.spin_some();
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        }
        first_removed_while_second_active =
            !active.count("/shared_process_one") && active.count("/shared_process_two");
        ok = first_removed_while_second_active;
    }

    if (ok) {
        // 再注销第二个节点，并确认汇总消息中两条记录都已消失。
        second.close();
        second_node.reset();

        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < deadline &&
               (active.count("/shared_process_one") || active.count("/shared_process_two"))) {
            executor.spin_some();
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        }
        ok = !active.count("/shared_process_one") && !active.count("/shared_process_two");
    }

    // PASS 表示注册、同进程独立注销和最终清空三项检查均通过。
    std::cout << "multi_node_same_pid=" << expected_pid
              << " reported_pids_match=" << reported_pids_match
              << " first_removed_while_second_active=" << first_removed_while_second_active
              << " first_and_second_independently_unregistered="
              << (!active.count("/shared_process_one") && !active.count("/shared_process_two"))
              << " result=" << (ok ? "PASS" : "FAIL") << std::endl;

    executor.remove_node(observer);
    observer.reset();
    rclcpp::shutdown();
    return ok ? 0 : 1;
}
