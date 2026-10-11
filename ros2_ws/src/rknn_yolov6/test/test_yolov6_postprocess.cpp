#include <gtest/gtest.h>

#include <array>
#include <stdexcept>
#include <string>
#include <vector>

#include "rknn_yolov6/postprocess.hpp"

namespace rknn_yolov6 {
namespace {

using TensorHeads = std::array<std::vector<float>, 3>;

// 按模型尺寸和类别数创建三个固定布局的浮点输出头。
TensorHeads make_empty_heads(int model_width, int model_height, int class_count) {
    constexpr std::array<int, 3> strides{{8, 16, 32}};
    TensorHeads heads;
    for (std::size_t index = 0; index < strides.size(); ++index) {
        const int grid_width  = model_width / strides[index];
        const int grid_height = model_height / strides[index];
        const int grid_length = grid_width * grid_height;
        heads[index].resize(static_cast<std::size_t>(5 + class_count) * grid_length, 0.0F);
    }
    return heads;
}

// 在固定张量指定网格位置写入一条 YOLOv6 候选框。
void set_prediction(TensorHeads &heads,
                    int model_width,
                    int model_height,
                    std::size_t head_index,
                    int row,
                    int column,
                    float left,
                    float top,
                    float right,
                    float bottom,
                    float objectness,
                    const std::vector<float> &class_scores) {
    constexpr std::array<int, 3> strides{{8, 16, 32}};
    const int grid_width  = model_width / strides[head_index];
    const int grid_height = model_height / strides[head_index];
    const int grid_length = grid_width * grid_height;
    const int cell_index  = row * grid_width + column;
    auto &head            = heads[head_index];

    head[0 * grid_length + cell_index] = left;
    head[1 * grid_length + cell_index] = top;
    head[2 * grid_length + cell_index] = right;
    head[3 * grid_length + cell_index] = bottom;
    head[4 * grid_length + cell_index] = objectness;
    for (std::size_t class_index = 0; class_index < class_scores.size(); ++class_index) {
        head[(5 + class_index) * grid_length + cell_index] = class_scores[class_index];
    }
}

// 创建借用测试张量的帧视图，张量所有权仍由测试持有。
YoloV6FrameOutputs make_frame_view(const TensorHeads &heads, int source_width, int source_height) {
    return {{{heads[0].data(), heads[1].data(), heads[2].data()}}, source_width, source_height};
}

// 构造使用 64×64 模型输入和两个类别的测试配置。
YoloV6PostprocessorConfig make_config() {
    YoloV6PostprocessorConfig config;
    config.model_width          = 64;
    config.model_height         = 64;
    config.confidence_threshold = 0.30F;
    config.nms_threshold        = 0.30F;
    config.labels               = {"cat", "dog"};
    return config;
}

// 验证检测类别、置信度和从模型尺寸到原图尺寸的坐标映射。
TEST(YoloV6PostprocessorTest, DecodesClassAndScalesCoordinates) {
    const auto config = make_config();
    const YoloV6Postprocessor postprocessor(config);
    auto heads = make_empty_heads(config.model_width, config.model_height, static_cast<int>(config.labels.size()));
    set_prediction(heads, config.model_width, config.model_height, 0, 2, 3, 0.5F, 0.5F, 0.5F, 0.5F, 0.95F, {0.6F, 0.9F});

    const auto detections = postprocessor.process(make_frame_view(heads, 128, 128));

    ASSERT_EQ(1U, detections.size());
    EXPECT_EQ(48, detections[0].x1);
    EXPECT_EQ(32, detections[0].y1);
    EXPECT_EQ(64, detections[0].x2);
    EXPECT_EQ(48, detections[0].y2);
    EXPECT_FLOAT_EQ(0.9F, detections[0].conf);
    EXPECT_EQ(1, detections[0].cls_id);
    EXPECT_EQ("dog", detections[0].cls_name);
}

// 验证高置信度候选框会按配置阈值抑制重叠框。
TEST(YoloV6PostprocessorTest, SuppressesOverlappingBoxes) {
    const auto config = make_config();
    const YoloV6Postprocessor postprocessor(config);
    auto heads = make_empty_heads(config.model_width, config.model_height, static_cast<int>(config.labels.size()));
    set_prediction(heads, config.model_width, config.model_height, 0, 2, 2, 1.0F, 1.0F, 1.0F, 1.0F, 0.95F, {0.9F, 0.1F});
    set_prediction(heads, config.model_width, config.model_height, 0, 2, 3, 1.0F, 1.0F, 1.0F, 1.0F, 0.90F, {0.8F, 0.1F});

    const auto detections = postprocessor.process(make_frame_view(heads, 64, 64));

    ASSERT_EQ(1U, detections.size());
    EXPECT_FLOAT_EQ(0.9F, detections[0].conf);
}

// 验证目标置信度低于阈值时不会生成检测结果。
TEST(YoloV6PostprocessorTest, FiltersCandidatesBelowConfidenceThreshold) {
    const auto config = make_config();
    const YoloV6Postprocessor postprocessor(config);
    auto heads = make_empty_heads(config.model_width, config.model_height, static_cast<int>(config.labels.size()));
    set_prediction(heads, config.model_width, config.model_height, 0, 2, 2, 0.5F, 0.5F, 0.5F, 0.5F, 0.2F, {0.95F, 0.1F});

    const auto detections = postprocessor.process(make_frame_view(heads, 64, 64));

    EXPECT_TRUE(detections.empty());
}

// 验证三个固定步长输出头都会解码，且结果按置信度降序返回。
TEST(YoloV6PostprocessorTest, DecodesAllOutputHeadsInConfidenceOrder) {
    const auto config = make_config();
    const YoloV6Postprocessor postprocessor(config);
    auto heads = make_empty_heads(config.model_width, config.model_height, static_cast<int>(config.labels.size()));
    set_prediction(heads, config.model_width, config.model_height, 0, 1, 1, 0.5F, 0.5F, 0.5F, 0.5F, 0.95F, {0.6F, 0.1F});
    set_prediction(heads, config.model_width, config.model_height, 1, 2, 2, 0.5F, 0.5F, 0.5F, 0.5F, 0.95F, {0.1F, 0.8F});
    set_prediction(heads, config.model_width, config.model_height, 2, 1, 1, 0.5F, 0.5F, 0.5F, 0.5F, 0.95F, {0.7F, 0.1F});

    const auto detections = postprocessor.process(make_frame_view(heads, 64, 64));

    ASSERT_EQ(3U, detections.size());
    EXPECT_FLOAT_EQ(0.8F, detections[0].conf);
    EXPECT_EQ("dog", detections[0].cls_name);
    EXPECT_FLOAT_EQ(0.7F, detections[1].conf);
    EXPECT_EQ("cat", detections[1].cls_name);
    EXPECT_FLOAT_EQ(0.6F, detections[2].conf);
    EXPECT_EQ("cat", detections[2].cls_name);
}

// 验证非正模型尺寸会在初始化模块时被拒绝。
TEST(YoloV6PostprocessorTest, RejectsNonPositiveModelDimensions) {
    auto config        = make_config();
    config.model_width = 0;

    EXPECT_THROW({ static_cast<void>(YoloV6Postprocessor(config)); }, std::invalid_argument);
}

// 验证缺少类别标签会在初始化模块时被拒绝。
TEST(YoloV6PostprocessorTest, RejectsMissingLabels) {
    auto config = make_config();
    config.labels.clear();

    EXPECT_THROW({ static_cast<void>(YoloV6Postprocessor(config)); }, std::invalid_argument);
}

// 验证帧图像尺寸无效时后处理会显式报错。
TEST(YoloV6PostprocessorTest, RejectsInvalidSourceDimensions) {
    const auto config = make_config();
    const YoloV6Postprocessor postprocessor(config);
    auto heads = make_empty_heads(config.model_width, config.model_height, static_cast<int>(config.labels.size()));

    EXPECT_THROW(postprocessor.process(make_frame_view(heads, 0, 64)), std::invalid_argument);
}

}  // namespace
}  // namespace rknn_yolov6
