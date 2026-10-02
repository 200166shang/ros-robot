#include "monitor/cpu_stat_monitor.h"

#include <algorithm>
#include <fstream>
#include <sstream>

namespace monitor {
void CpuStatMonitor::UpdateOnce(MonitorInfo *info) {
    std::ifstream input("/proc/stat");
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream row(line);
        std::string name;
        if (!(row >> name) || name.rfind("cpu", 0) != 0) continue;
        std::vector<uint64_t> ticks;
        uint64_t value = 0;
        while (row >> value) {
            ticks.push_back(value);
        }
        if (ticks.size() < 4) continue;

        auto old = previous_.find(name);
        if (old != previous_.end()) {
            const auto &before = old->second.values;
            auto at            = [](const std::vector<uint64_t> &v, size_t i) {
                return i < v.size() ? v[i] : uint64_t{0};
            };
            uint64_t total_delta = 0, busy_delta = 0;
            // guest 和 guest_nice 已计入 user/nice，不能再次进入总 ticks。
            // /proc/stat 前八项构成总量；busy 只累加非 idle、非 iowait 项。
            constexpr size_t tick_count = 8;
            for (size_t i = 0; i < tick_count; ++i) {
                const auto current = at(ticks, i);
                const auto prior   = at(before, i);
                if (current >= prior) {
                    total_delta += current - prior;
                }
            }
            for (size_t i : {size_t{0}, size_t{1}, size_t{2}, size_t{5}, size_t{6}, size_t{7}}) {
                const auto current = at(ticks, i);
                const auto prior   = at(before, i);
                if (current >= prior) {
                    busy_delta += current - prior;
                }
            }

            if (total_delta > 0) {
                CpuStat out;
                out.cpu_name     = name;
                const auto total = static_cast<double>(total_delta);
                auto rate        = [&](size_t i) {
                    const auto current = at(ticks, i);
                    const auto prior   = at(before, i);
                    return current >= prior ? static_cast<float>(100.0 * (current - prior) / total)
                                            : 0.0F;
                };
                out.cpu_percent      = static_cast<float>(100.0 * busy_delta / total);
                out.usr_percent      = rate(0);
                out.nice_percent     = rate(1);
                out.system_percent   = rate(2);
                out.idle_percent     = rate(3);
                out.io_wait_percent  = rate(4);
                out.irq_percent      = rate(5);
                out.soft_irq_percent = rate(6);
                info->cpu_stat.push_back(std::move(out));
            }
        }

        previous_[name].values = std::move(ticks);
    }
}
}  // namespace monitor
