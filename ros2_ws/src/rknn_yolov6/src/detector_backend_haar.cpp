#include <opencv2/imgproc.hpp>
#include <opencv2/objdetect.hpp>
#include <stdexcept>
#include <utility>

#include "detector_backend.hpp"

namespace rknn_yolov6 {
namespace detail {
namespace {

// 保存 Haar 检测框，供结果处理阶段映射为 Detection。
class HaarFrameResult final : public DetectorBackendFrameResult {
public:
    std::vector<cv::Rect> faces;
};

// 通过 OpenCV Haar 分类器实现主机侧检测后端。
class HaarDetectorBackend final : public DetectorBackend {
public:
    // 加载由 ROS 参数指定的外部 Haar 级联文件。
    explicit HaarDetectorBackend(const DetectorBackendConfig &config) {
        if (config.haar_cascade_path.empty()) {
            throw std::runtime_error("Haar backend requires haar_cascade_path");
        }
        if (!face_cascade_.load(config.haar_cascade_path)) {
            throw std::runtime_error("cannot load Haar cascade: " + config.haar_cascade_path);
        }
    }

    // 将 RGB 图像转灰度并运行 Haar 多尺度检测。
    std::unique_ptr<DetectorBackendFrameResult> infer(const cv::Mat &image) override {
        auto result = std::make_unique<HaarFrameResult>();
        cv::Mat gray;
        cv::cvtColor(image, gray, cv::COLOR_RGB2GRAY);
        face_cascade_.detectMultiScale(gray, result->faces, 1.1, 2, 0 | cv::CASCADE_SCALE_IMAGE, cv::Size(30, 30));
        return result;
    }

    // 将 Haar 人脸框映射到现有 Detection 字段语义。
    std::vector<Det> detections(DetectorBackendFrameResult &frame_result) override {
        auto *haar_result = dynamic_cast<HaarFrameResult *>(&frame_result);
        if (haar_result == nullptr) {
            throw std::runtime_error("Haar backend received an incompatible frame result");
        }

        std::vector<Det> detections;
        detections.reserve(haar_result->faces.size());
        for (const auto &face : haar_result->faces) {
            Det detection{};
            detection.x1       = static_cast<unsigned short>(face.x);
            detection.y1       = static_cast<unsigned short>(face.y);
            detection.x2       = static_cast<unsigned short>(face.x + face.width);
            detection.y2       = static_cast<unsigned short>(face.y + face.height);
            detection.conf     = 1.0F;
            detection.cls_name = "person";
            detection.cls_id   = 0;
            detection.obj_id   = 0;
            detections.push_back(std::move(detection));
        }
        return detections;
    }

private:
    cv::CascadeClassifier face_cascade_;
};

}  // namespace

// 创建 Haar adapter；该后端不使用 RKNN 的日志依赖。
std::unique_ptr<DetectorBackend> create_detector_backend(const DetectorBackendConfig &config, const rclcpp::Logger &logger, rclcpp::Clock::SharedPtr clock) {
    (void)logger;
    (void)clock;
    return std::make_unique<HaarDetectorBackend>(config);
}

}  // namespace detail
}  // namespace rknn_yolov6
