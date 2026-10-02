#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mode="format"
targets=()
for arg in "$@"; do
    case "$arg" in
        --check)
            mode="check"
            ;;
        -h|--help)
            cat <<'USAGE'
Usage: scripts/format-cpp.sh [--check] [PATH ...]

Without PATH, format all C++ source and header files in the repository.
PATH may be a directory (searched recursively) or a C++ file path.
Relative paths are resolved from the repository root; absolute paths inside
the repository are also accepted.

Examples:
  scripts/format-cpp.sh
  scripts/format-cpp.sh ros2_ws/src/monitor
  scripts/format-cpp.sh --check ros2_ws/src/monitor/src/main.cpp
USAGE
            exit 0
            ;;
        *)
            targets+=("$arg")
            ;;
    esac
done

if ! command -v clang-format >/dev/null 2>&1; then
    echo "clang-format is required but was not found in PATH" >&2
    exit 127
fi

is_cpp_file() {
    case "$1" in
        *.cc|*.cpp|*.cxx|*.c++|*.h|*.hh|*.hpp|*.hxx|*.h++|*.ipp|*.tpp|*.inl)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

resolved_targets=()
if ((${#targets[@]} == 0)); then
    resolved_targets+=("$repo_root")
else
    for target in "${targets[@]}"; do
        if [[ "$target" = /* ]]; then
            candidate="$target"
        else
            candidate="$repo_root/$target"
        fi

        if [[ ! -e "$candidate" ]]; then
            echo "Path does not exist: $target" >&2
            exit 2
        fi

        resolved="$(realpath "$candidate")"
        case "$resolved" in
            "$repo_root"|"$repo_root"/*)
                resolved_targets+=("$resolved")
                ;;
            *)
                echo "Path must be inside the repository: $target" >&2
                exit 2
                ;;
        esac
    done
fi

files=()
for target in "${resolved_targets[@]}"; do
    if [[ -f "$target" ]]; then
        if ! is_cpp_file "$target"; then
            echo "Not a supported C++ source/header file: $target" >&2
            exit 2
        fi
        files+=("$target")
    elif [[ -d "$target" ]]; then
        while IFS= read -r -d '' file; do
            files+=("$file")
        done < <(
            find "$target" \
                -type d \( -name .git -o -name build -o -name install -o -name log \
                    -o -name __pycache__ -o -name node_modules \) -prune -o \
                -type f \( -name '*.cc' -o -name '*.cpp' -o -name '*.cxx' -o -name '*.c++' \
                    -o -name '*.h' -o -name '*.hh' -o -name '*.hpp' -o -name '*.hxx' \
                    -o -name '*.h++' -o -name '*.ipp' -o -name '*.tpp' -o -name '*.inl' \) \
                -print0
        )
    fi
done

if ((${#files[@]} == 0)); then
    echo "No C++ source/header files found" >&2
    exit 1
fi

mapfile -d '' files < <(printf '%s\0' "${files[@]}" | sort -zu)

if [[ "$mode" == "check" ]]; then
    clang-format --style=file --dry-run --Werror "${files[@]}"
else
    clang-format --style=file -i "${files[@]}"
fi
