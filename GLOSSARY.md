# ROS Robot

This glossary defines shared terms for the robot's sensor and perception pipelines.

## Camera benchmark

**Capture FPS**:
The rate at which camera frames become available at the acquisition boundary.
_Avoid_: Camera FPS when the measurement stage is unspecified

**Publish FPS**:
The rate at which the camera publisher emits image messages.

**Receive FPS**:
The rate at which the benchmark receiver handles image messages.

**V4L2 sequence gap**:
A missing value between consecutive frame sequence numbers reported by the V4L2 capture stream.

**Publish/receive count difference**:
The difference between published and received message totals after the receiver has drained; it is an aggregate delivery measure, not per-frame loss attribution.

**Publish-to-receive latency**:
Elapsed time from the image message timestamp set at publication to the benchmark receiver callback.
