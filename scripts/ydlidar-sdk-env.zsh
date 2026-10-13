# Source this file from the current Bash or Zsh session after installing the SDK.
if [[ -z "${HOME:-}" && -z "${YDLIDAR_SDK_PREFIX:-}" ]]; then
    printf '[ydlidar-sdk] ERROR: HOME is unset; set YDLIDAR_SDK_PREFIX first.\n' >&2
    return 1
fi

YDLIDAR_SDK_PREFIX="${YDLIDAR_SDK_PREFIX:-${HOME}/.local/opt/ydlidar-sdk/1.2.7}"
ydlidar_sdk_config_dir="$YDLIDAR_SDK_PREFIX/lib/cmake/ydlidar_sdk"
ydlidar_sdk_config_file="$ydlidar_sdk_config_dir/ydlidar_sdkConfig.cmake"
ydlidar_sdk_library_file="$YDLIDAR_SDK_PREFIX/lib/libydlidar_sdk.so"

if [[ ! -f "$ydlidar_sdk_config_file" ]]; then
    printf '[ydlidar-sdk] ERROR: CMake package not found: %s\n' "$ydlidar_sdk_config_file" >&2
    printf '[ydlidar-sdk] Run scripts/install-ydlidar-sdk.sh first.\n' >&2
    return 1
fi
if [[ ! -f "$ydlidar_sdk_library_file" ]]; then
    printf '[ydlidar-sdk] ERROR: shared library not found: %s\n' "$ydlidar_sdk_library_file" >&2
    printf '[ydlidar-sdk] Run scripts/install-ydlidar-sdk.sh to repair the install.\n' >&2
    return 1
fi

export YDLIDAR_SDK_PREFIX
export ydlidar_sdk_DIR="$ydlidar_sdk_config_dir"
export CMAKE_PREFIX_PATH="$YDLIDAR_SDK_PREFIX${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
export LIBRARY_PATH="$YDLIDAR_SDK_PREFIX/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$YDLIDAR_SDK_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

unset ydlidar_sdk_config_dir ydlidar_sdk_config_file ydlidar_sdk_library_file
