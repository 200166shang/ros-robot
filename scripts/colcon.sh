#!/usr/bin/env bash
# 保留原入口，统一交给项目解释器执行 colcon。
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_dir/dev.sh" colcon "$@"
