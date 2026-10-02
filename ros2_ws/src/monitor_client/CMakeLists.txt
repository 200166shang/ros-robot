cmake_minimum_required(VERSION 3.5)
project(monitor_client)
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(monitor_interfaces REQUIRED)
add_library(monitor_client src/monitor_registration.cpp)
target_include_directories(monitor_client PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_link_libraries(monitor_client pthread)
ament_target_dependencies(monitor_client
  rclcpp
  monitor_interfaces)
install(TARGETS
  monitor_client
  EXPORT export_monitor_client
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)
ament_export_targets(export_monitor_client HAS_LIBRARY_TARGET)
ament_export_include_directories(include)
ament_export_dependencies(
  rclcpp
  monitor_interfaces)
if(BUILD_TESTING)
  add_executable(multi_node_probe test/multi_node_probe.cpp)
  target_link_libraries(multi_node_probe monitor_client)
  ament_target_dependencies(multi_node_probe
    rclcpp
    monitor_interfaces)
  install(TARGETS
    multi_node_probe
    RUNTIME DESTINATION lib/monitor_client)
endif()
ament_package()
