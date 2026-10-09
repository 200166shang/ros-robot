cmake_minimum_required(VERSION 3.5)
project(img_encode)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)

set(IMG_ENCODE_BACKEND "AUTO" CACHE STRING "JPEG encoder backend: AUTO, OPENCV, or MPP")
set_property(CACHE IMG_ENCODE_BACKEND PROPERTY STRINGS AUTO OPENCV MPP)
string(TOUPPER "${IMG_ENCODE_BACKEND}" IMG_ENCODE_BACKEND)

if(IMG_ENCODE_BACKEND STREQUAL "AUTO")
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
    set(IMG_ENCODE_BACKEND "MPP")
  else()
    set(IMG_ENCODE_BACKEND "OPENCV")
  endif()
endif()

if(IMG_ENCODE_BACKEND STREQUAL "MPP")
  set(IMG_ENCODE_BACKEND_SOURCE src/mpp_jpeg_encoder_backend.cpp)
  find_path(MPP_INCLUDE_DIR rockchip/rk_mpi.h)
  find_path(RGA_INCLUDE_DIR rga/im2d.h)
  find_library(MPP_LIBRARY rockchip_mpp)
  find_library(RGA_LIBRARY rga)
  if(NOT MPP_INCLUDE_DIR OR NOT RGA_INCLUDE_DIR OR NOT MPP_LIBRARY OR NOT RGA_LIBRARY)
    message(FATAL_ERROR "MPP backend requires Rockchip MPP and RGA headers and libraries")
  endif()
elseif(NOT IMG_ENCODE_BACKEND STREQUAL "OPENCV")
  message(FATAL_ERROR "IMG_ENCODE_BACKEND must be AUTO, OPENCV, or MPP")
else()
  set(IMG_ENCODE_BACKEND_SOURCE src/opencv_jpeg_encoder_backend.cpp)
endif()

add_library(img_encode_core
  src/jpeg_encoder.cpp
  src/image_encode_node.cpp
  ${IMG_ENCODE_BACKEND_SOURCE})
target_include_directories(img_encode_core
  PUBLIC include ${OpenCV_INCLUDE_DIRS}
  PRIVATE src)
ament_target_dependencies(img_encode_core rclcpp sensor_msgs)
target_link_libraries(img_encode_core ${OpenCV_LIBRARIES})

if(IMG_ENCODE_BACKEND STREQUAL "MPP")
  target_include_directories(img_encode_core PRIVATE ${MPP_INCLUDE_DIR} ${RGA_INCLUDE_DIR})
  target_link_libraries(img_encode_core ${MPP_LIBRARY} ${RGA_LIBRARY})
  set(IMG_ENCODE_EXPORT_LIBRARIES img_encode_core ${MPP_LIBRARY} ${RGA_LIBRARY})
else()
  set(IMG_ENCODE_EXPORT_LIBRARIES img_encode_core)
endif()

add_executable(img_encode_node src/img_encode_main.cpp)
ament_target_dependencies(img_encode_node rclcpp sensor_msgs)
target_link_libraries(img_encode_node img_encode_core)

install(TARGETS img_encode_core img_encode_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_img_encode test/test_img_encode.cpp)
  ament_target_dependencies(test_img_encode rclcpp sensor_msgs)
  target_link_libraries(test_img_encode img_encode_core ${OpenCV_LIBRARIES})
endif()

ament_export_include_directories(include)
ament_export_libraries(${IMG_ENCODE_EXPORT_LIBRARIES})
ament_export_dependencies(rclcpp sensor_msgs OpenCV)
ament_package()
