#include "monitor/process_monitor.h"

#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <climits>
#include <cmath>
#include <fstream>
#include <sstream>
#include <utility>
#include <vector>

namespace monitor {
namespace {
std::vector<std::string> Split(const std::string &value) {
    std::istringstream in(value);
    std::vector<std::string> fields;
    std::string field;
    while (in >> field) {
        fields.push_back(field);
    }
    return fields;
}
}  // namespace

ProcessMonitor::ProcessMonitor(std::chrono::seconds lease, size_t max_tombstones)
    : lease_(lease.count() > 0 ? lease : std::chrono::seconds(10)),
      max_tombstones_(max_tombstones),
      system_total_memory_kb_(GetSystemTotalMemoryKb()) {}

std::string ProcessMonitor::IdentityKey(const std::string &name,
                                        int32_t pid,
                                        uint64_t start,
                                        const std::string &id) {
    // 启动时间防 PID 复用，registration ID 区分同名节点的不同注册实例。
    std::ostringstream out;
    out << name << '\0' << pid << '\0' << start << '\0' << id;
    return out.str();
}

bool ProcessMonitor::ParseProcStatLine(const std::string &line, ProcSnapshot &snapshot) {
    const auto left  = line.find('(');
    const auto right = line.rfind(')');
    if (left == std::string::npos || right == std::string::npos || right <= left ||
        right + 1 >= line.size())
        return false;
    // comm 允许空格和括号；从最后一个右括号后按 proc(5) 固定字段解析。
    const auto fields = Split(line.substr(right + 1));
    if (fields.size() <= 19 || fields[0].size() != 1) return false;
    try {
        snapshot.state = fields[0][0];
        // 去掉 state 后 fields[11:13] 对应 utime/stime，fields[19] 对应 starttime。
        snapshot.cpu_time_ticks   = std::stoull(fields[11]) + std::stoull(fields[12]);
        snapshot.start_time_ticks = std::stoull(fields[19]);
    } catch (...) {
        return false;
    }
    return true;
}

bool ProcessMonitor::ReadProcSnapshot(int32_t pid, ProcSnapshot &snapshot) {
    if (pid <= 0) return false;
    std::ifstream input("/proc/" + std::to_string(pid) + "/stat");
    std::string line;
    return input && static_cast<bool>(std::getline(input, line)) &&
           ParseProcStatLine(line, snapshot);
}

bool ProcessMonitor::IsLiveIdentity(int32_t pid, uint64_t start) const {
    ProcSnapshot snapshot;
    return ReadProcSnapshot(pid, snapshot) && snapshot.state != 'Z' && snapshot.state != 'X' &&
           snapshot.start_time_ticks == start;
}

void ProcessMonitor::PruneLocked(Clock::time_point now) {
    for (auto it = registered_nodes_.begin(); it != registered_nodes_.end();) {
        const auto &record = it->second;
        if (!IsLiveIdentity(record.pid, record.start_time_ticks)) {
            cleanup_events_.push_back("PROCESS_EXIT name=" + record.node_name +
                                      " pid=" + std::to_string(record.pid));
            it = registered_nodes_.erase(it);
        } else if (now - record.last_registration > lease_) {
            cleanup_events_.push_back("LEASE_EXPIRED name=" + record.node_name +
                                      " pid=" + std::to_string(record.pid));
            it = registered_nodes_.erase(it);
        } else {
            ++it;
        }
    }
    for (auto it = terminated_identities_.begin(); it != terminated_identities_.end();) {
        // 注销后保留身份墓碑，防止迟到的续租请求复活旧注册；进程退出后再清理。
        const auto first  = it->find('\0');
        const auto second = first == std::string::npos ? first : it->find('\0', first + 1);
        const auto third  = second == std::string::npos ? second : it->find('\0', second + 1);
        bool live         = false;
        if (second != std::string::npos && third != std::string::npos) {
            try {
                const int32_t pid    = std::stoi(it->substr(first + 1, second - first - 1));
                const uint64_t start = std::stoull(it->substr(second + 1, third - second - 1));
                live                 = IsLiveIdentity(pid, start);
            } catch (...) {
            }
        }
        if (!live)
            it = terminated_identities_.erase(it);
        else
            ++it;
    }
}

bool ProcessMonitor::RegisterNode(const std::string &node_name,
                                  const std::string &process_name,
                                  int32_t pid,
                                  uint64_t start_time_ticks,
                                  const std::string &registration_id,
                                  std::string *message) {
    auto set_message = [message](const std::string &value) {
        if (message) *message = value;
    };
    if (node_name.empty() || registration_id.empty() || pid <= 0 || start_time_ticks == 0) {
        set_message("Invalid node identity");
        return false;
    }
    if (!IsLiveIdentity(pid, start_time_ticks)) {
        set_message("PID is not a live process with the supplied start time");
        return false;
    }

    const auto now      = Clock::now();
    const auto identity = IdentityKey(node_name, pid, start_time_ticks, registration_id);
    std::lock_guard<std::mutex> lock(mutex_);
    PruneLocked(now);
    if (terminated_identities_.count(identity)) {
        set_message("Registration identity has already been terminated");
        return false;
    }

    // 一个 ROS 节点名同一时刻只归一个注册身份所有，匹配身份的请求只续租。
    auto current = registered_nodes_.find(node_name);
    if (current != registered_nodes_.end()) {
        auto &old = current->second;
        if (old.pid == pid && old.start_time_ticks == start_time_ticks &&
            old.registration_id == registration_id) {
            old.last_registration = now;
            if (!process_name.empty()) old.process_name = process_name;
            set_message("Registration lease refreshed");
            return true;
        }
        set_message("Node name is owned by a different live registration");
        return false;
    }

    if (terminated_identities_.size() >= max_tombstones_) {
        set_message("Terminated identity table is full");
        return false;
    }

    ProcessInfo record;
    record.pid               = pid;
    record.node_name         = node_name;
    record.process_name      = process_name.empty() ? node_name : process_name;
    record.start_time_ticks  = start_time_ticks;
    record.registration_id   = registration_id;
    record.last_registration = now;
    record.last_update       = now;
    registered_nodes_.emplace(node_name, std::move(record));
    set_message("Node registered");
    return true;
}

bool ProcessMonitor::UnregisterNode(const std::string &node_name,
                                    int32_t pid,
                                    uint64_t start_time_ticks,
                                    const std::string &registration_id,
                                    std::string *message) {
    auto set_message = [message](const std::string &value) {
        if (message) *message = value;
    };
    if (node_name.empty() || registration_id.empty() || pid <= 0 || start_time_ticks == 0) {
        set_message("Invalid node identity");
        return false;
    }

    const auto identity = IdentityKey(node_name, pid, start_time_ticks, registration_id);
    const auto now      = Clock::now();
    std::lock_guard<std::mutex> lock(mutex_);
    PruneLocked(now);
    if (terminated_identities_.count(identity)) {
        set_message("Registration was already terminated");
        return true;
    }
    if (!IsLiveIdentity(pid, start_time_ticks)) {
        set_message("Process identity is no longer live");
        return false;
    }
    if (terminated_identities_.size() >= max_tombstones_) {
        set_message("Terminated identity table is full");
        return false;
    }
    // 先记录注销身份，避免网络延迟导致旧客户端再次注册成功。
    terminated_identities_.insert(identity);
    auto current = registered_nodes_.find(node_name);
    if (current != registered_nodes_.end() && current->second.pid == pid &&
        current->second.start_time_ticks == start_time_ticks &&
        current->second.registration_id == registration_id) {
        registered_nodes_.erase(current);
        set_message("Node unregistered");
        return true;
    }
    set_message("Registration was already absent; stale identity tombstoned");
    return true;
}

bool ProcessMonitor::ReadProcessMemory(int32_t pid,
                                       float &mem_mb,
                                       float &mem_percent,
                                       int32_t &thread_count) const {
    // VmRSS 和 MemTotal 都以 KiB 读取，输出分别换算为 MiB 和系统内存百分比。
    std::ifstream input("/proc/" + std::to_string(pid) + "/status");
    if (!input) return false;

    uint64_t rss_kb   = 0;
    bool have_rss     = false;
    bool have_threads = false;
    int threads       = 0;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream fields(line);
        std::string key, value, unit;
        if (!(fields >> key >> value)) continue;
        try {
            if (key == "VmRSS:") {
                rss_kb   = std::stoull(value);
                have_rss = true;
            } else if (key == "Threads:") {
                threads      = std::stoi(value);
                have_threads = true;
            }
        } catch (...) {
            return false;
        }
        if (have_rss && have_threads) break;
    }

