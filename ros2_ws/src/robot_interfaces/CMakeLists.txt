cmake_minimum_required(VERSION 3.5)
project(robot_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Det.msg"
  "msg/Dets.msg"
  "msg/HeadState.msg"
  "msg/BaseState.msg"
  "msg/SimPersonState.msg"
  "action/HeadMotion.action"
  DEPENDENCIES action_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime action_msgs std_msgs)
ament_package()
