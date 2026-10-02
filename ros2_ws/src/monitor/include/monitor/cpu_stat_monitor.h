#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "monitor/monitor_inter.h"

namespace monitor {
class CpuStatMonitor : public MonitorInter {
    struct CpuTicks {
        std::vector<uint64_t> values;
    };

public:
    void UpdateOnce(MonitorInfo *monitor_info) override;

private:
    std::unordered_map<std::string, CpuTicks> previous_;
};
}  // namespace monitor
