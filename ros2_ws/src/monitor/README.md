# monitor

The node samples system and registered process statistics every three seconds, publishes to the `monitor_topic` parameter (default `/monitor_info`) when the topic has subscribers, and always records samples through the Foxy rosbag2 C++ API. The default bag URI is `monitor_data.bag`; it must not already exist.

## Metric units

- CPU percentages and load averages are unitless; `cpu_time` is cumulative CPU seconds.
- Memory fields in `MemInfo` are GiB. Process `mem_mb` is MiB.
- Network byte rates and process disk byte rates are KiB/s. Packet rates are packets/s.
- Process disk byte and operation fields are cumulative bytes and operations.
- Softirq fields are event counts per second.

The message schema stays language neutral in `monitor_interfaces`.

## Run

After sourcing ROS Foxy and the workspace overlay from `ros2_ws`, start the node with:

```bash
ros2 run monitor monitor_node
```

The default `monitor_data.bag` URI is created in the current working directory and must not already exist. Set `bag_file_path` to a fresh URI when running another recording.
