#include <rknn_api.h>

#include <cstdint>
#include <fstream>
#include <im2d.hpp>
#include <opencv2/core.hpp>
#include <rclcpp/rclcpp.hpp>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "detector_backend.hpp"

namespace rknn_yolov6 {
namespace detail {
namespace {

// 持有 RKNN 输出张量，并在帧离开两阶段流程时释放运行时资源。
class RknnFrameResult final : public DetectorBackendFrameResult {
public:
    // 记录释放输出张量所需的上下文和原始图像尺寸。
    RknnFrameResult(rknn_context context, std::uint32_t output_count, int source_width, int source_height)
        : context_(context), output_count_(output_count), source_width_(source_width), source_height_(source_height), outputs_(output_count) {
        for (auto &output : outputs_) {
            output.want_float = 1;
        }
    }

    // 若推理成功取得张量，则在帧结果销毁时归还给 RKNN。
    ~RknnFrameResult() override {
        if (outputs_acquired_) {
            rknn_outputs_release(context_, output_count_, outputs_.data());
        }
    }

    // 返回当前帧持有的 RKNN 输出张量。
    std::vector<rknn_output> &outputs() { return outputs_; }

    // 标记 RKNN 已将输出张量交给当前帧。
    void mark_outputs_acquired() { outputs_acquired_ = true; }

    // 返回输入图像宽度，用于还原检测框坐标。
    int source_width() const { return source_width_; }

    // 返回输入图像高度，用于还原检测框坐标。
    int source_height() const { return source_height_; }

private:
    rknn_context context_{0};
    std::uint32_t output_count_{0};
    int source_width_{0};
    int source_height_{0};
    std::vector<rknn_output> outputs_;
    bool outputs_acquired_{false};
};

// 实现使用 RGA 缩放的 RKNN YOLOv6 检测后端。
class RknnRgaDetectorBackend final : public DetectorBackend {
public:
    // 加载标签并初始化 RKNN 上下文和模型张量元信息。
    RknnRgaDetectorBackend(const DetectorBackendConfig &config, const rclcpp::Logger &logger, rclcpp::Clock::SharedPtr clock)
        : confidence_threshold_(config.confidence_threshold),
          nms_threshold_(config.nms_threshold),
          print_perf_detail_(config.print_perf_detail),
          use_multi_npu_core_(config.use_multi_npu_core),
          logger_(logger),
          clock_(std::move(clock)) {
        if (config.model_path.empty() || config.labels_path.empty()) {
            throw std::runtime_error("RKNN backend requires model_path and labels_path");
        }

        try {
            load_labels(config.labels_path);
            initialize_rknn(config.model_path);
        } catch (...) {
            destroy_context();
            throw;
        }
    }

    // 线程退出后销毁 RKNN 上下文。
    ~RknnRgaDetectorBackend() override { destroy_context(); }

    // 准备输入、运行 RKNN 并保存跨阶段输出张量。
    std::unique_ptr<DetectorBackendFrameResult> infer(const cv::Mat &image) override {
        // 1. 将输入图像调整到模型尺寸；尺寸不匹配时通过 RGA 缩放。
        cv::Mat resized;
        const cv::Mat *input_image = &image;
        if (image.cols != model_width_ || image.rows != model_height_) {
            resized.create(model_height_, model_width_, CV_8UC3);
            if (!resize_with_rga(image, resized)) {
                return nullptr;
            }
            input_image = &resized;
        }

        // 2. 设置 RKNN 输入并执行推理，失败时记录错误并结束当前帧。
        rknn_input input{};
        input.index        = 0;
        input.buf          = input_image->data;
        input.size         = static_cast<std::uint32_t>(input_image->total() * input_image->elemSize());
        input.type         = RKNN_TENSOR_UINT8;
        input.fmt          = RKNN_TENSOR_NHWC;
        input.pass_through = 0;
        int result         = rknn_inputs_set(context_, 1, &input);
        if (result >= 0) {
            result = rknn_run(context_, nullptr);
        }
        if (result < 0) {
            RCLCPP_ERROR_THROTTLE(logger_, *clock_, 2000, "RKNN inference failed: %d", result);
            return nullptr;
        }

        // 3. 按需查询逐层耗时，默认关闭以保留当前运行开销。
        if (print_perf_detail_) {
            rknn_perf_detail detail{};
            if (rknn_query(context_, RKNN_QUERY_PERF_DETAIL, &detail, sizeof(detail)) >= 0) {
                RCLCPP_INFO(logger_, "RKNN perf detail: %s", detail.perf_data);
            }
        }

        // 4. 获取输出张量并交给帧结果对象管理，供结果线程后处理。
        auto frame_result = std::make_unique<RknnFrameResult>(context_, io_count_.n_output, image.cols, image.rows);
        result            = rknn_outputs_get(context_, io_count_.n_output, frame_result->outputs().data(), nullptr);
        if (result < 0) {
            RCLCPP_ERROR_THROTTLE(logger_, *clock_, 2000, "RKNN output retrieval failed: %d", result);
            return nullptr;
        }
        frame_result->mark_outputs_acquired();
        return frame_result;
    }

