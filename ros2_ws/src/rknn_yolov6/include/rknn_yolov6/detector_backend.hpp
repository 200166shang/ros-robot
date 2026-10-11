#ifndef RKNN_YOLOV6_DETECTOR_BACKEND_HPP_
#define RKNN_YOLOV6_DETECTOR_BACKEND_HPP_

#include <memory>
#include <opencv2/core/mat.hpp>
#include <rclcpp/clock.hpp>
#include <rclcpp/logger.hpp>
#include <string>
#include <vector>

#include "rknn_yolov6/postprocess.hpp"

namespace rknn_yolov6 {
namespace detail {

// 汇总由 ROS 参数提供、供所选检测后端使用的配置。
struct DetectorBackendConfig {
    std::string model_path;             // RKNN 模型文件路径。
    std::string labels_path;            // YOLO 类别标签文件路径。
    std::string haar_cascade_path;      // Haar 级联分类器文件路径。
    float confidence_threshold{0.30F};  // YOLO 检测置信度阈值。
    float nms_threshold{0.30F};         // YOLO 非极大值抑制阈值。
    bool print_perf_detail{false};      // 是否收集并输出 RKNN 性能详情。
    bool use_multi_npu_core{false};     // 是否请求使用多个 NPU 核心。
};

// 为单帧保留跨推理与结果处理阶段的后端私有资源。
class DetectorBackendFrameResult {
public:
    // 通过虚析构函数释放具体后端拥有的帧资源。
    virtual ~DetectorBackendFrameResult() = default;
};

// 隐藏后端初始化、推理和检测结果解释的统一 seam。
// 推理与检测结果解释可能在两个 worker 上并发调用，adapter 必须支持该交错。
class DetectorBackend {
public:
    // 确保基类指针销毁时释放具体后端资源。
    virtual ~DetectorBackend() = default;

    // 在推理线程处理图像并返回可交给结果处理线程的帧状态。
    virtual std::unique_ptr<DetectorBackendFrameResult> infer(const cv::Mat &image) = 0;

    // 在结果处理线程将同一后端产生的帧状态转换为 Detection。
    virtual std::vector<Det> detections(DetectorBackendFrameResult &frame_result) = 0;
};

// 创建由构建配置选择的检测后端，并注入 ROS 日志依赖。
std::unique_ptr<DetectorBackend> create_detector_backend(const DetectorBackendConfig &config, const rclcpp::Logger &logger, rclcpp::Clock::SharedPtr clock);

}  // namespace detail
}  // namespace rknn_yolov6

#endif  // RKNN_YOLOV6_DETECTOR_BACKEND_HPP_
