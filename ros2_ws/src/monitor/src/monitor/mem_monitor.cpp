#include "monitor/mem_monitor.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>

namespace monitor {
void MemMonitor::UpdateOnce(MonitorInfo *info) {
    // /proc/meminfo 的数值单位是 KiB，消息内存字段统一转换为 GiB。
    std::ifstream input("/proc/meminfo");
    std::unordered_map<std::string, uint64_t> kb;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream row(line);
        std::string key, unit;
        uint64_t value = 0;
        if (row >> key >> value) kb[key] = value;
    }

    const auto get = [&](const char *key) -> uint64_t {
        auto it = kb.find(key);
        return it == kb.end() ? 0 : it->second;
    };
    const auto total     = get("MemTotal:");
    const auto available = get("MemAvailable:");

    if (total == 0) return;
    auto gib = [](uint64_t value) {
        return static_cast<float>(static_cast<double>(value) / (1024.0 * 1024.0));
    };
    auto &m = info->mem_info;
    m.total = gib(total);
    m.free  = gib(get("MemFree:"));
    m.avail = gib(available);

    m.buffers     = gib(get("Buffers:"));
    m.cached      = gib(get("Cached:"));
    m.swap_cached = gib(get("SwapCached:"));

    m.active   = gib(get("Active:"));
    m.inactive = gib(get("Inactive:"));

    m.active_anon   = gib(get("Active(anon):"));
    m.inactive_anon = gib(get("Inactive(anon):"));
    m.active_file   = gib(get("Active(file):"));
    m.inactive_file = gib(get("Inactive(file):"));

    m.dirty        = gib(get("Dirty:"));
    m.writeback    = gib(get("Writeback:"));
    m.anon_pages   = gib(get("AnonPages:"));
    m.mapped       = gib(get("Mapped:"));
    m.kreclaimable = gib(get("KReclaimable:"));
    m.sreclaimable = gib(get("SReclaimable:"));
    m.sunreclaim   = gib(get("SUnreclaim:"));

    // MemAvailable 包含可回收缓存，比只用 MemFree 更接近系统可用内存。
    m.used_percent =
        static_cast<float>(100.0 * static_cast<double>(total - std::min(total, available)) /
                           static_cast<double>(total));
}
}  // namespace monitor
