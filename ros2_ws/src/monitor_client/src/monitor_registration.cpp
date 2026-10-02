#include "monitor_client/monitor_registration.hpp"

#include <unistd.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "monitor_interfaces/srv/register_node.hpp"
#include "monitor_interfaces/srv/unregister_node.hpp"

namespace monitor_client {
namespace {
constexpr auto kServicePollInterval         = std::chrono::milliseconds(50);
constexpr auto kResponsePollInterval        = std::chrono::milliseconds(25);
constexpr auto kRegistrationResponseTimeout = std::chrono::milliseconds(500);
constexpr auto kRenewalInterval             = std::chrono::seconds(2);
constexpr auto kCloseTimeout                = std::chrono::seconds(1);

struct RegistrationIdentity {
    int32_t pid{0};
    uint64_t process_starttime_ticks{0};
    std::string node_name;
    std::string process_name;
    std::string registration_id;
};

std::vector<std::string> Split(const std::string &line) {
    std::istringstream input(line);
    std::vector<std::string> fields;
    std::string field;

    while (input >> field) {
        fields.push_back(field);
    }

    return fields;
}

bool ReadProcessIdentity(uint64_t &start_time_ticks, std::string &process_name) {
    std::ifstream comm_file("/proc/self/comm");
    std::getline(comm_file, process_name);

    std::ifstream stat_file("/proc/self/stat");
    std::string line;
    if (!stat_file || !std::getline(stat_file, line)) {
        return false;
    }

    const auto right_parenthesis = line.rfind(')');
    if (right_parenthesis == std::string::npos || right_parenthesis + 1 >= line.size()) {
        return false;
    }

    // starttime 与 PID 一起确认进程身份；从最后一个右括号后解析，兼容 comm 中的空格和括号。
    const auto fields = Split(line.substr(right_parenthesis + 1));
    if (fields.size() <= 19) {
        return false;
    }

    try {
        start_time_ticks = std::stoull(fields[19]);
    } catch (...) {
        return false;
    }

    return start_time_ticks > 0;
}

std::string CreateRegistrationId() {
    // 每次登记使用独立 ID，避免同进程中的不同 ROS 节点互相注销。
    std::random_device random;
    std::ostringstream output;

    for (int index = 0; index < 16; ++index) {
        if (index == 4 || index == 6 || index == 8 || index == 10) {
            output << '-';
        }

        output << std::hex << std::setw(2) << std::setfill('0') << (random() & 0xff);
    }

    return output.str();
}

RegistrationIdentity CaptureIdentity(const rclcpp::Node::SharedPtr &owner) {
    RegistrationIdentity identity;
    identity.pid             = static_cast<int32_t>(::getpid());
    identity.node_name       = owner->get_fully_qualified_name();
    identity.registration_id = CreateRegistrationId();

    if (!ReadProcessIdentity(identity.process_starttime_ticks, identity.process_name)) {
        throw std::runtime_error("cannot read own /proc identity");
    }

    return identity;
}

}  // namespace

class MonitorRegistration::Impl {
public:
    explicit Impl(const rclcpp::Node::SharedPtr &owner);
    ~Impl();

    void Close();

private:
    void CreateClients();
    void RecreateRegisterClient();
    bool WaitForRegisterService();
    bool RegisterOnce();
    void Run();
    bool UnregisterOnce(std::chrono::steady_clock::time_point deadline);

