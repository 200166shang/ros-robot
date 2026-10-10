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

set(RKNN_YOLOV6_BACKEND "AUTO" CACHE STRING "Detector backend: AUTO, RKNN, or HAAR")
set_property(CACHE RKNN_YOLOV6_BACKEND PROPERTY STRINGS AUTO RKNN HAAR)
string(TOUPPER "${RKNN_YOLOV6_BACKEND}" RKNN_YOLOV6_BACKEND)

if(RKNN_YOLOV6_BACKEND STREQUAL "AUTO")
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
    set(RKNN_YOLOV6_BACKEND "RKNN")
  else()
    set(RKNN_YOLOV6_BACKEND "HAAR")
  endif()
endif()

if(RKNN_YOLOV6_BACKEND STREQUAL "RKNN")
  set(RKNN_YOLOV6_BACKEND_SOURCE src/detector_backend_rknn.cpp)
  set(RKNN_YOLOV6_OPENCV_COMPONENTS core imgproc imgcodecs)

  set(RKNN_API_INCLUDE_DIR "" CACHE PATH "Directory containing the external Rockchip rknn_api.h header")
  if(NOT RKNN_API_INCLUDE_DIR)
    find_path(RKNN_API_INCLUDE_DIR NAMES rknn_api.h PATHS /usr/include /usr/local/include)
  endif()
  find_library(RKNNRT_LIBRARY NAMES rknnrt rknn_api PATHS /usr/lib /usr/lib/aarch64-linux-gnu /lib /usr/local/lib)
  find_path(RGA_INCLUDE_DIR NAMES im2d.hpp PATHS /usr/include/rga /usr/local/include/rga)
  find_library(RGA_LIBRARY NAMES rga PATHS /usr/lib /usr/lib/aarch64-linux-gnu /lib /usr/local/lib)

  if(NOT RKNN_API_INCLUDE_DIR)
    message(FATAL_ERROR
      "rknn_api.h was not found. Install the matching official Rockchip SDK header outside this repository "
      "and pass -DRKNN_API_INCLUDE_DIR=/path/to/include")
  endif()
  if(NOT RKNNRT_LIBRARY)
    message(FATAL_ERROR "RKNN backend requires the installed rknnrt runtime library")
  endif()
  if(NOT RGA_INCLUDE_DIR OR NOT RGA_LIBRARY)
    message(FATAL_ERROR "RKNN backend requires the installed RGA headers and library")
  endif()
elseif(RKNN_YOLOV6_BACKEND STREQUAL "HAAR")
  set(RKNN_YOLOV6_BACKEND_SOURCE src/detector_backend_haar.cpp)
  set(RKNN_YOLOV6_OPENCV_COMPONENTS core imgproc imgcodecs objdetect)
else()
  message(FATAL_ERROR "RKNN_YOLOV6_BACKEND must be AUTO, RKNN, or HAAR")
endif()

find_package(OpenCV REQUIRED COMPONENTS ${RKNN_YOLOV6_OPENCV_COMPONENTS})

add_library(rknn_yolov6_core src/rknn_yolov6_node.cpp src/postprocess.cpp ${RKNN_YOLOV6_BACKEND_SOURCE})
target_include_directories(rknn_yolov6_core PUBLIC include)
target_include_directories(rknn_yolov6_core PRIVATE ${OpenCV_INCLUDE_DIRS})
ament_target_dependencies(rknn_yolov6_core rclcpp sensor_msgs std_msgs robot_interfaces)
target_link_libraries(rknn_yolov6_core ${OpenCV_LIBRARIES})

if(RKNN_YOLOV6_BACKEND STREQUAL "RKNN")
  target_include_directories(rknn_yolov6_core PRIVATE ${RKNN_API_INCLUDE_DIR} ${RGA_INCLUDE_DIR})
  target_link_libraries(rknn_yolov6_core ${RKNNRT_LIBRARY} ${RGA_LIBRARY})
endif()

add_executable(rknn_yolov6_node src/main.cpp)
ament_target_dependencies(rknn_yolov6_node rclcpp)
target_link_libraries(rknn_yolov6_node rknn_yolov6_core)

install(TARGETS rknn_yolov6_core rknn_yolov6_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_rknn_yolov6_topic test/test_rknn_yolov6_topic.cpp)
  ament_target_dependencies(test_rknn_yolov6_topic rclcpp sensor_msgs robot_interfaces)
  target_link_libraries(test_rknn_yolov6_topic rknn_yolov6_core)
  if(RKNN_YOLOV6_BACKEND STREQUAL "RKNN")
    target_compile_definitions(test_rknn_yolov6_topic PRIVATE RKNN_YOLOV6_TEST_RKNN=1)
  else()
    target_compile_definitions(test_rknn_yolov6_topic PRIVATE RKNN_YOLOV6_TEST_HAAR=1)
  endif()
endif()

ament_package()