    // 用现有 YOLOv6 算法将当前 RKNN 输出解释为 Detection。
    std::vector<Det> detections(DetectorBackendFrameResult &frame_result) override {
        auto *rknn_result = dynamic_cast<RknnFrameResult *>(&frame_result);
        if (rknn_result == nullptr) {
            throw std::runtime_error("RKNN backend received an incompatible frame result");
        }

        auto &outputs = rknn_result->outputs();
        std::vector<Det> detections;
        std::vector<int> output_indices{0, 1, 2};
        post_process(outputs[0].want_float,
                     outputs[0].buf,
                     outputs[1].buf,
                     outputs[2].buf,
                     model_height_,
                     model_width_,
                     confidence_threshold_,
                     nms_threshold_,
                     static_cast<float>(rknn_result->source_width()) / model_width_,
                     static_cast<float>(rknn_result->source_height()) / model_height_,
                     output_zero_points_,
                     output_scales_,
                     output_indices,
                     labels_,
                     static_cast<int>(labels_.size()),
                     detections);
        return detections;
    }

private:
    // 从类别文件读取标签，并要求至少存在一个类别。
    void load_labels(const std::string &labels_path) {
        std::ifstream input(labels_path);
        std::string line;
        while (std::getline(input, line)) {
            if (!line.empty()) {
                labels_.push_back(line);
            }
        }
        if (labels_.empty()) {
            throw std::runtime_error("labels_path is empty or unreadable: " + labels_path);
        }
    }

    // 初始化 RKNN 模型、核心选择和输入输出张量元信息。
    void initialize_rknn(const std::string &model_path) {
        std::ifstream model(model_path, std::ios::binary | std::ios::ate);
        if (!model) {
            throw std::runtime_error("model_path is unreadable: " + model_path);
        }
        const auto model_size = model.tellg();
        if (model_size <= 0) {
            throw std::runtime_error("model_path is empty: " + model_path);
        }
        model.seekg(0);
        model_data_.resize(static_cast<std::size_t>(model_size));
        if (!model.read(reinterpret_cast<char *>(model_data_.data()), static_cast<std::streamsize>(model_size))) {
            throw std::runtime_error("failed to read RKNN model: " + model_path);
        }

        const std::uint32_t flags = print_perf_detail_ ? RKNN_FLAG_COLLECT_PERF_MASK : 0;
        int result                = rknn_init(&context_, model_data_.data(), static_cast<std::uint32_t>(model_data_.size()), flags, nullptr);
        if (result < 0) {
            throw std::runtime_error("rknn_init failed: " + std::to_string(result));
        }

        const rknn_core_mask core_mask = use_multi_npu_core_ ? RKNN_NPU_CORE_0_1_2 : RKNN_NPU_CORE_AUTO;
        result                         = rknn_set_core_mask(context_, core_mask);
        if (result < 0) {
            throw std::runtime_error("rknn_set_core_mask failed: " + std::to_string(result));
        }

        rknn_sdk_version version{};
        result = rknn_query(context_, RKNN_QUERY_SDK_VERSION, &version, sizeof(version));
        if (result < 0) {
            throw std::runtime_error("cannot query RKNN SDK version");
        }
        RCLCPP_INFO(logger_, "RKNN runtime=%s driver=%s", version.api_version, version.drv_version);

        result = rknn_query(context_, RKNN_QUERY_IN_OUT_NUM, &io_count_, sizeof(io_count_));
        if (result < 0 || io_count_.n_input != 1 || io_count_.n_output < 3) {
            throw std::runtime_error("unexpected RKNN input/output count");
        }

        rknn_tensor_attr input_attribute{};
        input_attribute.index = 0;
        result                = rknn_query(context_, RKNN_QUERY_INPUT_ATTR, &input_attribute, sizeof(input_attribute));
        if (result < 0) {
            throw std::runtime_error("cannot query RKNN input tensor");
        }
        if (input_attribute.fmt == RKNN_TENSOR_NHWC) {
            model_height_ = static_cast<int>(input_attribute.dims[1]);
            model_width_  = static_cast<int>(input_attribute.dims[2]);
            channels_     = static_cast<int>(input_attribute.dims[3]);
        } else {
            channels_     = static_cast<int>(input_attribute.dims[1]);
            model_height_ = static_cast<int>(input_attribute.dims[2]);
            model_width_  = static_cast<int>(input_attribute.dims[3]);
        }
        if (channels_ != 3 || model_width_ <= 0 || model_height_ <= 0) {
            throw std::runtime_error("RKNN model input must have three channels and positive dimensions");
        }

        output_zero_points_.reserve(io_count_.n_output);
        output_scales_.reserve(io_count_.n_output);
        for (std::uint32_t index = 0; index < io_count_.n_output; ++index) {
            rknn_tensor_attr output_attribute{};
            output_attribute.index = index;
            result                 = rknn_query(context_, RKNN_QUERY_OUTPUT_ATTR, &output_attribute, sizeof(output_attribute));
            if (result < 0) {
                throw std::runtime_error("cannot query RKNN output tensor");
            }
            output_zero_points_.push_back(output_attribute.zp);
            output_scales_.push_back(output_attribute.scale);
        }
    }

