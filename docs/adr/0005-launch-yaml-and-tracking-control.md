---
status: accepted
supersedes: 0004 (launch interface and Bool compatibility decisions)
---

# Keep launch composition small and module configuration in YAML

The project currently targets one robot. Its combined tracking launch should
show the runtime composition, not duplicate every device and algorithm setting
as a second command-line configuration surface. Package launch files should
remain useful for independent development, and each package should own its
normal ROS parameter file.

ADR 0006 supersedes this ADR's `mode` launch interface and custom process
supervision decisions. Package-owned YAML, the two acknowledged tracking
services, and dry-run safety remain active decisions.

Keep `/tracking/set_enabled` and `/tracking/set_lidar_enabled` as the runtime
control interface for Follow and tracker-side LiDAR fusion. Remove the old
`/enable_tracking` and `/enable_lidar` Bool adapters and migrate in-repository
callers directly to the services. Other module controls, such as camera and
detector enable topics, are outside this decision.

## Decision

- `robot_bringup/launch/tracking.launch.py` exposes only `mode` (default
  `visual_only`) and `with_foxglove` (default `true`). It starts the camera,
  decoder, detector, and tracker in both modes. `full` also starts YDLIDAR and
  the platform camera-to-laser transform; `visual_only` starts neither.
- Both modes begin in Follow standby. `full` does not enable LiDAR fusion or
  chassis output by itself. Follow can be enabled only after the required
  synchronized input, TF, enabled LiDAR fusion, and a recent scan are ready.
  Missing fresh range input must not turn into a camera-only fallback.
- Package launch files load their package YAML without duplicating those
  parameters as launch arguments. `object_track.launch.py` keeps only `mode`,
  also defaulting to `visual_only`. Platform frame names and static extrinsics
  stay in `robot_bringup/config/platform.yaml`.
- Process supervision applies to the core processes created by this combined
  launch, including YDLIDAR and platform TF in `full`. It counts every exit,
  including exit code zero, allows two one-second delayed restarts, and shuts
  down the combination on the third exit. Active shutdown does not schedule a
  restart. Foxglove keeps its prior exclusion from supervision.
- Durable parameter changes belong in the owning package YAML. One-off ROS
  parameter overrides remain useful for direct node diagnostics; they are not
  exposed as arguments on the combined or package launch interfaces.

## Consequences

Operators change hardware and algorithm defaults in one package-owned YAML and
rebuild or reinstall that package before launching from the install space.
Independent package launches no longer accept per-parameter launch overrides.
The combined `full` mode starts its LiDAR and TF dependencies but leaves Follow
and LiDAR fusion under explicit service control. The legacy `perception` and
`camera_decode` compositions and the two tracking Bool topics are removed.
