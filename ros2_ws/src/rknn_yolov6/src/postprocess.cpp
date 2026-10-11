#include "rknn_yolov6/postprocess.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace rknn_yolov6 {
namespace {

// 将坐标限制在模型输入图像的有效像素范围内。
inline int clamp(float value, int minimum, int maximum) { return value > minimum ? (value < maximum ? value : maximum) : minimum; }

// 根据两个检测框坐标计算交并比。
float CalculateOverlap(float xmin0, float ymin0, float xmax0, float ymax0, float xmin1, float ymin1, float xmax1, float ymax1) {
    const float width        = std::fmax(0.0F, std::fmin(xmax0, xmax1) - std::fmax(xmin0, xmin1) + 1.0);
    const float height       = std::fmax(0.0F, std::fmin(ymax0, ymax1) - std::fmax(ymin0, ymin1) + 1.0);
    const float intersection = width * height;
    const float union_area   = (xmax0 - xmin0 + 1.0) * (ymax0 - ymin0 + 1.0) + (xmax1 - xmin1 + 1.0) * (ymax1 - ymin1 + 1.0) - intersection;
    return union_area <= 0.0F ? 0.0F : intersection / union_area;
}

// 按交并比阈值抑制重叠检测框。
void nms(int valid_count, const std::vector<float> &locations, std::vector<int> &order, float threshold) {
    for (int i = 0; i < valid_count; ++i) {
        if (order[i] == -1) {
            continue;
        }
        const int current = order[i];
        for (int j = i + 1; j < valid_count; ++j) {
            const int candidate = order[j];
            if (candidate == -1) {
                continue;
            }

            const float xmin0 = locations[current * 4];
            const float ymin0 = locations[current * 4 + 1];
            const float xmax0 = xmin0 + locations[current * 4 + 2];
            const float ymax0 = ymin0 + locations[current * 4 + 3];
            const float xmin1 = locations[candidate * 4];
            const float ymin1 = locations[candidate * 4 + 1];
            const float xmax1 = xmin1 + locations[candidate * 4 + 2];
            const float ymax1 = ymin1 + locations[candidate * 4 + 3];

            if (CalculateOverlap(xmin0, ymin0, xmax0, ymax0, xmin1, ymin1, xmax1, ymax1) > threshold) {
                order[j] = -1;
            }
        }
    }
}

// 按置信度降序排列分数，同时同步排列原始检测索引。
void quick_sort_indice_inverse(std::vector<float> &scores, int left, int right, std::vector<int> &indices) {
    int low  = left;
    int high = right;
    if (left >= right) {
        return;
    }

    const int key_index = indices[left];
    const float key     = scores[left];
    while (low < high) {
        while (low < high && scores[high] <= key) {
            --high;
        }
        scores[low]  = scores[high];
        indices[low] = indices[high];
        while (low < high && scores[low] >= key) {
            ++low;
        }
        scores[high]  = scores[low];
        indices[high] = indices[low];
    }
    scores[low]  = key;
    indices[low] = key_index;

    quick_sort_indice_inverse(scores, left, low - 1, indices);
    quick_sort_indice_inverse(scores, low + 1, right, indices);
}

// 解码单个浮点检测头并收集通过阈值筛选的检测框。
int process_float(const float *input,
                  int grid_height,
                  int grid_width,
                  int stride,
                  std::vector<float> &boxes,
                  std::vector<float> &scores,
                  std::vector<int> &class_ids,
                  float threshold,
                  int class_count) {
    // input 指向当前一个检测头 buffer 的起始位置；数据按 [通道][网格位置] 连续排列。
    int valid_count = 0;
    // 一个通道平面包含所有网格位置，因此跨通道时要偏移整个网格的 float 元素数量。
    const int grid_length = grid_height * grid_width;

    for (int row = 0; row < grid_height; ++row) {
        for (int column = 0; column < grid_width; ++column) {
            // 当前网格位置在每个通道平面中的索引都相同。
            const int cell_index = row * grid_width + column;

            // 通道 4 是目标置信度；低于阈值时跳过这个网格位置。
            if (input[4 * grid_length + cell_index] < threshold) {
                continue;
            }

            // cell 指向通道 0 下的当前位置；cell[k * grid_length] 是通道 k 下同一位置的值。
            const float *cell = input + cell_index;
            // 通道 5 起是各类别分数；选择最高分和对应的类别编号。
            float best_class_score = cell[5 * grid_length];
            int best_class_id      = 0;
            for (int class_index = 1; class_index < class_count; ++class_index) {
                const float class_score = cell[(5 + class_index) * grid_length];
                if (class_score > best_class_score) {
                    best_class_id    = class_index;
                    best_class_score = class_score;
                }
            }

            if (best_class_score >= threshold) {
                // 最高类别分也要达到阈值；通道 0–3 是网格中心到 left、top、right、bottom 边界的距离。
                // row 和 column 从网格左上角起按 0 计数，+0.5 表示移动到当前网格单元的中心。
                const float x1 = column + 0.5 - cell[0 * grid_length];
                const float y1 = row + 0.5 - cell[1 * grid_length];
                const float x2 = column + 0.5 + cell[2 * grid_length];
                const float y2 = row + 0.5 + cell[3 * grid_length];

                // x1/y1 是框左上角，x2/y2 是右下角；当前坐标仍以网格为单位。
                // 按 x、y、宽、高及其类别信息保存候选框，留给外层排序和 NMS。
                scores.push_back(best_class_score);
                class_ids.push_back(best_class_id);
                // 乘 stride 将网格坐标换算成模型输入像素坐标。
                boxes.push_back(x1 * stride);
                boxes.push_back(y1 * stride);
                boxes.push_back((x2 - x1) * stride);
                boxes.push_back((y2 - y1) * stride);
                ++valid_count;
            }
        }
    }

    return valid_count;
}

}  // namespace

