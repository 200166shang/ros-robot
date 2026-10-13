---
status: accepted
---

# Separate tracking process startup from follow behavior control

The launch argument and compatibility-topic choices below were revised by
[ADR 0005](0005-launch-yaml-and-tracking-control.md). The separation of process
composition from tracking behavior, Follow standby, acknowledged services, and
process ownership remain in effect.

The later `mode` switch and custom restart behavior were introduced after this
decision and are superseded by [ADR 0006](0006-single-tracking-composition.md).
The fixed bringup composition and service-controlled behavior described here
remain in effect.

The legacy webpage owns both process startup and behavior switches, while the current ROS 2 perception entry mixes basic tracking with Agent and web defaults. Put process composition and ownership in `robot_bringup`, reuse independent package launch/configuration, and start the basic tracking profile in follow standby; this keeps manual node startup and complete startup consistent without coupling perception to a particular operator interface.

Keep follow behavior and LiDAR fusion state in `object_track`, and expose acknowledged ROS control services. Preview subscriptions do not determine whether enabled following runs, and the existing voice/LLM demo becomes a separate composition of the basic pipeline.

Keep platform sensor transforms in bringup configuration, algorithm parameters with their owning packages, and dry-run safe routing from ADR 0003. Avoid a second process manager inside the webpage or a general dependency scheduler; an invocation manages only the processes it creates.
