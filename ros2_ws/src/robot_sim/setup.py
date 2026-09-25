from setuptools import setup

package_name = 'robot_sim'

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
    description='Hardware-free robot simulation backends',
    license='MIT',
    entry_points={
        'console_scripts': [
            'base_sim_node = robot_sim.base_sim_node:main',
            'virtual_person_node = robot_sim.virtual_person_node:main',
        ],
    },
)
