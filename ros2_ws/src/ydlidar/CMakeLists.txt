cmake_minimum_required(VERSION 3.5)
project(ydlidar)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(ydlidar_sdk 1.2.7 REQUIRED)

add_executable(ydlidar_node src/ydlidar_node.cpp)
target_include_directories(ydlidar_node PRIVATE ${YDLIDAR_SDK_INCLUDE_DIRS})
ament_target_dependencies(ydlidar_node rclcpp sensor_msgs std_srvs)
target_link_directories(ydlidar_node PRIVATE ${YDLIDAR_SDK_LIBRARY_DIRS})
target_link_libraries(ydlidar_node ${YDLIDAR_SDK_LIBRARIES})

install(TARGETS ydlidar_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})
ament_package()
