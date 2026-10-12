"""Exercise the SDK installer through replaceable command-line adapters."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY_ROOT / "scripts" / "install-ydlidar-sdk.sh"
ENVIRONMENT_LOADER = REPOSITORY_ROOT / "scripts" / "ydlidar-sdk-env.zsh"
SDK_COMMIT = "ad8e30f9e9315d4bd7544df85571072fdbcd31ea"


FAKE_GIT = r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == clone ]]; then
    if [[ "${FAKE_GIT_FAIL:-}" == clone ]]; then
        printf 'injected clone failure\n' >&2
        exit 23
    fi
    destination="${@: -1}"
    mkdir -p "$destination"
    printf '%s\n' "${FAKE_GIT_COMMIT}" > "$destination/.fake-commit"
    printf 'clone\n' >> "$FAKE_GIT_LOG"
    exit 0
fi
if [[ "$1" == -C && "$3" == rev-parse && "$4" == HEAD ]]; then
    cat "$2/.fake-commit"
    exit 0
fi
printf 'unexpected git command: %s\n' "$*" >&2
exit 24
"""


FAKE_CMAKE = r"""#!/usr/bin/env bash
set -eu
phase=""
if [[ "$1" == -S ]]; then
    phase=configure
    build_dir=""
    install_prefix=""
    while (($#)); do
        case "$1" in
            -B)
                build_dir="$2"
                shift 2
                ;;
            -DCMAKE_INSTALL_PREFIX=*)
                install_prefix="${1#*=}"
                shift
                ;;
            *) shift ;;
        esac
    done
    mkdir -p "$build_dir"
    printf '%s\n' "$install_prefix" > "$build_dir/.install-prefix"
elif [[ "$1" == --build ]]; then
    phase=build
elif [[ "$1" == --install ]]; then
    phase=install
else
    printf 'unexpected cmake command: %s\n' "$*" >&2
    exit 31
fi

printf '%s\n' "$phase" >> "$FAKE_CMAKE_LOG"
if [[ "${FAKE_CMAKE_FAIL:-}" == "$phase" ]]; then
    printf 'injected %s failure\n' "$phase" >&2
    exit 32
fi

if [[ "$phase" == install ]]; then
    build_dir="$2"
    install_prefix="$(<"$build_dir/.install-prefix")"
    config_dir="$install_prefix/lib/cmake/ydlidar_sdk"
    mkdir -p "$config_dir" "$install_prefix/lib"
    touch "$config_dir/ydlidar_sdkConfig.cmake"
    touch "$config_dir/ydlidar_sdkConfigVersion.cmake"
    touch "$config_dir/ydlidar_sdkTargets.cmake"
    touch "$install_prefix/lib/libydlidar_sdk.so"
fi
"""


