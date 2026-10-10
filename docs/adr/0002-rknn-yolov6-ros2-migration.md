# Preserve detector behavior behind the ROS 2 interface

Migrate the existing YOLOv6 detector's ARM64 RKNN/RGA path, two-stage worker flow, and non-ARM Haar fallback into the ROS 2 package while keeping its current topics, message types, and parameter names. The processing paths and external model assets remain separate from ROS wiring; keeping the established ROS 2 detection interface avoids breaking `object_track`, while preserving the source runtime behavior avoids changing detector results as part of the ROS 1-to-ROS 2 migration.
