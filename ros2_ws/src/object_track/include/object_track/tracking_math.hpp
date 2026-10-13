#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <vector>

namespace object_track {

// 针孔模型使用 camera optical frame：X 向右、Y 向下、Z 朝前，像素原点在图像左上角。
struct CameraProjectionModel {
    double fx{1410.6};  // 水平方向焦距，单位：像素。
    double fy{1410.6};  // 垂直方向焦距，单位：像素。
    double cx{640.0};   // 主点横坐标，单位：像素。
    double cy{360.0};   // 主点纵坐标，单位：像素。
};

// 描述 LaserScan 到相机 optical frame 的静态变换；平移单位为米，旋转矩阵按行存储。
struct LidarToCameraTransform {
    double x{0.20};
    double y{0.0};
    double z{0.0};
    std::array<double, 9> rotation{{0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 1.0, 0.0, 0.0}};
};

struct ProjectedScanPoint {
    double x{0.0};      // 投影横坐标 u，单位：像素。
    double y{0.0};      // 投影纵坐标 v，单位：像素。
    double range{0.0};  // 从相机坐标原点到点位的三维欧氏距离 sqrt(X²+Y²+Z²)，单位：米。
    double depth{0.0};  // 相机光轴方向的 Z 深度，单位：米。
};

struct LaserScanGeometry {
    double angle_min{0.0};        // 第一个量测的方向角，单位：弧度。
    double angle_increment{0.0};  // 相邻量测的角度间隔，单位：弧度。
    double range_min{0.0};        // 传感器报告的最小有效距离，单位：米。
    double range_max{0.0};        // 传感器报告的最大有效距离，单位：米。
};

struct ImageSize {
    double width{0.0};
    double height{0.0};
};

struct LinearControl {
    bool enabled{true};          // false 时始终返回零线速度。
    double gain{0.5};            // 距离误差到线速度的比例系数，单位：(m/s)/m。
    double keep_distance{0.3};   // 期望保持距离，单位：米。
    double minimum_range{0.05};  // 有效距离闭区间下界，单位：米；更近时线速度为 0。
    double maximum_range{5.0};   // 有效距离闭区间上界，单位：米；更远时线速度为 0。
    double maximum_speed{0.15};  // 线速度绝对值上限，单位：米/秒。
};

// 根据目标中心相对图像中心的像素误差计算并限幅角速度；gain 单位为 (rad/s)/pixel，结果为 rad/s。
inline double angular_command(double target_center_x, double image_width, double gain, double maximum) {
    if (image_width <= 0.0 || maximum < 0.0) return 0.0;

    // 目标在图像中心左侧时命令为正：w_raw = gain * (图像中心 x - 目标中心 x)。
    const double command = gain * (image_width * 0.5 - target_center_x);

    // 对称限幅：w = max(-maximum, min(maximum, w_raw))。
    return std::max(-maximum, std::min(maximum, command));
}

// 将有效 LaserScan 光线变换到相机坐标系，再用针孔相机模型求像素位置和三维距离。
inline std::vector<ProjectedScanPoint> project_laser_scan(const std::vector<float>& ranges,
                                                          const LaserScanGeometry& scan,
                                                          const LidarToCameraTransform& transform,
                                                          const CameraProjectionModel& camera,
                                                          const ImageSize& image_size) {
    std::vector<ProjectedScanPoint> projected;

    // 1. 相机内参、图像尺寸和静态外参必须为有限有效值，否则本次扫描无法可靠投影。
    if (camera.fx <= 0.0 || camera.fy <= 0.0 || image_size.width <= 0.0 || image_size.height <= 0.0 || !std::isfinite(camera.fx) || !std::isfinite(camera.fy) ||
        !std::isfinite(camera.cx) || !std::isfinite(camera.cy) || !std::isfinite(transform.x) || !std::isfinite(transform.y) || !std::isfinite(transform.z) ||
        !std::all_of(transform.rotation.begin(), transform.rotation.end(), [](double value) { return std::isfinite(value); })) {
        return projected;
    }

    const auto& rotation = transform.rotation;

    for (std::size_t index = 0; index < ranges.size(); ++index) {
        const double range = ranges[index];

        // 2. 只处理严格位于 LaserScan 有效区间内的有限量测，角度由首角加序号步长得到。
        if (!std::isfinite(range) || range <= scan.range_min || range >= scan.range_max) {
            continue;
        }

        const double angle = scan.angle_min + static_cast<double>(index) * scan.angle_increment;
        if (!std::isfinite(angle)) {
            continue;
        }
        const double lidar_x = range * std::cos(angle);
        const double lidar_y = range * std::sin(angle);

        // 3. 极坐标量测先转雷达平面直角坐标：(x_l,y_l,z_l)=(r cosθ,r sinθ,0)。
        //    坐标变换为 p_c=R*p_l+t：R 为 camera <- laser 的旋转矩阵，t 为平移量（米）。
        const double rotated_x = rotation[0] * lidar_x + rotation[1] * lidar_y;
        const double rotated_y = rotation[3] * lidar_x + rotation[4] * lidar_y;
        const double rotated_z = rotation[6] * lidar_x + rotation[7] * lidar_y;
        const double camera_x  = rotated_x + transform.x;
        const double camera_y  = rotated_y + transform.y;
        const double camera_z  = rotated_z + transform.z;

        // 4. 针孔投影要求点位于相机前方，即 optical frame 的 Z 必须为正。
        if (!std::isfinite(camera_x) || !std::isfinite(camera_y) || !std::isfinite(camera_z) || camera_z <= 0.0) {
            continue;
        }

        // 5. 针孔公式：u=fx*X/Z+cx，v=fy*Y/Z+cy；只保存落入图像边界的点。
        const double pixel_x = camera.fx * camera_x / camera_z + camera.cx;
        const double pixel_y = camera.fy * camera_y / camera_z + camera.cy;
        if (pixel_x < 0.0 || pixel_x >= image_size.width || pixel_y < 0.0 || pixel_y >= image_size.height) {
            continue;
        }

        // 6. range 用相机坐标系三维欧氏距离 sqrt(X²+Y²+Z²)，depth 单独保存 Z 供点半径计算。
        projected.push_back({pixel_x, pixel_y, std::sqrt(camera_x * camera_x + camera_y * camera_y + camera_z * camera_z), camera_z});
    }
    return projected;
}

// 只按水平坐标筛选目标框内的投影点，返回最近三维距离；不检查 y 以容忍路面高度抖动。
inline double nearest_range_in_horizontal_span(const std::vector<ProjectedScanPoint>& points, double left, double right) {
    double nearest = std::numeric_limits<double>::infinity();
    for (const auto& point : points) {
        // 与源节点一致，先把像素横坐标截为整数，再使用开区间 left < u < right。
        const int pixel_x = static_cast<int>(point.x);
        if (pixel_x > left && pixel_x < right && point.range < nearest) {
            nearest = point.range;
        }
    }
    return nearest;
}

// 距离位于 [minimum_range, maximum_range] 且 enabled=true 时计算 ROS 1 同款线速度，否则返回 0。
inline double linear_command(double range, const LinearControl& control) {
    if (!control.enabled || !std::isfinite(range) || range < control.minimum_range || range > control.maximum_range || control.maximum_speed < 0.0) {
        return 0.0;
    }

    // 距离有效时先算原始命令：v_raw = gain * (range - keep_distance)。
    const double command = control.gain * (range - control.keep_distance);

    // 最终线速度限制在 [-maximum_speed, +maximum_speed]。
    return std::max(-control.maximum_speed, std::min(control.maximum_speed, command));
}

}  // namespace object_track
