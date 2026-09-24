cmake_minimum_required(VERSION 3.5)
project(robot_bringup)

find_package(ament_cmake REQUIRED)
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/acceptance_probe.py
  scripts/voice_tracking_acceptance_probe.py
  DESTINATION lib/${PROJECT_NAME}
)
ament_package()