// 校验并保存 YOLOv6 后处理所需的固定配置。
YoloV6Postprocessor::YoloV6Postprocessor(YoloV6PostprocessorConfig config)
    : model_width_(config.model_width),
      model_height_(config.model_height),
      confidence_threshold_(config.confidence_threshold),
      nms_threshold_(config.nms_threshold),
      labels_(std::move(config.labels)) {
    if (model_width_ <= 0 || model_height_ <= 0) {
        throw std::invalid_argument("YOLOv6 model dimensions must be positive");
    }
    if (labels_.empty()) {
        throw std::invalid_argument("YOLOv6 postprocessor requires at least one class label");
    }
}

// 解码三个输出尺度，排序并执行 NMS 后映射到原图坐标。
std::vector<Det> YoloV6Postprocessor::process(const YoloV6FrameOutputs &outputs) const {
    if (outputs.source_width <= 0 || outputs.source_height <= 0) {
        throw std::invalid_argument("YOLOv6 source image dimensions must be positive");
    }
    if (std::any_of(outputs.heads.begin(), outputs.heads.end(), [](const float *head) { return head == nullptr; })) {
        throw std::invalid_argument("YOLOv6 frame output heads must not be null");
    }

    std::vector<float> boxes;
    std::vector<float> scores;
    std::vector<int> class_ids;

    // 1. 按固定的 8、16、32 步长解码三个输出头。
    constexpr std::array<int, 3> strides{{8, 16, 32}};
    int valid_count       = 0;
    const int class_count = static_cast<int>(labels_.size());
    for (std::size_t head_index = 0; head_index < strides.size(); ++head_index) {
        const int stride = strides[head_index];
        valid_count += process_float(
            outputs.heads[head_index], model_height_ / stride, model_width_ / stride, stride, boxes, scores, class_ids, confidence_threshold_, class_count);
    }

    std::vector<Det> detections;
    if (valid_count == 0) {
        return detections;
    }

    // 2. 按置信度排序并对候选框执行 NMS。
    std::vector<int> order(static_cast<std::size_t>(valid_count));
    for (int index = 0; index < valid_count; ++index) {
        order[static_cast<std::size_t>(index)] = index;
    }
    quick_sort_indice_inverse(scores, 0, valid_count - 1, order);
    nms(valid_count, boxes, order, nms_threshold_);

    // 3. 限制输出数量，并把模型坐标缩放到原始图像。
    const float scale_width  = static_cast<float>(outputs.source_width) / model_width_;
    const float scale_height = static_cast<float>(outputs.source_height) / model_height_;
    for (int index = 0; index < valid_count && index < 100; ++index) {
        const int box_index = order[static_cast<std::size_t>(index)];
        if (box_index == -1 || scores[static_cast<std::size_t>(index)] < confidence_threshold_) {
            continue;
        }

        const float x1     = boxes[static_cast<std::size_t>(box_index) * 4];
        const float y1     = boxes[static_cast<std::size_t>(box_index) * 4 + 1];
        const float x2     = x1 + boxes[static_cast<std::size_t>(box_index) * 4 + 2];
        const float y2     = y1 + boxes[static_cast<std::size_t>(box_index) * 4 + 3];
        const int class_id = class_ids[static_cast<std::size_t>(box_index)];

        Det detection;
        detection.x1       = static_cast<unsigned short>(static_cast<int>(clamp(x1, 0, model_width_ - 1) * scale_width));
        detection.y1       = static_cast<unsigned short>(static_cast<int>(clamp(y1, 0, model_height_ - 1) * scale_height));
        detection.x2       = static_cast<unsigned short>(static_cast<int>(clamp(x2, 0, model_width_ - 1) * scale_width));
        detection.y2       = static_cast<unsigned short>(static_cast<int>(clamp(y2, 0, model_height_ - 1) * scale_height));
        detection.conf     = scores[static_cast<std::size_t>(index)];
        detection.cls_name = labels_[static_cast<std::size_t>(class_id)];
        detection.cls_id   = static_cast<unsigned short>(class_id);
        detection.obj_id   = 0;
        detections.push_back(std::move(detection));
    }

    return detections;
}

}  // namespace rknn_yolov6
