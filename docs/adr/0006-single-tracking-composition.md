---
status: accepted
supersedes: 0005 (mode selection and custom process supervision only)
---

# Use one tracking composition and normal Launch lifecycle

The project targets one fixed Orange Pi robot. Keep a single tracking process
composition and use runtime services to control behavior. Launch starts every
perception dependency; it does not select between visual-only and full modes or
implement a second process supervisor.

## Decision

- `robot_bringup/launch/tracking.launch.py` always includes Camera, Decoder,
  Detector, YDLIDAR, platform TF, and ObjectTrack. `with_foxglove` remains the
  only optional launch argument.
- ObjectTrack has one safety model. Follow can start only after synchronized
  image/detection input, enabled LiDAR Fusion, a valid camera-to-laser TF, and a
  recent LaserScan are available. It never falls back to image-only following.
- `/tracking/set_lidar_enabled` controls ObjectTrack's scan subscription; it
  does not start or stop the YDLIDAR driver. `/tracking/set_enabled` controls
  Follow. Both default to disabled, and disabling fusion while Follow is active
  returns the tracker to standby with a zero command.
- Keep `dry_run: true` as the default. Missing or stale range data must clear
  the range and command state and prevent nonzero follow output.
- Let ROS 2 Launch manage normal process lifetimes. A child exit does not
  automatically restart it or request shutdown of the remaining composition;
  operator shutdown closes all children started by that Launch invocation.
- Keep Agent, Web, and Voice as a separate demonstration composition. It may
  reuse the base tracking Launch without mode arguments.

## Consequences

The combined Launch has one fixed hardware composition and one optional
visualization argument. Operators enable sensor fusion and Follow only after
the services report that their dependencies are ready. Node exit recovery is
an operator or deployment responsibility; a future restart policy should be
introduced only when its operational requirements are defined.