class YdLidarInstallerTests(unittest.TestCase):
    """Check install success, idempotence, and actionable failure results."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.bin_dir = self.root / "fake bin"
        self.bin_dir.mkdir()
        self._write_executable(self.bin_dir / "git", FAKE_GIT)
        self._write_executable(self.bin_dir / "cmake", FAKE_CMAKE)
        self.install_prefix = self.root / "persistent SDK prefix"
        self.temp_root = self.root / "temporary downloads"
        self.temp_root.mkdir()
        self.git_log = self.root / "git.log"
        self.cmake_log = self.root / "cmake.log"

    @staticmethod
    def _write_executable(path, contents):
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)

    def _environment(self, **updates):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.bin_dir) + os.pathsep + environment["PATH"],
                "HOME": str(self.root / "home"),
                "TMPDIR": str(self.temp_root),
                "YDLIDAR_SDK_PREFIX": str(self.install_prefix),
                "FAKE_GIT_COMMIT": SDK_COMMIT,
                "FAKE_GIT_LOG": str(self.git_log),
                "FAKE_CMAKE_LOG": str(self.cmake_log),
            }
        )
        environment.update(updates)
        return environment

    def _run_installer(self, **environment):
        return subprocess.run(
            [str(INSTALLER)],
            cwd=REPOSITORY_ROOT,
            env=self._environment(**environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_install_builds_persistent_sdk_and_repeat_uses_it(self):
        first_result = self._run_installer()

        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertIn("Installed V1.2.7", first_result.stdout)
        self.assertTrue((self.install_prefix / ".ydlidar-sdk-version").is_file())
        self.assertTrue(
            (
                self.install_prefix
                / "lib/cmake/ydlidar_sdk/ydlidar_sdkConfig.cmake"
            ).is_file()
        )
        self.assertTrue((self.install_prefix / "lib/libydlidar_sdk.so").is_file())
        self.assertEqual(self.git_log.read_text(encoding="utf-8"), "clone\n")
        self.assertEqual(
            self.cmake_log.read_text(encoding="utf-8").splitlines(),
            ["configure", "build", "install"],
        )
        self.assertEqual(list(self.temp_root.iterdir()), [])

        repeated_result = self._run_installer(FAKE_GIT_FAIL="clone")

        self.assertEqual(repeated_result.returncode, 0, repeated_result.stderr)
        self.assertIn("already installed", repeated_result.stdout)
        self.assertEqual(self.git_log.read_text(encoding="utf-8"), "clone\n")

    def test_download_failure_is_nonzero_and_actionable(self):
        result = self._run_installer(FAKE_GIT_FAIL="clone")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Download of official YDLIDAR SDK V1.2.7 failed", result.stderr)
        self.assertEqual(list(self.temp_root.iterdir()), [])

    def test_build_failure_is_nonzero_and_does_not_mark_install_complete(self):
        result = self._run_installer(FAKE_CMAKE_FAIL="build")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Build of the YDLIDAR SDK failed", result.stderr)
        self.assertFalse((self.install_prefix / ".ydlidar-sdk-version").exists())
        self.assertEqual(list(self.temp_root.iterdir()), [])

    def test_install_inside_repository_is_rejected_before_download(self):
        result = subprocess.run(
            [str(INSTALLER)],
            cwd=REPOSITORY_ROOT,
            env=self._environment(
                YDLIDAR_SDK_PREFIX=str(REPOSITORY_ROOT / "generated-sdk")
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Install prefix must be outside the repository", result.stderr)
        self.assertFalse(self.git_log.exists())
        self.assertFalse((REPOSITORY_ROOT / "generated-sdk").exists())


class YdLidarEnvironmentTests(unittest.TestCase):
    """Check that the SDK loader exports paths in the documented Zsh flow."""

    def test_zsh_source_exposes_cmake_and_runtime_paths(self):
        zsh = shutil.which("zsh")
        if zsh is None:
            self.skipTest("zsh is not installed")

        with tempfile.TemporaryDirectory() as temporary_directory:
            prefix = Path(temporary_directory) / "SDK with spaces"
            config_dir = prefix / "lib/cmake/ydlidar_sdk"
            config_dir.mkdir(parents=True)
            (config_dir / "ydlidar_sdkConfig.cmake").touch()
            library_file = prefix / "lib/libydlidar_sdk.so"
            library_file.parent.mkdir(parents=True, exist_ok=True)
            library_file.touch()

            environment = os.environ.copy()
            environment.update(
                {
                    "YDLIDAR_SDK_PREFIX": str(prefix),
                    "CMAKE_PREFIX_PATH": "/opt/ros/foxy",
                    "LD_LIBRARY_PATH": "/usr/lib",
                }
            )
            result = subprocess.run(
                [
                    zsh,
                    "-f",
                    "-c",
                    'source "$1"; print -r -- "$YDLIDAR_SDK_PREFIX"; '
                    'print -r -- "$ydlidar_sdk_DIR"; '
                    'print -r -- "$CMAKE_PREFIX_PATH"; '
                    'print -r -- "$LD_LIBRARY_PATH"',
                    "zsh",
                    str(ENVIRONMENT_LOADER),
                ],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(prefix),
                str(config_dir),
                str(prefix) + ":/opt/ros/foxy",
                str(prefix / "lib") + ":/usr/lib",
            ],
        )

    def test_cmake_finds_sdk_package_after_loading_environment(self):
        zsh = shutil.which("zsh")
        cmake = shutil.which("cmake")
        if zsh is None or cmake is None:
            self.skipTest("zsh and cmake are required for this integration check")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix = root / "SDK with spaces"
            config_dir = prefix / "lib/cmake/ydlidar_sdk"
            config_dir.mkdir(parents=True)
            (config_dir / "ydlidar_sdkConfig.cmake").write_text(
                "set(ydlidar_sdk_FOUND TRUE)\n", encoding="utf-8"
            )
            (config_dir / "ydlidar_sdkConfigVersion.cmake").write_text(
                "set(PACKAGE_VERSION \"1.2.7\")\n"
                "if(PACKAGE_FIND_VERSION VERSION_LESS_EQUAL PACKAGE_VERSION)\n"
                "  set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
                "endif()\n",
                encoding="utf-8",
            )
            library_file = prefix / "lib/libydlidar_sdk.so"
            library_file.parent.mkdir(parents=True, exist_ok=True)
            library_file.touch()
            project = root / "cmake-probe"
            project.mkdir()
            (project / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.5)\n"
                "project(ydlidar_sdk_environment_probe NONE)\n"
                "find_package(ydlidar_sdk 1.2.7 REQUIRED)\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment["YDLIDAR_SDK_PREFIX"] = str(prefix)
            result = subprocess.run(
                [
                    zsh,
                    "-f",
                    "-c",
                    'source "$1" && "$2" -S "$3" -B "$4"',
                    "zsh",
                    str(ENVIRONMENT_LOADER),
                    cmake,
                    str(project),
                    str(root / "cmake-build"),
                ],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Configuring done", result.stdout)


if __name__ == "__main__":
    unittest.main()
