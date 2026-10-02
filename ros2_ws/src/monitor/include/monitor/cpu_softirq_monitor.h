#pragma once
#include <array>
#include <chrono>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "monitor/monitor_inter.h"

namespace monitor {
class CpuSoftIrqMonitor : public MonitorInter {
    struct Previous {
        std::array<uint64_t, 10> values{};
        std::chrono::steady_clock::time_point timepoint{};
    };

public:
    void UpdateOnce(MonitorInfo *monitor_info) override;

private:
    std::unordered_map<std::string, Previous> previous_;
};
}  // namespace monitor
