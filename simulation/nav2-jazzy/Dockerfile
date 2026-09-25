# syntax=docker/dockerfile:1
FROM ros:jazzy-ros-base
ARG APT_HTTP_PROXY=""
ENV DEBIAN_FRONTEND=noninteractive

RUN rm -f /etc/apt/apt.conf.d/docker-clean

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eu; \
    if [ -n "$APT_HTTP_PROXY" ]; then \
      export http_proxy="$APT_HTTP_PROXY"; \
      export https_proxy="$APT_HTTP_PROXY"; \
    fi; \
    apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=120 \
      -o Acquire::http::Pipeline-Depth=0 update; \
    for attempt in 1 2 3; do \
      if apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=120 \
        -o Acquire::http::Pipeline-Depth=0 install -y --no-install-recommends \
        python3-colcon-common-extensions ros-jazzy-nav2-bringup \
        ros-jazzy-nav2-minimal-tb3-sim ros-jazzy-nav2-loopback-sim \
        ros-jazzy-slam-toolbox; then \
        exit 0; \
      fi; \
      if [ "$attempt" -eq 3 ]; then exit 1; fi; \
      echo "APT install failed on attempt $attempt; retrying with cached package downloads."; \
      sleep 5; \
    done
WORKDIR /opt/nav2_ws
COPY ros2_ws/src /opt/nav2_ws/src
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && colcon build --base-paths /opt/nav2_ws/src --merge-install"
ENV ROS_DOMAIN_ID=62
ENV ROS_LOCALHOST_ONLY=1
EXPOSE 18091
CMD ["bash", "-lc", "source /opt/nav2_ws/install/setup.bash && ros2 launch robot_nav2_gateway nav2_loopback.launch.py use_rviz:=False"]
