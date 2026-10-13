#include <cassert>
#include <cmath>
#include <limits>
#include <vector>

#include "object_track/tracking_math.hpp"

// 验证默认外参下 r=0.5 m 的中心光线变为相机点 (0.2,0,0.5)，并满足针孔投影公式。
void test_scan_projection() {
    const object_track::CameraProjectionModel camera;
    const object_track::LidarToCameraTransform transform;
    const object_track::LaserScanGeometry scan{0.0, 0.0, 0.1, 10.0};
    const object_track::ImageSize image{1280.0, 720.0};
    const std::vector<float> ranges{0.5F, std::numeric_limits<float>::infinity(), 0.05F, 10.0F};
    const auto points = object_track::project_laser_scan(ranges, scan, transform, camera, image);

    assert(points.size() == 1U);
    assert(std::abs(points.front().x - 1204.24) < 0.1);
    assert(std::abs(points.front().y - 360.0) < 0.1);
    assert(std::abs(points.front().range - std::sqrt(0.29)) < 1e-6);
}

// 验证平台四元数 (0.5,-0.5,0.5,0.5) 的旋转矩阵保留整条水平扫描线，而非退化为中心射线。
void test_platform_rotation_projection() {
    object_track::LidarToCameraTransform transform;
    transform.rotation = {{0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 1.0, 0.0, 0.0}};
    const object_track::LaserScanGeometry scan{0.0, 0.26, 0.1, 10.0};
    const std::vector<float> ranges{0.5F, std::numeric_limits<float>::infinity(), 0.5F, 0.5F};
    const auto points = object_track::project_laser_scan(ranges, scan, transform, {}, {1280.0, 720.0});

    assert(points.size() == 3U);
    assert(std::abs(points[1].x - 482.52581) < 1e-4);
    assert(std::abs(points[1].y - 360.0) < 1e-4);
    assert(std::abs(points[1].range - 0.436605053) < 1e-8);
    assert(std::abs(points[2].x - 38.23069) < 1e-4);
    assert(std::abs(points[2].y - 360.0) < 1e-4);
}

// 验证目标按开区间水平跨度选最近三维距离，边界像素不计入且不检查垂直坐标。
void test_nearest_range_in_horizontal_span() {
    const std::vector<object_track::ProjectedScanPoint> points{
        {300.0, 360.0, 0.7}, {800.0, 360.0, 0.1}, {900.0, 120.0, 1.4}, {1000.0, 600.0, 0.5}, {1100.0, 360.0, 0.2}};

    assert(std::abs(object_track::nearest_range_in_horizontal_span(points, 800.0, 1100.0) - 0.5) < 1e-9);
    assert(std::isinf(object_track::nearest_range_in_horizontal_span(points, 400.0, 700.0)));
}

// 验证 v=0.5*(range-0.3) 的距离控制公式、±0.15 m/s 限幅和禁用条件。
void test_linear_command() {
    const object_track::LinearControl control;
    assert(std::abs(object_track::linear_command(std::sqrt(0.29), control) - 0.1192582403567252) < 1e-9);
    assert(object_track::linear_command(2.0, control) == 0.15);
    assert(object_track::linear_command(5.1, control) == 0.0);

    object_track::LinearControl disabled = control;
    disabled.enabled                     = false;
    assert(object_track::linear_command(1.0, disabled) == 0.0);
}

// 运行 LiDAR 投影、目标距离和线速度数学用例。
int main() {
    test_scan_projection();
    test_platform_rotation_projection();
    test_nearest_range_in_horizontal_span();
    test_linear_command();
    return 0;
}