    // 通过 RGA 将 RGB 图像缩放到模型输入尺寸。
    bool resize_with_rga(const cv::Mat &source, cv::Mat &destination) {
        auto src = wrapbuffer_virtualaddr_t(const_cast<std::uint8_t *>(source.data), source.cols, source.rows, source.cols, source.rows, RK_FORMAT_RGB_888);
        auto dst = wrapbuffer_virtualaddr_t(destination.data, destination.cols, destination.rows, destination.cols, destination.rows, RK_FORMAT_RGB_888);
        const im_rect source_rect{};
        const im_rect destination_rect{};
        const int check_result = imcheck_t(src, dst, rga_buffer_t{}, source_rect, destination_rect, im_rect{}, 0);
        if (check_result != IM_STATUS_NOERROR) {
            RCLCPP_ERROR(logger_, "RGA input validation failed: %s", imStrError_t(static_cast<IM_STATUS>(check_result)));
            return false;
        }

        const IM_STATUS result = imresize_t(src, dst, 0.0, 0.0, INTER_LINEAR, 1);
        if (result != IM_STATUS_SUCCESS && result != IM_STATUS_NOERROR) {
            RCLCPP_ERROR(logger_, "RGA resize failed: %s", imStrError_t(result));
            return false;
        }
        return true;
    }

    // 销毁已创建的 RKNN 上下文，覆盖初始化失败和正常关闭。
    void destroy_context() {
        if (context_ != 0) {
            rknn_destroy(context_);
            context_ = 0;
        }
    }

    float confidence_threshold_{0.30F};
    float nms_threshold_{0.30F};
    bool print_perf_detail_{false};
    bool use_multi_npu_core_{false};
    rclcpp::Logger logger_;
    rclcpp::Clock::SharedPtr clock_;
    int model_width_{0};
    int model_height_{0};
    int channels_{0};
    rknn_context context_{0};
    rknn_input_output_num io_count_{};
    std::vector<std::uint8_t> model_data_;
    std::vector<std::int32_t> output_zero_points_;
    std::vector<float> output_scales_;
    std::vector<std::string> labels_;
};

}  // namespace

// 创建 RKNN/RGA adapter 并传入 ROS 日志依赖。
std::unique_ptr<DetectorBackend> create_detector_backend(const DetectorBackendConfig &config, const rclcpp::Logger &logger, rclcpp::Clock::SharedPtr clock) {
    return std::make_unique<RknnRgaDetectorBackend>(config, logger, std::move(clock));
}

}  // namespace detail
}  // namespace rknn_yolov6
