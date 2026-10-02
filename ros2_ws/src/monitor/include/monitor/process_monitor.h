#pragma once
#include <chrono>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "monitor/ros2_types.hpp"

namespace monitor {
struct ProcSnapshot {
    uint64_t cpu_time_ticks{0};
    uint64_t start_time_ticks{0};
    char state{'?'};
};

struct ProcessInfo {
    int32_t pid{0};
    std::string process_name;
    std::string node_name;
    uint64_t start_time_ticks{0};
    std::string registration_id;
    std::chrono::steady_clock::time_point last_registration{};
    std::chrono::steady_clock::time_point last_update{};
    uint64_t last_cpu_time{0};
    float cpu_percent{0.0F};
    float cpu_time{0.0F};
    float mem_mb{0.0F};
    float mem_percent{0.0F};
    int32_t thread_count{0};
    uint64_t last_disk_read_bytes{0};
    uint64_t last_disk_write_bytes{0};
    uint64_t last_disk_read_ops{0};
    uint64_t last_disk_write_ops{0};
    float disk_read_rate{0.0F};
    float disk_write_rate{0.0F};
    uint64_t disk_read_bytes{0};
    uint64_t disk_write_bytes{0};
    uint64_t disk_read_ops{0};
    uint64_t disk_write_ops{0};
    bool cpu_baseline_valid{false};
    bool disk_baseline_valid{false};
};

class ProcessMonitor {
public:
    explicit ProcessMonitor(std::chrono::seconds lease = std::chrono::seconds(10),
                            size_t max_tombstones      = 4096);
    bool RegisterNode(const std::string &node_name,
                      const std::string &process_name,
                      int32_t pid,
                      uint64_t start_time_ticks,
                      const std::string &registration_id,
                      std::string *message = nullptr);
    bool UnregisterNode(const std::string &node_name,
                        int32_t pid,
                        uint64_t start_time_ticks,
                        const std::string &registration_id,
                        std::string *message = nullptr);
    void UpdateAll();
    void GetAllNodeInfo(std::vector<NodeMonitorInfo> &infos);
    bool IsRegistered(const std::string &node_name);
    size_t RegisteredCount();
    size_t TombstoneCount();
    std::vector<std::string> TakeCleanupEvents();

    static bool ReadProcSnapshot(int32_t pid, ProcSnapshot &snapshot);
    static bool ParseProcStatLine(const std::string &line, ProcSnapshot &snapshot);
    static uint64_t GetSystemTotalMemoryKb();

private:
    using Clock = std::chrono::steady_clock;
    static std::string IdentityKey(const std::string &node_name,
                                   int32_t pid,
                                   uint64_t start_time_ticks,
                                   const std::string &registration_id);
    bool IsLiveIdentity(int32_t pid, uint64_t start_time_ticks) const;
    void PruneLocked(Clock::time_point now);
    void UpdateProcessLocked(ProcessInfo &process, Clock::time_point now);
    bool ReadProcessMemory(int32_t pid,
                           float &mem_mb,
                           float &mem_percent,
                           int32_t &thread_count) const;
    bool ReadProcessDiskIO(int32_t pid,
                           uint64_t &read_bytes,
                           uint64_t &write_bytes,
                           uint64_t &read_ops,
                           uint64_t &write_ops) const;

    mutable std::mutex mutex_;
    std::unordered_map<std::string, ProcessInfo> registered_nodes_;
    std::unordered_set<std::string> terminated_identities_;
    std::vector<std::string> cleanup_events_;
    std::chrono::seconds lease_;
    size_t max_tombstones_;
    uint64_t system_total_memory_kb_;
};
}  // namespace monitor
