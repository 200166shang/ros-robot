#include <exception>
#include <memory>

#include "rknn_yolov6/rknn_yolov6_node.hpp"

// 初始化 ROS 2 并运行 YOLOv6 检测节点。
int main(int argc, char** argv) {
    // 初始化 ROS 通信环境。
    rclcpp::init(argc, argv);

    // 构造节点并进入 ROS 事件循环。
    try {
        rclcpp::spin(std::make_shared<rknn_yolov6::RknnYolov6Node>());
    } catch (const std::exception& error) {
        RCLCPP_FATAL(rclcpp::get_logger("rknn_yolov6"), "%s", error.what());
        rclcpp::shutdown();
        return 1;
    }

    // 事件循环正常结束后释放 ROS 通信资源。
    rclcpp::shutdown();
    return 0;
}