    rclcpp::Node::SharedPtr owner_;
    RegistrationIdentity identity_;
    rclcpp::Node::SharedPtr helper_node_;
    rclcpp::Client<monitor_interfaces::srv::RegisterNode>::SharedPtr register_client_;
    rclcpp::Client<monitor_interfaces::srv::UnregisterNode>::SharedPtr unregister_client_;
    rclcpp::executors::SingleThreadedExecutor helper_executor_;
    std::thread executor_thread_;
    std::thread worker_thread_;
    std::mutex mutex_;
    std::condition_variable wake_;
    std::atomic<bool> stopping_{false};
    std::atomic<bool> closed_{false};
    // steady_clock 绝对期限跨线程传递，保证注销等待与 Close() 共用一个截止点。
    std::atomic<int64_t> close_deadline_ns_{0};
    int client_recreations_{0};
};

MonitorRegistration::Impl::Impl(const rclcpp::Node::SharedPtr &owner)
    : owner_(owner), identity_(CaptureIdentity(owner)) {
    // 独立辅助节点和 executor 让注册响应不依赖业务节点使用的 executor。
    auto options = rclcpp::NodeOptions().use_global_arguments(false).context(
        owner_->get_node_base_interface()->get_context());
    helper_node_ =
        std::make_shared<rclcpp::Node>("_monitor_client_" + identity_.registration_id.substr(0, 8),
                                       owner_->get_namespace(),
                                       options);

    CreateClients();

    helper_executor_.add_node(helper_node_);
    executor_thread_ = std::thread([this]() { helper_executor_.spin(); });
    worker_thread_   = std::thread([this]() { Run(); });
}

MonitorRegistration::Impl::~Impl() { Close(); }

void MonitorRegistration::Impl::CreateClients() {
    register_client_ = helper_node_->create_client<monitor_interfaces::srv::RegisterNode>(
        "/monitor/register_node");
    unregister_client_ = helper_node_->create_client<monitor_interfaces::srv::UnregisterNode>(
        "/monitor/unregister_node");
    ++client_recreations_;
}

void MonitorRegistration::Impl::RecreateRegisterClient() {
    register_client_.reset();
    register_client_ = helper_node_->create_client<monitor_interfaces::srv::RegisterNode>(
        "/monitor/register_node");
    ++client_recreations_;
}

bool MonitorRegistration::Impl::WaitForRegisterService() {
    // 服务尚未启动时持续等待；关闭请求可以打断等待。
    while (!stopping_.load()) {
        if (register_client_->service_is_ready()) {
            return true;
        }

        std::this_thread::sleep_for(kServicePollInterval);
        if (stopping_.load()) {
            return false;
        }
    }

    return false;
}

bool MonitorRegistration::Impl::RegisterOnce() {
    // 注册和续租复用同一身份；服务端据此创建记录或刷新租期。
    auto request          = std::make_shared<monitor_interfaces::srv::RegisterNode::Request>();
    request->node_name    = identity_.node_name;
    request->process_name = identity_.process_name;
    request->pid          = identity_.pid;
    request->process_starttime_ticks = identity_.process_starttime_ticks;
    request->registration_id         = identity_.registration_id;

    auto future         = register_client_->async_send_request(request);
    const auto deadline = std::chrono::steady_clock::now() + kRegistrationResponseTimeout;

    while (std::chrono::steady_clock::now() < deadline && !stopping_.load()) {
        if (future.wait_for(kResponsePollInterval) == std::future_status::ready) {
            try {
                auto response = future.get();
                if (!response->success) {
                    RCLCPP_WARN_THROTTLE(owner_->get_logger(),
                                         *owner_->get_clock(),
                                         5000,
                                         "monitor registration rejected: %s",
                                         response->message.c_str());
                }
                return response->success;
            } catch (const std::exception &error) {
                RCLCPP_WARN(owner_->get_logger(), "monitor registration failed: %s", error.what());
                return false;
            }
        }
    }

    // Foxy 无法移除超时请求，重建 client 可避免 pending future 持续累积。
    RecreateRegisterClient();
    return false;
}

void MonitorRegistration::Impl::Run() {
    // worker 独占续租流程；停止后先尝试注销，再由 Close() 停止响应 executor。
    while (!stopping_.load()) {
        if (WaitForRegisterService() && !stopping_.load()) {
            RegisterOnce();
        }

        // 超时2秒就跳出wait_for阻塞，继续执行while循环，从而达到2秒续租的能力
        std::unique_lock<std::mutex> lock(mutex_);
        wake_.wait_for(lock, kRenewalInterval, [this]() { return stopping_.load(); });
    }

    // Close会保存当前关闭时间，从而提醒Run这里注销，因此注册和注销都在这一个work_thread里
    const auto deadline_ns = close_deadline_ns_.load();
    if (deadline_ns > 0) {
        const auto deadline =
            std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline_ns));
        UnregisterOnce(deadline);
    }
}

bool MonitorRegistration::Impl::UnregisterOnce(std::chrono::steady_clock::time_point deadline) {
    // 服务等待和响应等待共用 Close() 给出的绝对期限。
    while (std::chrono::steady_clock::now() < deadline) {
        if (unregister_client_->service_is_ready()) {
            break;
        }

        std::this_thread::sleep_for(kResponsePollInterval);
    }
    if (!unregister_client_->service_is_ready()) {
        return false;
    }

    auto request       = std::make_shared<monitor_interfaces::srv::UnregisterNode::Request>();
    request->node_name = identity_.node_name;
    request->pid       = identity_.pid;
    request->process_starttime_ticks = identity_.process_starttime_ticks;
    request->registration_id         = identity_.registration_id;

    auto future = unregister_client_->async_send_request(request);
    while (std::chrono::steady_clock::now() < deadline) {
        if (future.wait_for(kResponsePollInterval) == std::future_status::ready) {
            try {
                auto response = future.get();
                if (response->success) {
                    RCLCPP_INFO(owner_->get_logger(),
                                "monitor registration closed: %s",
                                response->message.c_str());
                } else {
                    RCLCPP_WARN(owner_->get_logger(),
                                "monitor unregister failed: %s",
                                response->message.c_str());
                }
                return response->success;
            } catch (...) {
                return false;
            }
        }
    }

    RCLCPP_WARN(owner_->get_logger(), "monitor unregister timed out");
    return false;
}

void MonitorRegistration::Impl::Close() {
    bool expected = false;
    if (!closed_.compare_exchange_strong(expected, true)) {
        return;
    }

    const auto deadline = std::chrono::steady_clock::now() + kCloseTimeout;
    close_deadline_ns_.store(
        std::chrono::duration_cast<std::chrono::nanoseconds>(deadline.time_since_epoch()).count());

    stopping_.store(true);
    wake_.notify_all();
    if (worker_thread_.joinable()) {
        worker_thread_.join();
    }

    // 注销请求完成或到期后，才停止处理异步响应的 executor。
    helper_executor_.cancel();
    if (executor_thread_.joinable()) {
        executor_thread_.join();
    }

    if (helper_node_) {
        helper_executor_.remove_node(helper_node_);
    }

    if (owner_) {
        RCLCPP_INFO(owner_->get_logger(),
                    "monitor client closed; client_recreations=%d max_inflight=1",
                    client_recreations_);
    }

    register_client_.reset();
    unregister_client_.reset();
    helper_node_.reset();
    owner_.reset();
}

MonitorRegistration::MonitorRegistration(const rclcpp::Node::SharedPtr &owner)
    : impl_(new Impl(owner)) {}

MonitorRegistration::~MonitorRegistration() = default;

void MonitorRegistration::close() { impl_->Close(); }

}  // namespace monitor_client