    if (!have_rss || system_total_memory_kb_ == 0) return false;

    mem_mb      = static_cast<float>(rss_kb) / 1024.0F;
    mem_percent = static_cast<float>(100.0 * static_cast<double>(rss_kb) /
                                     static_cast<double>(system_total_memory_kb_));
    if (have_threads) thread_count = threads;
    return std::isfinite(mem_mb) && std::isfinite(mem_percent);
}

bool ProcessMonitor::ReadProcessDiskIO(int32_t pid,
                                       uint64_t &read_bytes,
                                       uint64_t &write_bytes,
                                       uint64_t &read_ops,
                                       uint64_t &write_ops) const {
    std::ifstream input("/proc/" + std::to_string(pid) + "/io");
    if (!input) return false;
    bool rb = false, wb = false, ro = false, wo = false;
    std::string key;
    uint64_t value = 0;
    while (input >> key >> value) {
        if (key == "read_bytes:") {
            read_bytes = value;
            rb         = true;
        } else if (key == "write_bytes:") {
            write_bytes = value;
            wb          = true;
        } else if (key == "syscr:") {
            read_ops = value;
            ro       = true;
        } else if (key == "syscw:") {
            write_ops = value;
            wo        = true;
        }
        if (rb && wb && ro && wo) break;
    }

    return rb && wb && ro && wo;
}

