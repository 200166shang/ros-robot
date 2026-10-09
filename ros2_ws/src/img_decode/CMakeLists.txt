cmake_minimum_required(VERSION 3.5)
project(img_decode)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)

set(IMG_DECODE_BACKEND "AUTO" CACHE STRING "Image processing backend: AUTO, OPENCV, or ROCKCHIP")
set_property(CACHE IMG_DECODE_BACKEND PROPERTY STRINGS AUTO OPENCV ROCKCHIP)
string(TOUPPER "${IMG_DECODE_BACKEND}" IMG_DECODE_BACKEND)

if(IMG_DECODE_BACKEND STREQUAL "AUTO")
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
    set(IMG_DECODE_BACKEND "ROCKCHIP")
  else()
    set(IMG_DECODE_BACKEND "OPENCV")
  endif()
endif()

if(IMG_DECODE_BACKEND STREQUAL "OPENCV")
  set(IMG_DECODE_PROCESSOR_SOURCE src/opencv_image_processor.cpp)
elseif(IMG_DECODE_BACKEND STREQUAL "ROCKCHIP")
  find_path(ROCKCHIP_MPP_INCLUDE_DIR NAMES rockchip/rk_mpi.h)
  find_path(ROCKCHIP_RGA_INCLUDE_DIR NAMES im2d.h PATH_SUFFIXES rga)
  find_library(ROCKCHIP_MPP_LIBRARY NAMES rockchip_mpp)
  find_library(ROCKCHIP_RGA_LIBRARY NAMES rga)
  if(NOT ROCKCHIP_MPP_INCLUDE_DIR OR NOT ROCKCHIP_RGA_INCLUDE_DIR OR
     NOT ROCKCHIP_MPP_LIBRARY OR NOT ROCKCHIP_RGA_LIBRARY)
    message(FATAL_ERROR "ROCKCHIP backend requires MPP headers/library and RGA headers/library")
  endif()
  set(IMG_DECODE_PROCESSOR_SOURCE src/rockchip_image_processor.cpp)
else()
  message(FATAL_ERROR "Unknown IMG_DECODE_BACKEND '${IMG_DECODE_BACKEND}'; use AUTO, OPENCV, or ROCKCHIP")
endif()
message(STATUS "img_decode processing backend: ${IMG_DECODE_BACKEND}")

add_library(img_decode_processor
  src/image_decode_node.cpp
  ${IMG_DECODE_PROCESSOR_SOURCE})
target_include_directories(img_decode_processor PUBLIC include ${OpenCV_INCLUDE_DIRS})
ament_target_dependencies(img_decode_processor rclcpp sensor_msgs)
target_link_libraries(img_decode_processor ${OpenCV_LIBRARIES})
if(IMG_DECODE_BACKEND STREQUAL "ROCKCHIP")
  target_include_directories(img_decode_processor PRIVATE ${ROCKCHIP_MPP_INCLUDE_DIR} ${ROCKCHIP_RGA_INCLUDE_DIR})
  target_link_libraries(img_decode_processor ${ROCKCHIP_MPP_LIBRARY} ${ROCKCHIP_RGA_LIBRARY})
endif()

add_executable(img_decode_node src/img_decode_main.cpp)
target_include_directories(img_decode_node PRIVATE include)
ament_target_dependencies(img_decode_node rclcpp sensor_msgs)
target_link_libraries(img_decode_node img_decode_processor)

add_executable(image_monitor src/image_monitor.cpp)
ament_target_dependencies(image_monitor rclcpp sensor_msgs)
target_include_directories(image_monitor PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(image_monitor ${OpenCV_LIBRARIES})

install(TARGETS img_decode_processor img_decode_node image_monitor
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_img_decode_ros_interface test/test_img_decode_ros_interface.cpp)
  target_include_directories(test_img_decode_ros_interface PRIVATE include ${OpenCV_INCLUDE_DIRS})
  ament_target_dependencies(test_img_decode_ros_interface rclcpp sensor_msgs)
  target_link_libraries(test_img_decode_ros_interface img_decode_processor ${OpenCV_LIBRARIES})
endif()

ament_export_include_directories(include)
ament_export_libraries(img_decode_processor)
ament_package()
