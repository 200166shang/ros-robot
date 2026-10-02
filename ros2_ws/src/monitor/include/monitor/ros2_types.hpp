#pragma once
#include "monitor_interfaces/msg/cpu_load.hpp"
#include "monitor_interfaces/msg/cpu_soft_irq.hpp"
#include "monitor_interfaces/msg/cpu_stat.hpp"
#include "monitor_interfaces/msg/mem_info.hpp"
#include "monitor_interfaces/msg/monitor_info.hpp"
#include "monitor_interfaces/msg/net_info.hpp"
#include "monitor_interfaces/msg/node_monitor_info.hpp"

namespace monitor {
using CpuLoad         = monitor_interfaces::msg::CpuLoad;
using CpuSoftIrq      = monitor_interfaces::msg::CpuSoftIrq;
using CpuStat         = monitor_interfaces::msg::CpuStat;
using MemInfo         = monitor_interfaces::msg::MemInfo;
using MonitorInfo     = monitor_interfaces::msg::MonitorInfo;
using NetInfo         = monitor_interfaces::msg::NetInfo;
using NodeMonitorInfo = monitor_interfaces::msg::NodeMonitorInfo;
}  // namespace monitor