uint64_t ProcessMonitor::GetSystemTotalMemoryKb() {
    std::ifstream input("/proc/meminfo");
    std::string key;
    uint64_t value = 0;
    while (input >> key >> value) {
        if (key == "MemTotal:") return value;
        std::string unit;
        input >> unit;
    }
    return 0;
}

void ProcessMonitor::UpdateProcessLocked(ProcessInfo &process, Clock::time_point now) {
    ProcSnapshot snapshot;
    if (!ReadProcSnapshot(process.pid, snapshot) ||
        snapshot.start_time_ticks != process.start_time_ticks)
        return;
    // /proc/PID/stat 的 CPU 时间以时钟 tick 累计，利用单调时钟间隔计算使用率。
    const long ticks   = std::max<long>(1, sysconf(_SC_CLK_TCK));
    const auto elapsed = std::chrono::duration<double>(now - process.last_update).count();
    if (process.cpu_baseline_valid && elapsed > 0.0 &&
        snapshot.cpu_time_ticks >= process.last_cpu_time) {
        process.cpu_percent = static_cast<float>((snapshot.cpu_time_ticks - process.last_cpu_time) *
                                                 100.0 / (static_cast<double>(ticks) * elapsed));
        if (!std::isfinite(process.cpu_percent)) process.cpu_percent = 0.0F;
    } else {
        process.cpu_percent = 0.0F;
    }
    process.cpu_time      = static_cast<float>(snapshot.cpu_time_ticks) / static_cast<float>(ticks);
    process.last_cpu_time = snapshot.cpu_time_ticks;
    process.cpu_baseline_valid = true;

    float mem = 0.0F, percent = 0.0F;
    int32_t threads = process.thread_count;
    if (ReadProcessMemory(process.pid, mem, percent, threads)) {
        process.mem_mb       = mem;
        process.mem_percent  = percent;
        process.thread_count = threads;
    }

    // /proc/PID/io 提供累计量；第一次读取建立基线，后续再计算磁盘速率。
    uint64_t rb = 0, wb = 0, ro = 0, wo = 0;
    if (ReadProcessDiskIO(process.pid, rb, wb, ro, wo)) {
        if (process.disk_baseline_valid && elapsed > 0.0) {
            process.disk_read_rate =
                rb >= process.last_disk_read_bytes
                    ? static_cast<float>((rb - process.last_disk_read_bytes) / 1024.0 / elapsed)
                    : 0.0F;
            process.disk_write_rate =
                wb >= process.last_disk_write_bytes
                    ? static_cast<float>((wb - process.last_disk_write_bytes) / 1024.0 / elapsed)
                    : 0.0F;
        }
        process.disk_read_bytes       = rb;
        process.disk_write_bytes      = wb;
        process.disk_read_ops         = ro;
        process.disk_write_ops        = wo;
        process.last_disk_read_bytes  = rb;
        process.last_disk_write_bytes = wb;
        process.last_disk_read_ops    = ro;
        process.last_disk_write_ops   = wo;
        process.disk_baseline_valid   = true;
    }
    process.last_update = now;
}

