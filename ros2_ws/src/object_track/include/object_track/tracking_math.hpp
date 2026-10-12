#pragma once

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

namespace object_track {

struct CameraProjectionModel {
    double fx{1410.6};
    double fy{1410.6};
    double cx{640.0};
    double cy{360.0};
};

// 参数描述 LaserScan 坐标系到相机 optical frame 的静态变换。
struct LidarToCameraTransform {
    double x{0.20};
    double y{0.0};
    double z{0.0};
    double roll{1.5707963267948966};
    double pitch{-1.5707963267948966};
    double yaw{0.0};
};

struct ProjectedScanPoint {
    double x{0.0};
    double y{0.0};
    double range{0.0};
};

struct LaserScanGeometry {
    double angle_min{0.0};
    double angle_increment{0.0};
    double range_min{0.0};
    double range_max{0.0};
};

struct ImageSize {
    double width{0.0};
    double height{0.0};
};

struct LinearControl {
    bool enabled{true};
    double gain{0.5};
    double keep_distance{0.3};
    double minimum_range{0.05};
    double maximum_range{5.0};
    double maximum_speed{0.15};
};

// 根据目标中心相对图像中心的位置计算限幅角速度。
inline double angular_command(double target_center_x, double image_width, double gain, double maximum) {
    if (image_width <= 0.0 || maximum < 0.0) return 0.0;
    const double command = gain * (image_width * 0.5 - target_center_x);
    return std::max(-maximum, std::min(maximum, command));
}

// 将有效 LaserScan 光线经固定外参变换并投影到相机图像坐标。
inline std::vector<ProjectedScanPoint> project_laser_scan(const std::vector<float>& ranges,
                                                          const LaserScanGeometry& scan,
                                                          const LidarToCameraTransform& transform,
                                                          const CameraProjectionModel& camera,
                                                          const ImageSize& image_size) {
    std::vector<ProjectedScanPoint> projected;
    if (camera.fx <= 0.0 || camera.fy <= 0.0 || image_size.width <= 0.0 || image_size.height <= 0.0 || !std::isfinite(camera.fx) || !std::isfinite(camera.fy) ||
        !std::isfinite(camera.cx) || !std::isfinite(camera.cy) || !std::isfinite(transform.x) || !std::isfinite(transform.y) || !std::isfinite(transform.z) ||
        !std::isfinite(transform.roll) || !std::isfinite(transform.pitch) || !std::isfinite(transform.yaw)) {
        return projected;
    }

    const double cr = std::cos(transform.roll);
    const double sr = std::sin(transform.roll);
    const double cp = std::cos(transform.pitch);
    const double sp = std::sin(transform.pitch);
    const double cy = std::cos(transform.yaw);
    const double sy = std::sin(transform.yaw);

    for (std::size_t index = 0; index < ranges.size(); ++index) {
        const double range = ranges[index];
        if (!std::isfinite(range) || range < scan.range_min || range > scan.range_max) {
            continue;
        }

        const double angle = scan.angle_min + static_cast<double>(index) * scan.angle_increment;
        if (!std::isfinite(angle)) {
            continue;
        }
        const double lidar_x = range * std::cos(angle);
        const double lidar_y = range * std::sin(angle);

        // Apply Rz(yaw) * Ry(pitch) * Rx(roll) to the planar scan point.
        const double rotated_x = cy * cp * lidar_x + (cy * sp * sr - sy * cr) * lidar_y;
        const double rotated_y = sy * cp * lidar_x + (sy * sp * sr + cy * cr) * lidar_y;
        const double rotated_z = -sp * lidar_x + cp * sr * lidar_y;
        const double camera_x  = rotated_x + transform.x;
        const double camera_y  = rotated_y + transform.y;
        const double camera_z  = rotated_z + transform.z;
        if (!std::isfinite(camera_x) || !std::isfinite(camera_y) || !std::isfinite(camera_z) || camera_z <= 0.0) {
            continue;
        }

        const double pixel_x = camera.fx * camera_x / camera_z + camera.cx;
        const double pixel_y = camera.fy * camera_y / camera_z + camera.cy;
        if (pixel_x < 0.0 || pixel_x >= image_size.width || pixel_y < 0.0 || pixel_y >= image_size.height) {
            continue;
        }

        projected.push_back({pixel_x, pixel_y, std::sqrt(camera_x * camera_x + camera_y * camera_y + camera_z * camera_z)});
    }
    return projected;
}

// 保留投影横坐标落在目标框内的最近 3D 距离。
inline double nearest_range_in_horizontal_span(const std::vector<ProjectedScanPoint>& points, double left, double right) {
    double nearest = std::numeric_limits<double>::infinity();
    for (const auto& point : points) {
        if (point.x >= left && point.x <= right && point.range < nearest) {
            nearest = point.range;
        }
    }
    return nearest;
}

// 将有效目标距离转换为 ROS 1 同款、限幅后的线速度。
inline double linear_command(double range, const LinearControl& control) {
    if (!control.enabled || !std::isfinite(range) || range < control.minimum_range || range > control.maximum_range || control.maximum_speed < 0.0) {
        return 0.0;
    }
    const double command = control.gain * (range - control.keep_distance);
    return std::max(-control.maximum_speed, std::min(control.maximum_speed, command));
}

}  // namespace object_track
