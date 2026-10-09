#include <exception>
#include <memory>

#include "img_encode/image_encode_node.hpp"

// ROS 2 入口负责初始化、中止异常处理和节点生命周期。
int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    try {
        rclcpp::spin(std::make_shared<img_encode::ImageEncodeNode>());
    } catch (const std::exception& exception) {
        RCLCPP_FATAL(rclcpp::get_logger("img_encode"), "encoder startup failed: %s", exception.what());
        rclcpp::shutdown();
        return 1;
    }
    rclcpp::shutdown();
    return 0;
}