void ProcessMonitor::UpdateAll() {
    const auto now = Clock::now();
    std::lock_guard<std::mutex> lock(mutex_);
    PruneLocked(now);

    for (auto &entry : registered_nodes_) {
        UpdateProcessLocked(entry.second, now);
    }
}

void ProcessMonitor::GetAllNodeInfo(std::vector<NodeMonitorInfo> &infos) {
    std::lock_guard<std::mutex> lock(mutex_);
    infos.clear();
    infos.reserve(registered_nodes_.size());

    for (const auto &entry : registered_nodes_) {
        const auto &p = entry.second;
        NodeMonitorInfo info;
        info.node_name       = p.node_name;
        info.process_name    = p.process_name;
        info.pid             = p.pid;
        info.cpu_percent     = p.cpu_percent;
        info.cpu_time        = p.cpu_time;
        info.mem_mb          = p.mem_mb;
        info.mem_percent     = p.mem_percent;
        info.thread_count    = p.thread_count;
        info.disk_read_rate  = p.disk_read_rate;
        info.disk_write_rate = p.disk_write_rate;
        // ROS 接口使用 int64，累计计数饱和裁剪以避免超范围转换。
        info.disk_read_bytes = static_cast<int64_t>(
            std::min<uint64_t>(p.disk_read_bytes, static_cast<uint64_t>(INT64_MAX)));
        info.disk_write_bytes = static_cast<int64_t>(
            std::min<uint64_t>(p.disk_write_bytes, static_cast<uint64_t>(INT64_MAX)));
        info.disk_read_ops = static_cast<int64_t>(
            std::min<uint64_t>(p.disk_read_ops, static_cast<uint64_t>(INT64_MAX)));
        info.disk_write_ops = static_cast<int64_t>(
            std::min<uint64_t>(p.disk_write_ops, static_cast<uint64_t>(INT64_MAX)));
        infos.push_back(std::move(info));
    }
}

bool ProcessMonitor::IsRegistered(const std::string &name) {
    std::lock_guard<std::mutex> lock(mutex_);
    PruneLocked(Clock::now());
    return registered_nodes_.find(name) != registered_nodes_.end();
}

size_t ProcessMonitor::RegisteredCount() {
    std::lock_guard<std::mutex> lock(mutex_);
    return registered_nodes_.size();
}

size_t ProcessMonitor::TombstoneCount() {
    std::lock_guard<std::mutex> lock(mutex_);
    return terminated_identities_.size();
}

std::vector<std::string> ProcessMonitor::TakeCleanupEvents() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> events;
    events.swap(cleanup_events_);
    return events;
}
}  // namespace monitor
