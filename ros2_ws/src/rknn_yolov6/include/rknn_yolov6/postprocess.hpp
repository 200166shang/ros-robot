#ifndef RKNN_YOLOV6_POSTPROCESS_HPP_
#define RKNN_YOLOV6_POSTPROCESS_HPP_

#include <array>
#include <string>
#include <vector>

namespace rknn_yolov6 {

// 表示后处理模块输出的检测框及其类别信息。
struct Det {
    unsigned short x1{0};
    unsigned short y1{0};
    unsigned short x2{0};
    unsigned short y2{0};
    float conf{0.0F};
    std::string cls_name;
    unsigned short cls_id{0};
    unsigned short obj_id{0};
};

// 保存模型和检测器的固定配置，由后处理模块在整个生命周期内持有。
struct YoloV6PostprocessorConfig {
    int model_width{0};
    int model_height{0};
    float confidence_threshold{0.30F};
    float nms_threshold{0.30F};
    std::vector<std::string> labels;
};

// 借用当前帧三个浮点输出头和原图尺寸；模块只在 process 调用期间读取这些指针。
struct YoloV6FrameOutputs {
    std::array<const float *, 3> heads{{nullptr, nullptr, nullptr}};
    int source_width{0};
    int source_height{0};
};

// 持有 YOLOv6 解码配置，并将三个浮点输出头转换为检测结果。
class YoloV6Postprocessor final {
public:
    // 校验并保存模型尺寸、阈值和类别标签。
    explicit YoloV6Postprocessor(YoloV6PostprocessorConfig config);

    // 同步解码当前帧的借用张量，并返回映射到原图尺寸的检测框。
    std::vector<Det> process(const YoloV6FrameOutputs &outputs) const;

private:
    const int model_width_;
    const int model_height_;
    const float confidence_threshold_;
    const float nms_threshold_;
    const std::vector<std::string> labels_;
};

}  // namespace rknn_yolov6

#endif  // RKNN_YOLOV6_POSTPROCESS_HPP_
