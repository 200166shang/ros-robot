cmake_minimum_required(VERSION 3.5)
project(monitor)
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(monitor_interfaces REQUIRED)
find_package(rosbag2_cpp REQUIRED)
find_package(rosbag2_storage REQUIRED)
find_package(rcutils REQUIRED)
add_library(monitor_core
  src/monitor/cpu_load_monitor.cpp
  src/monitor/cpu_softirq_monitor.cpp
  src/monitor/cpu_stat_monitor.cpp
  src/monitor/mem_monitor.cpp
  src/monitor/net_monitor.cpp
  src/monitor/process_monitor.cpp)
target_include_directories(monitor_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(monitor_core
  rclcpp
  monitor_interfaces)
add_library(monitor_bag_writer src/monitor/monitor_bag_writer.cpp)
target_include_directories(monitor_bag_writer PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(monitor_bag_writer
  rclcpp
  rosbag2_cpp
  rosbag2_storage
  rcutils
  monitor_interfaces)
add_executable(monitor_node src/main.cpp)
target_link_libraries(monitor_node monitor_core)
target_link_libraries(monitor_node monitor_bag_writer)
ament_target_dependencies(monitor_node
  rclcpp
  std_msgs
  monitor_interfaces)
install(TARGETS
  monitor_core
  monitor_bag_writer
  monitor_node
  EXPORT export_monitor
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/monitor)
install(DIRECTORY include/ DESTINATION include)
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_process_monitor test/test_process_monitor.cpp)
  target_link_libraries(test_process_monitor monitor_core)
  ament_target_dependencies(test_process_monitor
    monitor_interfaces)
endif()
ament_export_targets(export_monitor HAS_LIBRARY_TARGET)
ament_export_include_directories(include)
ament_export_dependencies(
  rclcpp
  monitor_interfaces
  rosbag2_cpp
  rosbag2_storage
  rcutils)
ament_package()
