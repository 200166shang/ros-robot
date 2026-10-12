#include <cassert>
#include <cmath>
#include <limits>
#include <vector>

#include "object_track/tracking_math.hpp"

// 验证固定外参将中心 scan 点投影到相机图像中的预期像素。
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

// 验证目标仅按水平框跨度选取最近有效三维距离。
void test_nearest_range_in_horizontal_span() {
    const std::vector<object_track::ProjectedScanPoint> points{
        {300.0, 360.0, 0.7}, {800.0, 360.0, 0.1}, {900.0, 120.0, 1.4}, {1000.0, 600.0, 0.5}, {1100.0, 360.0, 0.2}};

    assert(std::abs(object_track::nearest_range_in_horizontal_span(points, 800.0, 1100.0) - 0.5) < 1e-9);
    assert(std::isinf(object_track::nearest_range_in_horizontal_span(points, 400.0, 700.0)));
}

// 验证 ROS 1 距离比例命令、速度限幅和禁用条件。
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
    test_nearest_range_in_horizontal_span();
    test_linear_command();
    return 0;
}
