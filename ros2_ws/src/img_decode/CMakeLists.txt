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

add_executable(img_decode_node src/img_decode_node.cpp)
ament_target_dependencies(img_decode_node rclcpp sensor_msgs)
target_include_directories(img_decode_node PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(img_decode_node ${OpenCV_LIBRARIES})

add_executable(image_monitor src/image_monitor.cpp)
ament_target_dependencies(image_monitor rclcpp sensor_msgs)
target_include_directories(image_monitor PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(image_monitor ${OpenCV_LIBRARIES})

install(TARGETS img_decode_node image_monitor DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
