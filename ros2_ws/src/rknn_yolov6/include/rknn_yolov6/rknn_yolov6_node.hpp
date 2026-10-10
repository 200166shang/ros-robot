#ifndef RKNN_YOLOV6__RKNN_YOLOV6_NODE_HPP_
#define RKNN_YOLOV6__RKNN_YOLOV6_NODE_HPP_

#include <memory>
#include <rclcpp/rclcpp.hpp>

namespace rknn_yolov6 {

// 提供 YOLOv6 检测器的 ROS 2 节点入口。
class RknnYolov6Node : public rclcpp::Node {
public:
    // 创建 ROS 2 检测节点及其运行实现。
    explicit RknnYolov6Node(const rclcpp::NodeOptions& options = rclcpp::NodeOptions());

    // 在 ROS 节点基类销毁前停止检测工作线程。
    ~RknnYolov6Node() override;

private:
    struct Implementation;
    std::unique_ptr<Implementation> implementation_;
};

}  // namespace rknn_yolov6

#endif  // RKNN_YOLOV6__RKNN_YOLOV6_NODE_HPP_
