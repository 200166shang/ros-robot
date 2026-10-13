#!/usr/bin/env bash
set -Eeuo pipefail

readonly SDK_VERSION="1.2.7"
readonly SDK_TAG="V1.2.7"
readonly SDK_COMMIT="ad8e30f9e9315d4bd7544df85571072fdbcd31ea"
readonly SDK_REPOSITORY="https://github.com/YDLIDAR/YDLidar-SDK.git"

fail() {
    printf '[ydlidar-sdk] ERROR: %s\n' "$*" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"

if [[ -z "${HOME:-}" && -z "${YDLIDAR_SDK_PREFIX:-}" ]]; then
    fail 'HOME is unset; set YDLIDAR_SDK_PREFIX to a persistent install path.'
fi

default_prefix="${HOME:-}/.local/opt/ydlidar-sdk/${SDK_VERSION}"
prefix="${YDLIDAR_SDK_PREFIX:-$default_prefix}"
if ! prefix="$(realpath -m -- "$prefix")"; then
    fail "Cannot resolve install prefix: $prefix"
fi

if [[ "$prefix" == "$repo_root" || "$prefix" == "$repo_root/"* ]]; then
    fail "Install prefix must be outside the repository: $prefix"
fi

config_dir="$prefix/lib/cmake/ydlidar_sdk"
config_file="$config_dir/ydlidar_sdkConfig.cmake"
version_file="$config_dir/ydlidar_sdkConfigVersion.cmake"
library_file="$prefix/lib/libydlidar_sdk.so"
version_marker="$prefix/.ydlidar-sdk-version"
expected_marker="$SDK_TAG $SDK_COMMIT"

if [[ -f "$version_marker" && -f "$config_file" && -f "$version_file" && -f "$library_file" ]]; then
    if [[ "$(<"$version_marker")" == "$expected_marker" ]]; then
        printf '[ydlidar-sdk] %s is already installed at %s\n' "$SDK_TAG" "$prefix"
        exit 0
    fi
fi

if ! mkdir -p -- "$(dirname -- "$prefix")"; then
    fail "Cannot create parent directory for install prefix: $prefix"
fi

temporary_root="${TMPDIR:-/tmp}"
if ! temporary_root="$(realpath -m -- "$temporary_root")"; then
    fail "Cannot resolve temporary directory: ${TMPDIR:-/tmp}"
fi
if [[ "$temporary_root" == "$repo_root" || "$temporary_root" == "$repo_root/"* ]]; then
    fail "Temporary directory must be outside the repository: $temporary_root"
fi

build_jobs="${YDLIDAR_SDK_BUILD_JOBS:-2}"
if [[ ! "$build_jobs" =~ ^[1-9][0-9]*$ ]]; then
    fail "YDLIDAR_SDK_BUILD_JOBS must be a positive integer: $build_jobs"
fi

if ! work_dir="$(mktemp -d "$temporary_root/ydlidar-sdk.XXXXXX")"; then
    fail "Cannot create temporary build directory under $temporary_root"
fi
trap 'rm -rf -- "$work_dir"' EXIT

source_dir="$work_dir/source"
build_dir="$work_dir/build"

if ! git clone --depth 1 --branch "$SDK_TAG" "$SDK_REPOSITORY" "$source_dir"; then
    fail "Download of official YDLIDAR SDK $SDK_TAG failed."
fi

if ! actual_commit="$(git -C "$source_dir" rev-parse HEAD)"; then
    fail 'Cannot read the downloaded YDLIDAR SDK commit.'
fi
if [[ "$actual_commit" != "$SDK_COMMIT" ]]; then
    fail "YDLIDAR SDK $SDK_TAG resolved to $actual_commit, expected $SDK_COMMIT."
fi

if ! cmake -S "$source_dir" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$prefix" \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_TEST=OFF; then
    fail 'CMake configuration of the YDLIDAR SDK failed.'
fi

if ! cmake --build "$build_dir" --parallel "$build_jobs"; then
    fail 'Build of the YDLIDAR SDK failed.'
fi

if ! cmake --install "$build_dir"; then
    fail "Install of the YDLIDAR SDK into $prefix failed."
fi

if [[ ! -f "$config_file" || ! -f "$version_file" ]]; then
    fail "SDK install completed without the expected CMake package files under $config_dir"
fi
if [[ ! -f "$library_file" ]]; then
    fail "SDK install completed without the expected shared library: $library_file"
fi

if ! printf '%s\n' "$expected_marker" > "$version_marker.tmp.$$"; then
    fail "Cannot write SDK version marker in $prefix"
fi
if ! mv -f -- "$version_marker.tmp.$$" "$version_marker"; then
    fail "Cannot finalize SDK version marker in $prefix"
fi

printf '[ydlidar-sdk] Installed %s at %s\n' "$SDK_TAG" "$prefix"
printf '[ydlidar-sdk] Source and build files will be removed from %s\n' "$work_dir"
