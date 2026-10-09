# Orange Pi camera pipeline validation — 2026-10-09

Issue: [#19 Verify Orange Pi camera preview and ROS 2 pipeline rates](https://github.com/200166shang/ros-robot/issues/19)

## Environment and method

- Orange Pi 3B, AArch64 Rockchip RK356x, ROS 2 Foxy.
- Physical UVC camera: Logitech `046d:0825` on `/dev/video0`, configured for 1280×720 MJPEG and requested 30 FPS.
- Decoder scale: 0.5, producing 640×360 `rgb8` on `/camera/image_raw`.
- The rate probe subscribed with best-effort QoS to `/image_raw/compressed` and `/camera/image_raw`. Each measured window was 10 seconds after an 8-second warm-up. Camera capture and publish FPS are the `usb_camera_node` five-second statistics. Startup waits and one camera reopen were outside the measurement window.
- RViz2 used `img_decode/config/camera_preview.rviz` through the existing headless noVNC service. The preview uses a 5 FPS RViz render limit and best-effort image QoS. The GUI was stopped for rate measurements because software rendering reduces throughput on the board.

## Results

| Build configuration | Camera capture | Camera topic publish | Decoder output | Notes |
|---|---:|---:|---:|---|
| OpenCV | 29.8 FPS | 29.79 FPS | 27.69 FPS | Physical camera → OpenCV JPEG decode; RViz2/noVNC preview displayed the live image. |
| Rockchip MPP/RGA | 29.8 FPS | 29.79 FPS | 29.79 FPS | Physical camera → MPP decode/RGA scale; RViz2/noVNC preview displayed the live image. |
| MPP/RGA, `frame_divider=2` | 29.8 FPS | 14.88 FPS | 14.88 FPS | Camera output and decoder rates were half the capture rate, as configured. |

No fixed FPS threshold or ROS 1 comparison was used. The camera node logged occasional startup capture timeouts and reopened `/dev/video0`; rates were measured after the camera had produced frames and the warm-up elapsed.

## Encoder functional round trip

For each backend, a generated four-color 640×360 `rgb8` image was published to the encoder. Its `/camera/image_raw/compressed` output used `format: jpeg`, retained the input header, and was sent through the ROS 2 decoder at scale 0.5. The decoded output retained the header, measured 320×180 `rgb8`, and passed checks for all four color regions.

- OpenCV: round-trip probe passed.
- MPP/RGA: round-trip probe passed.

Encoder FPS, latency, and resource usage were not measured or included in the performance conclusion.

## Build and test evidence

- OpenCV configuration: `usb_camera`, `img_decode`, and `img_encode` built on the Orange Pi; their ROS interface and metrics tests passed (3, 3, and 1 test cases, respectively).
- MPP/RGA configuration: `img_decode` and `img_encode` built with installed Rockchip MPP/RGA libraries; their ROS tests passed (3 and 1 test cases, respectively). Runtime logs identified the Rockchip MPP/RGA backend and RGA API 1.9.3.
- RViz2: the image panel showed the physical scene from `/camera/image_raw` with Status OK. The noVNC page returned HTTP 200 on the loopback endpoint.
- `scripts/verify_image_encode_roundtrip.py` documents and checks the encoder-to-decoder ROS topic path.
