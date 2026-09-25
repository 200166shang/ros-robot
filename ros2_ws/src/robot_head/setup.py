from setuptools import setup

package_name = 'robot_head'

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
    description='Hardware-free virtual head motion simulator for XiaoMo',
    license='MIT',
    entry_points={
        'console_scripts': [
            'robot_head_motion = robot_head.head_motion_node:main',
        ]
    },
)
