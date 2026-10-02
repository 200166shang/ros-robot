#include <gtest/gtest.h>
#include <unistd.h>

#include <chrono>
#include <cmath>
#include <thread>

#include "monitor/cpu_load_monitor.h"
#include "monitor/cpu_softirq_monitor.h"
#include "monitor/cpu_stat_monitor.h"
#include "monitor/mem_monitor.h"
#include "monitor/net_monitor.h"
#include "monitor/process_monitor.h"

TEST(ProcessMonitor, ParsesCommContainingSpacesAndParentheses) {
    const std::string line =
        "123 (camera worker (v2)) S 1 2 3 4 5 6 7 8 9 10 120 30 "
        "16 17 18 19 20 21 987654";
    monitor::ProcSnapshot snapshot;
    ASSERT_TRUE(monitor::ProcessMonitor::ParseProcStatLine(line, snapshot));
    EXPECT_EQ(snapshot.state, 'S');
    EXPECT_EQ(snapshot.cpu_time_ticks, 150U);
    EXPECT_EQ(snapshot.start_time_ticks, 987654U);
}

TEST(ProcessMonitor, RegistersRefreshesTerminatesAndProtectsNewInstance) {
    monitor::ProcSnapshot self;
    ASSERT_TRUE(monitor::ProcessMonitor::ReadProcSnapshot(getpid(), self));
    monitor::ProcessMonitor manager;
    std::string result;

    ASSERT_TRUE(
        manager.RegisterNode("/same", "test", getpid(), self.start_time_ticks, "old-id", &result));
    EXPECT_EQ(manager.RegisteredCount(), 1U);
    EXPECT_TRUE(
        manager.RegisterNode("/same", "test", getpid(), self.start_time_ticks, "old-id", &result));
    EXPECT_EQ(manager.RegisteredCount(), 1U);

    ASSERT_TRUE(
        manager.UnregisterNode("/same", getpid(), self.start_time_ticks, "old-id", &result));
    EXPECT_EQ(manager.RegisteredCount(), 0U);

    EXPECT_FALSE(
        manager.RegisterNode("/same", "test", getpid(), self.start_time_ticks, "old-id", &result));

    ASSERT_TRUE(
        manager.RegisterNode("/same", "test", getpid(), self.start_time_ticks, "new-id", &result));
    EXPECT_TRUE(
        manager.UnregisterNode("/same", getpid(), self.start_time_ticks, "old-id", &result));
    EXPECT_TRUE(manager.IsRegistered("/same"));
    std::vector<monitor::NodeMonitorInfo> infos;
    manager.GetAllNodeInfo(infos);
    ASSERT_EQ(infos.size(), 1U);
    EXPECT_EQ(infos[0].pid, getpid());
    EXPECT_TRUE(
        manager.UnregisterNode("/same", getpid(), self.start_time_ticks, "new-id", &result));
}

TEST(ProcessMonitor, RejectsIncorrectProcessIdentity) {
    monitor::ProcessMonitor manager;
    std::string result;
    EXPECT_FALSE(manager.RegisterNode("/wrong-start", "test", getpid(), 1, "id", &result));
    EXPECT_EQ(manager.RegisteredCount(), 0U);
}

TEST(ProcessMonitor, RejectsReusedPidWithStaleStarttime) {
    monitor::ProcSnapshot current;
    ASSERT_TRUE(monitor::ProcessMonitor::ReadProcSnapshot(getpid(), current));
    ASSERT_GT(current.start_time_ticks, 1U);
    monitor::ProcessMonitor manager;
    std::string result;
    const auto stale_start = current.start_time_ticks - 1;
    EXPECT_FALSE(manager.RegisterNode(
        "/reused-pid", "old-process", getpid(), stale_start, "old-instance", &result));
    ASSERT_TRUE(manager.RegisterNode(
        "/reused-pid", "new-process", getpid(), current.start_time_ticks, "new-instance", &result));
    EXPECT_FALSE(
        manager.UnregisterNode("/reused-pid", getpid(), stale_start, "old-instance", &result));
    EXPECT_TRUE(manager.IsRegistered("/reused-pid"));
    EXPECT_EQ(manager.RegisteredCount(), 1U);
}

TEST(ProcessMonitor, RemovesExpiredLease) {
    monitor::ProcessMonitor manager(std::chrono::seconds(1));
    monitor::ProcSnapshot self;
    ASSERT_TRUE(monitor::ProcessMonitor::ReadProcSnapshot(getpid(), self));
    ASSERT_TRUE(
        manager.RegisterNode("/lease", "test", getpid(), self.start_time_ticks, "lease-id"));
    std::this_thread::sleep_for(std::chrono::milliseconds(1100));
    manager.UpdateAll();
    EXPECT_EQ(manager.RegisteredCount(), 0U);
}

TEST(MonitorSamplers, ReadCurrentProcFilesWithoutInvalidRates) {
    monitor::MonitorInfo first, second;
    monitor::CpuStatMonitor cpu;
    monitor::CpuSoftIrqMonitor softirq;
    monitor::CpuLoadMonitor load;
    monitor::MemMonitor memory;
    monitor::NetMonitor network;
    cpu.UpdateOnce(&first);
    softirq.UpdateOnce(&first);
    load.UpdateOnce(&first);
    memory.UpdateOnce(&first);
    network.UpdateOnce(&first);

    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    cpu.UpdateOnce(&second);
    softirq.UpdateOnce(&second);
    load.UpdateOnce(&second);
    memory.UpdateOnce(&second);
    network.UpdateOnce(&second);

    ASSERT_FALSE(second.cpu_stat.empty());
    ASSERT_FALSE(second.cpu_softirq.empty());
    EXPECT_EQ(second.cpu_stat.front().cpu_name, "cpu");
    EXPECT_FALSE(second.cpu_softirq.front().cpu_name.empty());
    EXPECT_GE(second.cpu_load.load_avg_5, 0.0F);
    EXPECT_GT(second.mem_info.total, 0.0F);
    EXPECT_TRUE(std::isfinite(second.mem_info.used_percent));
    for (const auto &entry : second.cpu_stat) {
        EXPECT_TRUE(std::isfinite(entry.cpu_percent));
        EXPECT_GE(entry.cpu_percent, 0.0F);
        EXPECT_LE(entry.cpu_percent, 100.0F);
    }
    for (const auto &entry : second.net_info) {
        EXPECT_TRUE(std::isfinite(entry.rcv_rate));
        EXPECT_TRUE(std::isfinite(entry.send_rate));
    }
}
