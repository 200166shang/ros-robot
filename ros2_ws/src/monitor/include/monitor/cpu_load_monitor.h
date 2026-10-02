#pragma once
#include "monitor/monitor_inter.h"

namespace monitor {
class CpuLoadMonitor : public MonitorInter {
public:
    void UpdateOnce(MonitorInfo *monitor_info) override;
};
}  // namespace monitor
