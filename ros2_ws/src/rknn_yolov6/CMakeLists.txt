cmake_minimum_required(VERSION 3.5)
project(rknn_yolov6)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(robot_interfaces REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  find_library(RKNNRT_LIBRARY NAMES rknnrt rknn_api PATHS /usr/lib /lib REQUIRED)
  set(RKNN_API_INCLUDE_DIR "" CACHE PATH
    "Directory containing rknn_api.h from the locally installed Rockchip SDK")
  if(NOT RKNN_API_INCLUDE_DIR)
    find_path(RKNN_API_INCLUDE_DIR NAMES rknn_api.h PATHS /usr/include /usr/local/include)
  endif()
  if(NOT RKNN_API_INCLUDE_DIR)
    message(FATAL_ERROR
      "rknn_api.h was not found. Install the Rockchip SDK header outside this repository "
      "and pass -DRKNN_API_INCLUDE_DIR=/path/to/include")
  endif()
  add_executable(rknn_yolov6_node src/rknn_yolov6_node.cpp src/postprocess.cpp)
  target_include_directories(rknn_yolov6_node PRIVATE include ${RKNN_API_INCLUDE_DIR} ${OpenCV_INCLUDE_DIRS})
  ament_target_dependencies(rknn_yolov6_node rclcpp sensor_msgs std_msgs robot_interfaces)
  target_link_libraries(rknn_yolov6_node ${OpenCV_LIBRARIES} ${RKNNRT_LIBRARY})
  install(TARGETS rknn_yolov6_node DESTINATION lib/${PROJECT_NAME})
else()
  message(WARNING "rknn_yolov6_node is only built for ARM64 RK3566 targets")
endif()

install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})
ament_package()
