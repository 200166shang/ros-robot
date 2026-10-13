cmake_minimum_required(VERSION 3.5)
project(robot_bringup)

find_package(ament_cmake REQUIRED)
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/acceptance_probe.py
  scripts/voice_tracking_acceptance_probe.py
  scripts/object_track_acceptance_probe.py
  scripts/tracking_control_acceptance_probe.py
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(
    test_tracking_launch
    test/test_tracking_launch.py
  )
endif()

ament_package()
