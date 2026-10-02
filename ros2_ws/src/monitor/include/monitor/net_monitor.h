#pragma once
#include <chrono>
#include <cstdint>
#include <string>
#include <unordered_map>

#include "monitor/monitor_inter.h"

namespace monitor {
class NetMonitor : public MonitorInter {
    struct InterfaceStats {
        uint64_t rx_bytes{0}, rx_packets{0}, tx_bytes{0}, tx_packets{0};
        std::chrono::steady_clock::time_point timepoint{};
    };

public:
    void UpdateOnce(MonitorInfo *monitor_info) override;

private:
    std::unordered_map<std::string, InterfaceStats> previous_;
};
}  // namespace monitor
