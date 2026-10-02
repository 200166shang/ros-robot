#include "monitor/cpu_softirq_monitor.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <unordered_map>

namespace monitor {
void CpuSoftIrqMonitor::UpdateOnce(MonitorInfo *info) {
    std::ifstream input("/proc/softirqs");
    std::string line;
    if (!std::getline(input, line)) return;
    std::istringstream headings(line);
    std::vector<std::string> cpus;
    std::string cpu;
    while (headings >> cpu) {
        cpus.push_back(cpu);
    }

    if (cpus.empty()) return;

    // /proc/softirqs 以行名区分中断类型，表中索引对应消息字段顺序。
    static const std::unordered_map<std::string, size_t> row_index{{"HI", 0},
                                                                   {"TIMER", 1},
                                                                   {"NET_TX", 2},
                                                                   {"NET_RX", 3},
                                                                   {"BLOCK", 4},
                                                                   {"IRQ_POLL", 5},
                                                                   {"TASKLET", 6},
                                                                   {"SCHED", 7},
                                                                   {"HRTIMER", 8},
                                                                   {"RCU", 9}};

    std::unordered_map<std::string, std::array<uint64_t, 10>> current;
    while (std::getline(input, line)) {
        const auto split = line.find(':');
        if (split == std::string::npos) continue;
        std::string key = line.substr(0, split);
        key.erase(0, key.find_first_not_of(" \\t"));
        key.erase(key.find_last_not_of(" \\t") + 1);
        auto row = row_index.find(key);
        if (row == row_index.end()) continue;
        std::istringstream values(line.substr(split + 1));
        for (const auto &name : cpus) {
            uint64_t count = 0;
            if (!(values >> count)) break;
            current[name][row->second] = count;
        }
    }

    // 文件提供累计计数，除以两次读取的单调时钟间隔得到每秒事件数。
    const auto now = std::chrono::steady_clock::now();
    for (const auto &name : cpus) {
        auto values = current.find(name);
        if (values == current.end()) continue;
        auto old = previous_.find(name);
        if (old != previous_.end()) {
            const double elapsed =
                std::chrono::duration<double>(now - old->second.timepoint).count();
            if (elapsed <= 0.0) continue;
            auto rate = [&](size_t i) -> int64_t {
                if (values->second[i] < old->second.values[i]) return 0;
                const double result = (values->second[i] - old->second.values[i]) / elapsed;
                if (!std::isfinite(result) || result > static_cast<double>(INT64_MAX))
                    return INT64_MAX;
                return static_cast<int64_t>(result);
            };
            CpuSoftIrq out;
            out.cpu_name = name;
            out.hi       = rate(0);
            out.timer    = rate(1);
            out.net_tx   = rate(2);
            out.net_rx   = rate(3);
            out.block    = rate(4);
            out.irq_poll = rate(5);
            out.tasklet  = rate(6);
            out.sched    = rate(7);
            out.hrtimer  = rate(8);
            out.rcu      = rate(9);
            info->cpu_softirq.push_back(std::move(out));
        }

        previous_[name] = Previous{values->second, now};
    }
}
}  // namespace monitor
