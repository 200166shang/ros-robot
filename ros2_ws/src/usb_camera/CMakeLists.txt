cmake_minimum_required(VERSION 3.5)
project(usb_camera)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(usb_camera_node
  src/usb_camera_node.cpp
  src/v4l2_camera.cpp
)
target_include_directories(usb_camera_node PRIVATE include)
ament_target_dependencies(usb_camera_node rclcpp sensor_msgs std_msgs)

install(TARGETS usb_camera_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
