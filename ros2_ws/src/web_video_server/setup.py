import os

from setuptools import setup

package_name = 'web_video_server'
static_data_files = []
for directory, _, filenames in os.walk('static'):
    files = [os.path.join(directory, name) for name in filenames]
    if files:
        relative_directory = os.path.relpath(directory, '.')
        destination = os.path.join('share', package_name, relative_directory)
        static_data_files.append((destination, files))

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/templates', ['templates/index.html']),
    ] + static_data_files,
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot',
    maintainer_email='robot@example.com',
    description='Browser MJPEG viewer for the Orange Pi ROS 2 perception pipeline',
    license='MIT',
    entry_points={'console_scripts': ['web_video_node = web_video_server.web_video_node:main']},
)
