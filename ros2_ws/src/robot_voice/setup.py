from setuptools import setup


package_name = "robot_voice"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (
            "share/" + package_name,
            [
                "package.xml",
                "README.md",
            ],
        ),
        ("share/" + package_name + "/launch", ["launch/voice_frontend.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="robot",
    maintainer_email="robot@example.com",
    description="Decoupled half-duplex offline voice front end for the Qwen ROS text bridge.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "voice_frontend = robot_voice.voice_frontend_node:main",
        ],
    },
)
