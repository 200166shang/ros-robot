cmake_minimum_required(VERSION 3.5)
project(monitor_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/CpuLoad.msg"
  "msg/CpuStat.msg"
  "msg/CpuSoftIrq.msg"
  "msg/MemInfo.msg"
  "msg/NetInfo.msg"
  "msg/NodeMonitorInfo.msg"
  "msg/MonitorInfo.msg"
  "srv/RegisterNode.srv"
  "srv/UnregisterNode.srv"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
