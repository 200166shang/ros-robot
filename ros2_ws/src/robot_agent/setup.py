from setuptools import setup

package_name = 'robot_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot',
    maintainer_email='robot@example.com',
    description='Hardware-safe ROS 2 command agent',
    license='MIT',
    entry_points={
        'console_scripts': [
            'command_agent = robot_agent.command_agent:main',
            'llm_ros_node = robot_agent.llm_ros_node:main',
        ]
    },
)
