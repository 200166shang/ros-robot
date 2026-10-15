# ROS Robot

This glossary defines shared terms for the robot's sensor and perception
pipelines and Agent interactions.

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

## Camera calibration

**Camera calibration**:
Camera model parameters, such as focal lengths, principal point, and lens distortion, used to relate image pixels to camera rays. Calibration information is separate from depth measurements.
_Avoid_: Depth data

## Camera perception

**Detection**:
A result for one image that identifies an object with a class, bounding box, and confidence. A detection does not associate the object with a persistent target across frames.
_Avoid_: Track, tracked object

**Detection-annotated image**:
A camera image with object-detection results, such as bounding boxes and labels, drawn on it.

**Tracking-annotated image**:
A camera image with the selected target and tracking status drawn on it. It is a visual output of tracking, distinct from the detector's results.

**Tracking target**:
A person detection currently selected as the subject of following. It is distinct from the full set of detections and does not imply a persistent identity across frames.
_Avoid_: Detection, tracked identity

**Target range estimate**:
An estimated distance associated with the current tracking target and used by the follow behavior.
_Avoid_: Ground-truth range

## Tracking lifecycle

**Tracking bringup**:
The fixed process composition that starts the camera, decoder, detector, LiDAR, platform transform, and ObjectTrack. Runtime Follow and LiDAR fusion remain disabled until explicitly enabled through their services.

**Follow standby**:
The follow behavior is inactive while sensing, detection, and visual observation may remain available. Starting the perception pipeline does not itself activate following.

**Follow enabled**:
The follow behavior is active and evaluates the current tracking target to determine follow commands. An absent target does not disable the behavior; target selection resumes when a matching person appears.

**LiDAR fusion**:
The association of LiDAR measurements with camera detections to estimate the tracking target's range. It is distinct from the LiDAR device acquiring measurements.

## Agent actions

**Action plan**:
An ordered sequence of requested robot actions whose names and parameters
are validated together before execution. Execution can stop partway through
the plan while retaining confirmed outcomes and the unexecuted remainder.

**Action execution**:
Carrying out a requested sequence of robot actions while retaining confirmed
outcomes and the unexecuted remainder. A wait ending without confirmation does
not establish whether an action occurred.

**Action capability**:
A supported robot behavior together with the observable state associated with
that behavior. Music playback and whether music is playing belong to the same
capability.

**Action outcome**:
The recorded state of one action in a requested sequence, including an action
that was not executed or whose execution remains unconfirmed.

## Agent interaction

**Turn result**:
A snapshot of a submitted interaction's reply and action outcomes as known
when reported. Later reconciliation may produce a new result without changing
the previously reported snapshot.

## Voice input

**ASR input pause**:
Temporarily withholding real microphone audio from speech recognition while
keeping its connection alive with silence. Audio captured during the pause is
discarded, rather than submitted after listening resumes.
_Avoid_: ASR shutdown, conversation sleep
