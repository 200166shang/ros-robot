# Local-only assets and provenance

Large model files, proprietary SDK headers and recordings stay on the Orange Pi but outside the public repository. `.gitignore` is a secondary guard; keeping assets outside the checkout also protects them from commands such as `git clean -fdx`.

## Vision model

| Item | Local path | Notes |
|---|---|---|
| `yolov6n_85.rknn` | `/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn` | RKNN-compiled detector model; not a Qwen model. |
| `rknn_api.h` | `/home/orangepi/sdk/rknn/include/rknn_api.h` | Rockchip header marked confidential/proprietary; do not commit or publish. |
| `librknnrt.so` | System library, currently `/lib/librknnrt.so` | Installed runtime dependency, not copied into this repository. |

Model SHA-256: `ca65d65483b6a3cf141b6c4af569f0b9140803ce834d38aa6fe044bef22020d4` (5,459,846 bytes). The same hash was observed in the source project, Orange Pi practice mirror and board workspace. The file first appears in the source repository's initial import dated 2025-10-26; that is not proof of its actual conversion date. The meaning of `_85` has not been established.

The XiaoMo ROS launch configuration uses this model. The migrated launch files accept `model_path:=...` and default to the external board path above. A fresh board must obtain the model and Rockchip SDK header from an authorized source before building/running the detector.

## Voice fixtures and model assets

- Local voice test material belongs under `/home/orangepi/local-data/ros-robot/voice-fixtures/`.
- This directory may contain a synthetic `start_person_tracking` fixture and user-provided recordings. None of those audio files belong in Git or in a public artifact.
- The synthetic sample was previously verified as mono 16 kHz PCM16 and transcribed by the board's Sherpa ASR. The demo takes its path through `input_wav_path`; tests create temporary WAV data and do not require recorded fixtures.
- Qwen GGUF and Sherpa-ONNX ASR/TTS models remain in the existing `/home/orangepi/models/qwen3/` and `/home/orangepi/models/voice/` trees. They are not copied into this repository.

## Provisioning the current board

During this migration, assets are copied (not moved) from the old workspace so that the currently running stack remains intact. After checking each copied file's checksum and validating the new checkout, the old copies can be retired separately. Do not remove the old model/header/fixture while the existing workspace is still the rollback target.
