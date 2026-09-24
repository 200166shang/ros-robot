cmake_minimum_required(VERSION 3.5)
project(object_track)

include(CTest)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(robot_interfaces REQUIRED)

add_executable(object_track_node src/object_track_node.cpp)
target_include_directories(object_track_node PRIVATE include)
ament_target_dependencies(object_track_node rclcpp geometry_msgs std_msgs robot_interfaces)

if(BUILD_TESTING)
  add_executable(test_tracking_output test/test_tracking_output.cpp)
  target_include_directories(test_tracking_output PRIVATE include)
  target_compile_options(test_tracking_output PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME tracking_output_routing COMMAND test_tracking_output)
endif()

install(TARGETS object_track_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include launch DESTINATION share/${PROJECT_NAME})
ament_package()
