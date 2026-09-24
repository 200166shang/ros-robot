FROM ros:jazzy-ros-base
ARG APT_HTTP_PROXY=""
ENV DEBIAN_FRONTEND=noninteractive
RUN if [ -n "$APT_HTTP_PROXY" ]; then \
      apt-get -o "Acquire::http::Proxy=$APT_HTTP_PROXY" update && \
      apt-get -o "Acquire::http::Proxy=$APT_HTTP_PROXY" install -y --no-install-recommends \
        python3-colcon-common-extensions ros-jazzy-nav2-bringup \
        ros-jazzy-nav2-minimal-tb3-sim ros-jazzy-nav2-loopback-sim \
        ros-jazzy-slam-toolbox && \
      rm -rf /var/lib/apt/lists/*; \
    else \
      apt-get update && \
      apt-get install -y --no-install-recommends \
        python3-colcon-common-extensions ros-jazzy-nav2-bringup \
        ros-jazzy-nav2-minimal-tb3-sim ros-jazzy-nav2-loopback-sim \
        ros-jazzy-slam-toolbox && \
      rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /opt/nav2_ws
COPY ros2_ws/src /opt/nav2_ws/src
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && colcon build --base-paths /opt/nav2_ws/src --merge-install"
ENV ROS_DOMAIN_ID=62
ENV ROS_LOCALHOST_ONLY=1
EXPOSE 18091
CMD ["bash", "-lc", "source /opt/nav2_ws/install/setup.bash && ros2 launch robot_nav2_gateway nav2_loopback.launch.py use_rviz:=False"]
