from glob import glob
import os

from setuptools import find_packages, setup

package_name = "robot_nav2_gateway"
share_dir = os.path.join("share", package_name)

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (share_dir, ["package.xml"]),
        (os.path.join(share_dir, "launch"), glob("launch/*.launch.py")),
        (os.path.join(share_dir, "config"), glob("config/*")),
        (os.path.join(share_dir, "web"), glob("web/*")),
    ],
    install_requires=[],
    zip_safe=True,
    maintainer="ros-robot maintainers",
    maintainer_email="robot@example.invalid",
    description="Isolated Nav2 loopback gateway and local web UI.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "nav2_http_gateway = robot_nav2_gateway.gateway:main",
        ],
    },
)
