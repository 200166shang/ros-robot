#pragma once
#include "monitor/ros2_types.hpp"

namespace monitor {
class MonitorInter {
public:
    virtual ~MonitorInter()                            = default;
    virtual void UpdateOnce(MonitorInfo *monitor_info) = 0;
};
}  // namespace monitor
