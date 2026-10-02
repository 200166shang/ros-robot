#include "monitor/cpu_load_monitor.h"

#include <cmath>
#include <fstream>

namespace monitor {
void CpuLoadMonitor::UpdateOnce(MonitorInfo *info) {
    std::ifstream input("/proc/loadavg");
    double one = 0.0, five = 0.0, fifteen = 0.0;
    if (!(input >> one >> five >> fifteen) || !std::isfinite(one) || !std::isfinite(five) ||
        !std::isfinite(fifteen))
        return;
    // Linux 提供 1、5、15 分钟负载；字段名与内核统计窗口保持一致。
    info->cpu_load.load_avg_1  = static_cast<float>(one);
    info->cpu_load.load_avg_5  = static_cast<float>(five);
    info->cpu_load.load_avg_15 = static_cast<float>(fifteen);
}
}  // namespace monitor
