#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <future>
#include <memory>
#include <mutex>
#include <thread>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_srvs/srv/empty.hpp"
#include "ydlidar/ydlidar_node.hpp"

namespace {

struct SourceStats {
    std::atomic<int> starts{0};
    std::atomic<int> stops{0};
    std::atomic<int> reads{0};
    std::atomic<int> disconnects{0};
};

class FakeLidarSource final : public ydlidar::LidarSource {
public:
    explicit FakeLidarSource(std::shared_ptr<SourceStats> stats) : stats_(std::move(stats)) {}

    bool initialize(const ydlidar::Configuration &configuration) override {
        configuration_ = configuration;
        return true;
    }
    bool start() override {
        ++stats_->starts;
        return true;
    }
    bool stop() override {
        ++stats_->stops;
        return true;
    }
    bool read(ydlidar::Scan &scan) override {
        ++stats_->reads;
        scan.stamp_ns        = 1234567890ULL;
        scan.angle_min       = 0.0F;
        scan.angle_max       = 0.3F;
        scan.angle_increment = 0.1F;
        scan.scan_time       = 0.2F;
        scan.time_increment  = 0.01F;
        scan.range_min       = 0.1F;
        scan.range_max       = 10.0F;
        scan.points          = {{0.1F, 2.5F, 7.0F}, {0.2F, 0.05F, 8.0F}};
        return true;
    }
    void disconnect() override { ++stats_->disconnects; }
    std::string error() const override { return "fake source"; }

private:
    std::shared_ptr<SourceStats> stats_;
    ydlidar::Configuration configuration_;
};

class YdLidarRosInterfaceTest : public ::testing::Test {
protected:
    static void SetUpTestCase() {
        int argc = 0;
        rclcpp::init(argc, nullptr);
    }
    static void TearDownTestCase() { rclcpp::shutdown(); }
};

class ExecutorThread {
public:
    explicit ExecutorThread(rclcpp::executors::SingleThreadedExecutor &executor)
        : executor_(executor), thread_([this]() { executor_.spin(); }) {}
    ~ExecutorThread() {
        executor_.cancel();
        if (thread_.joinable()) {
            thread_.join();
        }
    }

private:
    rclcpp::executors::SingleThreadedExecutor &executor_;
    std::thread thread_;
};

TEST_F(YdLidarRosInterfaceTest, PublishesScansAndHonorsStartStopServices) {
    auto stats    = std::make_shared<SourceStats>();
    auto node     = std::make_shared<YdLidarNode>(std::make_unique<FakeLidarSource>(stats));
    auto observer = std::make_shared<rclcpp::Node>("ydlidar_interface_observer");
    std::mutex message_mutex;
    std::condition_variable message_ready;
    sensor_msgs::msg::LaserScan::SharedPtr received_scan;
    auto subscription = observer->create_subscription<sensor_msgs::msg::LaserScan>(
        "scan", 10, [&](sensor_msgs::msg::LaserScan::SharedPtr message) {
            {
                std::lock_guard<std::mutex> lock(message_mutex);
                received_scan = std::move(message);
            }
            message_ready.notify_one();
        });
    auto start_client = observer->create_client<std_srvs::srv::Empty>("start_scan");
    auto stop_client  = observer->create_client<std_srvs::srv::Empty>("stop_scan");
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(node);
    executor.add_node(observer);
    ExecutorThread spin_thread(executor);

    ASSERT_TRUE(start_client->wait_for_service(std::chrono::seconds(4)));
    ASSERT_TRUE(stop_client->wait_for_service(std::chrono::seconds(4)));
    {
        std::unique_lock<std::mutex> lock(message_mutex);
        ASSERT_TRUE(message_ready.wait_for(lock, std::chrono::seconds(4), [&received_scan]() {
            return static_cast<bool>(received_scan);
        }));
    }
    {
        std::lock_guard<std::mutex> lock(message_mutex);
        ASSERT_EQ(received_scan->header.frame_id, "laser_link");
        EXPECT_EQ(received_scan->header.stamp.sec, 1);
        EXPECT_EQ(received_scan->header.stamp.nanosec, 234567890U);
        EXPECT_FLOAT_EQ(received_scan->angle_min, 0.0F);
        EXPECT_FLOAT_EQ(received_scan->angle_max, 0.3F);
        EXPECT_FLOAT_EQ(received_scan->angle_increment, 0.1F);
        EXPECT_FLOAT_EQ(received_scan->scan_time, 0.2F);
        EXPECT_FLOAT_EQ(received_scan->time_increment, 0.01F);
        EXPECT_FLOAT_EQ(received_scan->range_min, 0.1F);
        EXPECT_FLOAT_EQ(received_scan->range_max, 10.0F);
        ASSERT_EQ(received_scan->ranges.size(), 4U);
        EXPECT_FLOAT_EQ(received_scan->ranges[0], 0.0F);
        EXPECT_FLOAT_EQ(received_scan->ranges[1], 2.5F);
        EXPECT_FLOAT_EQ(received_scan->ranges[2], 0.0F);
        EXPECT_FLOAT_EQ(received_scan->intensities[1], 7.0F);
    }
    EXPECT_EQ(stats->starts.load(), 1);

    auto stop_future =
        stop_client->async_send_request(std::make_shared<std_srvs::srv::Empty::Request>());
    ASSERT_EQ(stop_future.wait_for(std::chrono::seconds(2)), std::future_status::ready);
    const auto reads_after_stop = stats->reads.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    EXPECT_EQ(stats->reads.load(), reads_after_stop);
    EXPECT_EQ(stats->stops.load(), 1);

    auto start_future =
        start_client->async_send_request(std::make_shared<std_srvs::srv::Empty::Request>());
    ASSERT_EQ(start_future.wait_for(std::chrono::seconds(2)), std::future_status::ready);
    EXPECT_EQ(stats->starts.load(), 2);

    executor.remove_node(node);
    executor.remove_node(observer);
    node.reset();
    EXPECT_EQ(stats->stops.load(), 2);
    EXPECT_EQ(stats->disconnects.load(), 1);
    (void)subscription;
}

}  // namespace
