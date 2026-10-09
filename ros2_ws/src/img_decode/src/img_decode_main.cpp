#include "img_decode/image_decode_node.hpp"

// 初始化 ROS 2 并运行 JPEG 解码节点。
int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<ImageDecodeNode>());
    rclcpp::shutdown();
    return 0;
}
