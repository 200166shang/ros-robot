# monitor_client

`monitor_client::MonitorRegistration` registers one C++ ROS node with `monitor`, renews its lease every two seconds, and unregisters it when closed. Keep the object alive with its owner node and call `close()` before `rclcpp::shutdown()`.

```cpp
auto node = std::make_shared<MyNode>();
monitor_client::MonitorRegistration monitor_registration(node);

// In the application's controlled shutdown path:
monitor_registration.close();
rclcpp::shutdown();
```

Route process signals through the application's shutdown path so it can close the registration before shutting down the ROS context. The destructor also calls `close()`, and repeated calls are safe, but relying on destruction after context shutdown prevents the unregister request. The client library does not take ownership of process signals or the business node's executor.

## Probe

With `monitor_node` running in another terminal, run the C++ main-path probe from `ros2_ws`:

```bash
ros2 run monitor_client multi_node_probe
```

It checks that two nodes in one process report the same PID, then verifies that each registration can be independently removed.
