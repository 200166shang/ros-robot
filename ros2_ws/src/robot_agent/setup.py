"""robot_agent 包安装配置与在线入口声明。"""

from setuptools import find_packages, setup

package_name = "robot_agent"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(include=[package_name, package_name + ".*"]),
    package_data={
        package_name + ".conversation": ["online_system_prompt.txt"]
    },
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=[
        "setuptools",
        "websocket-client>=1.6,<2",
        "websockets==13.1",
        "pydantic==2.10.6",
        "httpx==0.28.1",
        "typing-extensions==4.13.2",
    ],
    zip_safe=True,
    maintainer="robot",
    maintainer_email="robot@example.com",
    description="Online microphone Agent and independent WAV tests",
    license="MIT",
    entry_points={
        "console_scripts": [
            "online_voice_agent = robot_agent.ros.voice_node:main",
            "online_voice_wav = robot_agent.voice.runtime:main",
        ]
    },
)
