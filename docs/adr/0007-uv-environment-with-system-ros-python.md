---
status: accepted
---

# Manage project Python dependencies with uv on the system ROS interpreter

Use a root uv project and virtual environment based explicitly on the Orange Pi's system Python 3.8 interpreter, with system packages visible, so project-installed dependencies are isolated without replacing the Python ABI required by ROS 2 Foxy and its binary extensions. Commit the Python dependency lockfile and record the system dependency baseline separately; colcon remains responsible for installing ROS source packages and must run under the project interpreter. Project command entry points centralize environment setup, with dependency synchronization explicit and ordinary execution neither installing dependencies nor modifying the lockfile.

This deliberately retains a dependency on the board's system environment: the uv lockfile reproduces project-managed Python dependencies, not the complete ROS and operating-system installation. Managing third-party dependencies in uv while retaining ROS package installation in colcon avoids two competing installations of the same project source packages.

Include the sherpa speech tools in the same root `.venv` rather than maintaining a separate speech environment. Voice nodes continue to invoke the sherpa executables as child processes, and model assets remain outside the repository; a separate process does not require a separate dependency environment.
