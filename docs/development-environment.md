# Orange Pi development environment

The project uses one root `.venv`, created from `/usr/bin/python3` with system
site packages visible. This keeps the Python 3.8 ABI required by ROS 2 Foxy and
OpenCV. `uv.lock` reproduces project-installed Python dependencies on this
Orange Pi ARM64 board. Colcon builds and installs every ROS source package;
uv does not install the repository itself or its ROS packages.

## Install and synchronize

Install the pinned uv release once, then explicitly synchronize the lockfile:

```bash
curl -LsSf https://astral.sh/uv/0.8.22/install.sh -o /tmp/install-uv.sh
sh /tmp/install-uv.sh
export PATH="$HOME/.local/bin:$PATH"
./scripts/dev.sh sync
```

`sync` creates `.venv` with `--python /usr/bin/python3
--system-site-packages --no-python-downloads`, then runs `uv sync --locked`.
It needs network access when artifacts are not cached. Keep using the wrapper
when recreating the environment: plain `uv sync` creates an environment without
system site packages. Remove an obsolete `.venv` before recreating it, and
rebuild the workspace after changing the interpreter or repository location.

Runtime dependencies are Flask, websocket-client, and sherpa-onnx-bin. The
latter pulls in the matching sherpa-onnx-core dynamic libraries. The Python
`sherpa-onnx` wrapper alone does not provide the required native executables.
The lock contains the PyPI ARM64 manylinux2014 wheels for version 1.13.8,
including their SHA-256 hashes:

| Artifact | SHA-256 |
| --- | --- |
| sherpa_onnx_bin-1.13.8-py3-none-manylinux2014_aarch64.whl | `7529a3d1f7f1e9313a230238b2104cfb3648dec53612611513b9929d8810e510` |
| sherpa_onnx_core-1.13.8-py3-none-manylinux2014_aarch64.whl | `a51a03d55c376c32e15dd63ea852236042ba91a5cd73e253bbf7cf21f6582ba9` |

These executables continue to run as child processes. Put speech models and
recordings outside the repository; syncing dependencies downloads no models.
The [PyPI release files](https://pypi.org/project/sherpa-onnx-bin/1.13.8/#files)
provide the reproducible artifact source.

Development tools are pinned too. Pytest 7.4.4 works with this board's Foxy
launch-testing plugin; pytest 8.3.5 fails in that plugin's `import_path` call.
Setuptools 68.2.2 retains the editable installation commands used by colcon.
Ruff retains the existing Python 3.8 rule configuration and source scope.

## Build, check, and run

Run commands from the repository root; the wrappers load ROS Foxy and the
current workspace and put `.venv/bin` first on PATH. Environment activation
alone cannot change system-Python shebangs in `colcon` or `ros2`. The wrapper
uses `python -m colcon` and invokes the ROS CLI script with the project Python.
Its `build` command also supplies both CMake Python executable variables so
ament-generated Python interfaces use the same interpreter.

```bash
# Full board build, using the existing external Rockchip header and YDLIDAR SDK.
./scripts/dev.sh build --executor sequential --cmake-args \
  -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
./scripts/dev.sh lint
./scripts/dev.sh test -q tests ros2_ws/src
./scripts/dev.sh test-ros --executor sequential
./scripts/dev.sh test-result --verbose
./scripts/dev.sh verify

# Focused development commands.
./scripts/dev.sh format path/to/changed.py
./scripts/dev.sh test -q ros2_ws/src/robot_agent/test
./scripts/dev.sh python -c 'import rclpy, cv2, websocket'
./scripts/dev.sh ros run robot_agent online_voice_wav --help
./scripts/dev.sh colcon list --names-only
```

`build` enables symlink installation and forwards package/backend arguments.
Do not override `PYTHON_EXECUTABLE` or `Python3_EXECUTABLE`. The existing
`colcon.sh`, `run-demo.sh`, and `run-tracking.sh` entries share this environment.
Only `sync` installs dependencies; ordinary commands neither synchronize nor
change the lockfile. Missing environments report `./scripts/dev.sh sync`.
`test-ros` explicitly selects pytest so colcon includes function-style Python
tests as well as unittest cases. `lint` checks formatting and Ruff rules;
`format` applies formatting. C++
formatting still uses `scripts/format-cpp.sh`.

`verify` imports system ROS/OpenCV and project web/speech dependencies, loads
all Agent, web, and offline voice console targets without invoking nodes,
checks installed shebangs, runs the installed WAV entry with `--help`, and
runs sherpa version/help commands. It opens no camera, microphone, LiDAR, or
motor, makes no model request, and requires no model assets. The command tests
rebuild the Python ROS packages. The fresh-environment installation acceptance
test is opt-in, so ordinary tests do not download or install dependencies:

```bash
ROBOT_TEST_DEPENDENCY_INSTALL=1 ./scripts/dev.sh test -q \
  tests/test_dev_commands.py -k sync_creates
```

This explicitly runs `sync` in a temporary project using the committed lock.
Test commands default to ROS domain 174 and localhost-only DDS to isolate
fixture services from the robot's normal domain; explicit environment values
can override these defaults. ROS tests use fixtures; inference tests needing
external model/image assets remain skipped when those assets are absent.

For intentional dependency updates, edit `pyproject.toml`, run the pinned
`uv lock --python /usr/bin/python3 --no-python-downloads`, review and commit
both declaration and lockfile, then run `./scripts/dev.sh sync`. See
[uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/).

## System dependency baseline

The lockfile covers installed project Python wheels. The following are
intentionally supplied by the current board's operating system, ROS install,
and external SDK directories; they are not reproduced by uv.

| Dependency | Verified board baseline |
| --- | --- |
| Platform | Orange Pi 3B, aarch64, Ubuntu 20.04 (Orange Pi 1.0.8 Focal), glibc 2.31 |
| Python | `/usr/bin/python3`, CPython 3.8.10 |
| ROS | Foxy in `/opt/ros/foxy`; rclpy 1.0.13, ament_cmake 0.9.12, launch_testing 0.10.10 |
| Build tools | CMake 3.16.3, GCC/G++ 9.4.0 |
| Colcon | python3-colcon-core 0.21.3+upstream-1; colcon-cmake 0.2.30; python-setup-py 0.2.9; common-extensions 0.3.0 |
| System Python extensions | OpenCV 4.2.0, NumPy 1.17.4, cv_bridge 3.0.7 |
| Audio runtime | alsa-utils 1.2.2, libasound2 1.2.2; devices are needed only for actual recording/playback |
| Perception SDKs | Installed MPP and RGA libraries/headers; `/usr/lib/librknnrt.so`; RKNN header in `/home/orangepi/sdk/rknn/include` |
| LiDAR SDK | YDLIDAR SDK 1.2.7 under `$HOME/.local/opt/ydlidar-sdk/1.2.7`, prepared by `scripts/install-ydlidar-sdk.sh` |

ROS message, service, launch, test, and C++ development packages remain owned
by the Foxy installation. Inspect their exact installed Debian revisions with
`dpkg-query -W 'ros-foxy-*' 'python3-colcon-*' python3-opencv python3-numpy`.
Source packages under `ros2_ws/src` remain colcon-owned even when Python wheels
with similar names exist. Model files, SDK headers, credentials, `.venv`, and
`ros2_ws/{build,install,log}` stay outside source commits. Tracking remains in
its existing dry-run configuration.
