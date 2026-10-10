#include "rknn_yolov6/rknn_yolov6_node.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <robot_interfaces/msg/det.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/header.hpp>

#include "rknn_yolov6/bounded_queue.hpp"
#include "rknn_yolov6/postprocess.hpp"

#ifdef RKNN_YOLOV6_BACKEND_RKNN
#include <rknn_api.h>

#include <im2d.hpp>
#endif

#ifdef RKNN_YOLOV6_BACKEND_HAAR
#include <opencv2/objdetect.hpp>
#endif

#include <sys/stat.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace rknn_yolov6 {
namespace {

constexpr std::size_t kQueueCapacity = 2;

// 保存单帧图像、推理输出及 ROS 时间信息，贯穿两个处理阶段。
struct FrameData {
    sensor_msgs::msg::Image::ConstSharedPtr input_message;
    std_msgs::msg::Header header;
    cv::Mat image;
    std::uint64_t offline_index{0};
#ifdef RKNN_YOLOV6_BACKEND_RKNN
    std::vector<rknn_output> outputs;
    bool outputs_acquired{false};
#endif
#ifdef RKNN_YOLOV6_BACKEND_HAAR
    std::vector<cv::Rect> faces;
#endif
};

}  // namespace

// 集中管理 ROS 接口、检测后端和有界双阶段处理队列。
struct RknnYolov6Node::Implementation {
    // 读取参数、初始化后端并启动 ROS 接口和处理线程。
    explicit Implementation(RknnYolov6Node *node) : node_(node) {
        read_parameters();
        initialize_backend();
        create_ros_interfaces();

        started_at_        = std::chrono::steady_clock::now();
        last_report_at_    = started_at_;
        processing_thread_ = std::thread(&Implementation::run_processing_stage, this);
        inference_thread_  = std::thread(&Implementation::run_inference_stage, this);
    }

    // 关闭队列、等待工作线程退出并释放 RKNN 上下文。
    ~Implementation() {
        stopping_.store(true);
        input_queue_.close();
        if (inference_thread_.joinable()) {
            inference_thread_.join();
        }
        output_queue_.close();
        if (processing_thread_.joinable()) {
            processing_thread_.join();
        }
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        if (context_ != 0) {
            rknn_destroy(context_);
            context_ = 0;
        }
#endif
    }

    // 声明 ROS 参数并校验当前检测后端需要的路径。
    void read_parameters() {
        model_path_           = node_->declare_parameter<std::string>("model_path", "");
        labels_path_          = node_->declare_parameter<std::string>("labels_path", "");
        input_topic_          = node_->declare_parameter<std::string>("input_topic", "/camera/image_raw");
        detections_topic_     = node_->declare_parameter<std::string>("detections_topic", "/ai_msg_det");
        annotated_topic_      = node_->declare_parameter<std::string>("annotated_topic", "/camera/image_det");
        confidence_threshold_ = node_->declare_parameter<double>("confidence_threshold", 0.30);
        nms_threshold_        = node_->declare_parameter<double>("nms_threshold", 0.30);
        enabled_.store(node_->declare_parameter<bool>("enabled", true));
        always_process_      = node_->declare_parameter<bool>("always_process", false);
        print_perf_detail_   = node_->declare_parameter<bool>("print_perf_detail", false);
        use_multi_npu_core_  = node_->declare_parameter<bool>("use_multi_npu_core", false);
        offline_mode_        = node_->declare_parameter<bool>("is_offline_image_mode", false);
        offline_images_path_ = node_->declare_parameter<std::string>("offline_images_path", "");
        offline_output_path_ = node_->declare_parameter<std::string>("offline_output_path", "");
        haar_cascade_path_   = node_->declare_parameter<std::string>("haar_cascade_path", "");

        if (offline_mode_ && (offline_images_path_.empty() || offline_output_path_.empty())) {
            throw std::runtime_error("offline image mode requires offline_images_path and offline_output_path");
        }
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        if (model_path_.empty() || labels_path_.empty()) {
            throw std::runtime_error("RKNN backend requires model_path and labels_path");
        }
#endif
#ifdef RKNN_YOLOV6_BACKEND_HAAR
        if (haar_cascade_path_.empty()) {
            throw std::runtime_error("Haar backend requires haar_cascade_path");
        }
#endif
    }

    // 加载 RKNN 模型与标签，或加载主机侧 Haar 分类器。
    void initialize_backend() {
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        load_labels();
        initialize_rknn();
#endif
#ifdef RKNN_YOLOV6_BACKEND_HAAR
        if (!face_cascade_.load(haar_cascade_path_)) {
            throw std::runtime_error("cannot load Haar cascade: " + haar_cascade_path_);
        }
#endif
    }

    // 创建保持现有话题、消息类型和 QoS 的 ROS 2 发布与订阅接口。
    void create_ros_interfaces() {
        const auto qos        = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
        detections_publisher_ = node_->create_publisher<robot_interfaces::msg::Dets>(detections_topic_, qos);
        annotated_publisher_  = node_->create_publisher<sensor_msgs::msg::Image>(annotated_topic_, qos);
        image_subscription_   = node_->create_subscription<sensor_msgs::msg::Image>(
            input_topic_, qos, [this](sensor_msgs::msg::Image::ConstSharedPtr message) { receive_image(std::move(message)); });
        enable_subscription_ = node_->create_subscription<std_msgs::msg::Bool>(
            "/enable_detector", 10, [this](std_msgs::msg::Bool::ConstSharedPtr message) { enabled_.store(message->data); });
    }

#ifdef RKNN_YOLOV6_BACKEND_RKNN
    // 从类别文件读取标签名称并确保后处理至少有一个类别。
    void load_labels() {
        std::ifstream input(labels_path_);
        std::string line;
        while (std::getline(input, line)) {
            if (!line.empty()) {
                labels_.push_back(line);
            }
        }
        if (labels_.empty()) {
            throw std::runtime_error("labels_path is empty or unreadable: " + labels_path_);
        }
    }

    // 初始化 RKNN 上下文、模型张量信息、核心掩码和输出量化参数。
    void initialize_rknn() {
        std::ifstream model(model_path_, std::ios::binary | std::ios::ate);
        if (!model) {
            throw std::runtime_error("model_path is unreadable: " + model_path_);
        }
        const auto model_size = model.tellg();
        if (model_size <= 0) {
            throw std::runtime_error("model_path is empty: " + model_path_);
        }
        model.seekg(0);
        model_data_.resize(static_cast<std::size_t>(model_size));
        if (!model.read(reinterpret_cast<char *>(model_data_.data()), static_cast<std::streamsize>(model_size))) {
            throw std::runtime_error("failed to read RKNN model: " + model_path_);
        }

        try {
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
            RCLCPP_INFO(node_->get_logger(), "RKNN runtime=%s driver=%s", version.api_version, version.drv_version);

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
        } catch (...) {
            if (context_ != 0) {
                rknn_destroy(context_);
                context_ = 0;
            }
            throw;
        }
    }
#endif

    // 接收符合启用状态及订阅状态的 RGB 图像并送入输入队列。
    void receive_image(sensor_msgs::msg::Image::ConstSharedPtr message) {
        if (offline_mode_ || !enabled_.load()) {
            return;
        }
        if (!always_process_ && detections_publisher_->get_subscription_count() == 0 && annotated_publisher_->get_subscription_count() == 0) {
            return;
        }
        const auto row_size  = static_cast<std::size_t>(message->width) * 3;
        const auto data_size = static_cast<std::size_t>(message->step) * message->height;
        if (message->encoding != "rgb8" || message->width == 0 || message->height == 0 || message->step < row_size || message->data.size() < data_size) {
            RCLCPP_WARN_THROTTLE(node_->get_logger(), *node_->get_clock(), 2000, "expected a complete rgb8 image");
            return;
        }

        auto frame           = std::make_shared<FrameData>();
        frame->input_message = std::move(message);
        frame->header        = frame->input_message->header;
        const cv::Mat source(static_cast<int>(frame->input_message->height),
                             static_cast<int>(frame->input_message->width),
                             CV_8UC3,
                             const_cast<std::uint8_t *>(frame->input_message->data.data()),
                             frame->input_message->step);
        frame->image = source.clone();
        input_queue_.push(std::move(frame));
    }

    // 按实时或离线模式生成帧，在推理完成后交给后处理线程。
    void run_inference_stage() {
        if (offline_mode_) {
            run_offline_images();
        } else {
            while (auto frame = input_queue_.wait_and_pop()) {
                if (stopping_.load()) {
                    break;
                }
                if (run_inference(*frame)) {
                    queue_inference_result(std::move(frame));
                }
            }
        }
        output_queue_.close();
    }

    // 对当前帧运行 RKNN 模型或 Haar 分类器并记录后处理数据。
    bool run_inference(FrameData &frame) {
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        cv::Mat resized;
        const cv::Mat *input_image = &frame.image;
        if (frame.image.cols != model_width_ || frame.image.rows != model_height_) {
            resized.create(model_height_, model_width_, CV_8UC3);
            if (!resize_with_rga(frame.image, resized)) {
                return false;
            }
            input_image = &resized;
        }

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
            RCLCPP_ERROR_THROTTLE(node_->get_logger(), *node_->get_clock(), 2000, "RKNN inference failed: %d", result);
            return false;
        }

        if (print_perf_detail_) {
            rknn_perf_detail detail{};
            if (rknn_query(context_, RKNN_QUERY_PERF_DETAIL, &detail, sizeof(detail)) >= 0) {
                RCLCPP_INFO(node_->get_logger(), "RKNN perf detail: %s", detail.perf_data);
            }
        }

        frame.outputs.resize(io_count_.n_output);
        for (auto &output : frame.outputs) {
            output.want_float = 1;
        }
        result = rknn_outputs_get(context_, io_count_.n_output, frame.outputs.data(), nullptr);
        if (result < 0) {
            RCLCPP_ERROR_THROTTLE(node_->get_logger(), *node_->get_clock(), 2000, "RKNN output retrieval failed: %d", result);
            return false;
        }
        frame.outputs_acquired = true;
        return true;
#else
        cv::Mat gray;
        cv::cvtColor(frame.image, gray, cv::COLOR_RGB2GRAY);
        face_cascade_.detectMultiScale(gray, frame.faces, 1.1, 2, 0 | cv::CASCADE_SCALE_IMAGE, cv::Size(30, 30));
        return true;
#endif
    }

#ifdef RKNN_YOLOV6_BACKEND_RKNN
    // 通过 RGA 将 RGB 图像缩放到模型输入尺寸。
    bool resize_with_rga(const cv::Mat &source, cv::Mat &destination) {
        auto src = wrapbuffer_virtualaddr_t(const_cast<std::uint8_t *>(source.data), source.cols, source.rows, source.cols, source.rows, RK_FORMAT_RGB_888);
        auto dst = wrapbuffer_virtualaddr_t(destination.data, destination.cols, destination.rows, destination.cols, destination.rows, RK_FORMAT_RGB_888);
        const im_rect source_rect{};
        const im_rect destination_rect{};
        const int check_result = imcheck_t(src, dst, rga_buffer_t{}, source_rect, destination_rect, im_rect{}, 0);
        if (check_result != IM_STATUS_NOERROR) {
            RCLCPP_ERROR(node_->get_logger(), "RGA input validation failed: %s", imStrError_t(static_cast<IM_STATUS>(check_result)));
            return false;
        }

        const IM_STATUS result = imresize_t(src, dst, 0.0, 0.0, INTER_LINEAR, 1);
        if (result != IM_STATUS_SUCCESS && result != IM_STATUS_NOERROR) {
            RCLCPP_ERROR(node_->get_logger(), "RGA resize failed: %s", imStrError_t(result));
            return false;
        }
        return true;
    }

    // 释放已取得的 RKNN 输出，覆盖正常处理和队列淘汰路径。
    void release_outputs(FrameData &frame) {
        if (frame.outputs_acquired) {
            rknn_outputs_release(context_, io_count_.n_output, frame.outputs.data());
            frame.outputs_acquired = false;
        }
    }
#endif

    // 推入后处理队列，并释放因队列满而淘汰帧的 RKNN 输出。
    void queue_inference_result(std::shared_ptr<FrameData> frame) {
        auto dropped = output_queue_.push(std::move(frame));
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        if (dropped) {
            release_outputs(*dropped);
        }
#endif
    }

    // 从外部图片目录构造离线帧并送入实时处理路径。
    void run_offline_images() {
        std::vector<cv::String> image_paths;
        cv::glob(offline_images_path_, image_paths, false);
        if (image_paths.empty()) {
            RCLCPP_ERROR(node_->get_logger(), "offline_images_path has no images: %s", offline_images_path_.c_str());
            return;
        }
        if (!ensure_output_directory()) {
            return;
        }

        for (std::size_t index = 0; index < image_paths.size() && !stopping_.load(); ++index) {
            const cv::Mat bgr_image = cv::imread(image_paths[index], cv::IMREAD_COLOR);
            if (bgr_image.empty()) {
                RCLCPP_WARN(node_->get_logger(), "cannot read offline image: %s", image_paths[index].c_str());
                continue;
            }

            auto frame = std::make_shared<FrameData>();
            cv::cvtColor(bgr_image, frame->image, cv::COLOR_BGR2RGB);
            frame->offline_index   = index;
            frame->header.stamp    = node_->now();
            frame->header.frame_id = "image";
            if (run_inference(*frame)) {
                queue_inference_result(std::move(frame));
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        }
    }

    // 确认离线输出目录存在，必要时创建单层目录。
    bool ensure_output_directory() {
        struct stat status {};
        if (stat(offline_output_path_.c_str(), &status) == 0) {
            if (S_ISDIR(status.st_mode)) {
                return true;
            }
            RCLCPP_ERROR(node_->get_logger(), "offline_output_path is not a directory: %s", offline_output_path_.c_str());
            return false;
        }
        if (mkdir(offline_output_path_.c_str(), 0777) == 0) {
            return true;
        }
        RCLCPP_ERROR(node_->get_logger(), "cannot create offline output directory: %s", offline_output_path_.c_str());
        return false;
    }

    // 从后处理队列取帧并发布检测结果及标注图像。
    void run_processing_stage() {
        while (auto frame = output_queue_.wait_and_pop()) {
            try {
                process_frame(*frame);
            } catch (const std::exception &error) {
                RCLCPP_ERROR(node_->get_logger(), "frame processing failed: %s", error.what());
#ifdef RKNN_YOLOV6_BACKEND_RKNN
                release_outputs(*frame);
#endif
            }
        }
    }

    // 后处理单帧检测结果，绘制标注、发布消息并保存离线图像。
    void process_frame(FrameData &frame) {
        std::vector<Det> detections;
#ifdef RKNN_YOLOV6_BACKEND_RKNN
        std::vector<int> output_indices{0, 1, 2};
        post_process(frame.outputs[0].want_float,
                     frame.outputs[0].buf,
                     frame.outputs[1].buf,
                     frame.outputs[2].buf,
                     model_height_,
                     model_width_,
                     static_cast<float>(confidence_threshold_),
                     static_cast<float>(nms_threshold_),
                     static_cast<float>(frame.image.cols) / model_width_,
                     static_cast<float>(frame.image.rows) / model_height_,
                     output_zero_points_,
                     output_scales_,
                     output_indices,
                     labels_,
                     static_cast<int>(labels_.size()),
                     detections);
        release_outputs(frame);
#else
        detections.reserve(frame.faces.size());
        for (const auto &face : frame.faces) {
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
#endif

        auto annotated = frame.image.clone();
        robot_interfaces::msg::Dets detection_message;
        detection_message.header       = frame.header;
        detection_message.image_width  = static_cast<std::uint32_t>(frame.image.cols);
        detection_message.image_height = static_cast<std::uint32_t>(frame.image.rows);
        const auto &colors             = detection_colors();
        for (const auto &detection : detections) {
            robot_interfaces::msg::Det converted;
            converted.x1         = detection.x1;
            converted.y1         = detection.y1;
            converted.x2         = detection.x2;
            converted.y2         = detection.y2;
            converted.confidence = detection.conf;
            converted.class_name = detection.cls_name;
            converted.class_id   = detection.cls_id;
            converted.object_id  = detection.obj_id;
            detection_message.detections.push_back(std::move(converted));

            const auto &color = colors[detection.cls_id % colors.size()];
            cv::rectangle(annotated, cv::Point(detection.x1, detection.y1), cv::Point(detection.x2, detection.y2), color, 2);
            char text[256];
            std::snprintf(text, sizeof(text), "%s%.0f%%", detection.cls_name.c_str(), detection.conf * 100.0F);
            cv::putText(annotated, text, cv::Point(detection.x1, std::max<int>(15, detection.y1 - 6)), cv::FONT_HERSHEY_SIMPLEX, 0.5, color, 2);
        }

        detections_publisher_->publish(detection_message);
        if (offline_mode_ || annotated_publisher_->get_subscription_count() > 0) {
            sensor_msgs::msg::Image output;
            output.header       = frame.header;
            output.height       = static_cast<std::uint32_t>(annotated.rows);
            output.width        = static_cast<std::uint32_t>(annotated.cols);
            output.encoding     = "rgb8";
            output.is_bigendian = false;
            output.step         = output.width * 3;
            output.data.assign(annotated.data, annotated.data + annotated.total() * annotated.elemSize());
            annotated_publisher_->publish(std::move(output));
        }

        if (offline_mode_) {
            const std::string path = offline_output_path_ + "/" + std::to_string(frame.offline_index) + ".jpg";
            if (!cv::imwrite(path, annotated)) {
                RCLCPP_WARN(node_->get_logger(), "failed to save offline result: %s", path.c_str());
            }
        }
        report_processing_rate(detections.size());
    }

    // 返回旧实现使用的类别颜色表。
    const std::array<cv::Scalar, 12> &detection_colors() const {
        static const std::array<cv::Scalar, 12> colors{cv::Scalar(0, 0, 255),
                                                       cv::Scalar(0, 255, 0),
                                                       cv::Scalar(255, 0, 0),
                                                       cv::Scalar(0, 255, 255),
                                                       cv::Scalar(255, 0, 255),
                                                       cv::Scalar(255, 255, 0),
                                                       cv::Scalar(0, 128, 255),
                                                       cv::Scalar(0, 255, 128),
                                                       cv::Scalar(128, 0, 128),
                                                       cv::Scalar(255, 0, 128),
                                                       cv::Scalar(128, 255, 0),
                                                       cv::Scalar(255, 128, 0)};
        return colors;
    }

    // 每五秒报告一次处理帧速率及最近一帧检测数量。
    void report_processing_rate(std::size_t detection_count) {
        ++processed_frames_;
        const auto now = std::chrono::steady_clock::now();
        if (now - last_report_at_ >= std::chrono::seconds(5)) {
            const double elapsed = std::chrono::duration<double>(now - started_at_).count();
            RCLCPP_INFO(node_->get_logger(), "inference %.1f fps, detections=%zu", elapsed > 0.0 ? processed_frames_ / elapsed : 0.0, detection_count);
            last_report_at_ = now;
        }
    }

    // ROS 参数和节点所有者。
    RknnYolov6Node *node_;
    std::string model_path_;
    std::string labels_path_;
    std::string input_topic_;
    std::string detections_topic_;
    std::string annotated_topic_;
    std::string offline_images_path_;
    std::string offline_output_path_;
    std::string haar_cascade_path_;
    double confidence_threshold_{0.30};
    double nms_threshold_{0.30};
    bool always_process_{false};
    bool print_perf_detail_{false};
    bool use_multi_npu_core_{false};
    bool offline_mode_{false};
    std::atomic<bool> enabled_{true};
    std::atomic<bool> stopping_{false};

    // 两个容量二队列及其工作线程。
    BoundedQueue<FrameData> input_queue_{kQueueCapacity};
    BoundedQueue<FrameData> output_queue_{kQueueCapacity};
    std::thread inference_thread_;
    std::thread processing_thread_;
    std::chrono::steady_clock::time_point started_at_;
    std::chrono::steady_clock::time_point last_report_at_;
    std::uint64_t processed_frames_{0};

    // ROS 发布者和订阅者。
    rclcpp::Publisher<robot_interfaces::msg::Dets>::SharedPtr detections_publisher_;
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr annotated_publisher_;
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_subscription_;
    rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;

#ifdef RKNN_YOLOV6_BACKEND_RKNN
    // RKNN 上下文、模型数据和模型张量元信息。
    int model_width_{0};
    int model_height_{0};
    int channels_{0};
    rknn_context context_{0};
    rknn_input_output_num io_count_{};
    std::vector<std::uint8_t> model_data_;
    std::vector<std::int32_t> output_zero_points_;
    std::vector<float> output_scales_;
    std::vector<std::string> labels_;
#endif
#ifdef RKNN_YOLOV6_BACKEND_HAAR
    // 主机侧 Haar 级联分类器。
    cv::CascadeClassifier face_cascade_;
#endif
};

// 使用 ROS 2 参数创建检测节点实现。
RknnYolov6Node::RknnYolov6Node(const rclcpp::NodeOptions &options) : Node("rknn_yolov6", options), implementation_(std::make_unique<Implementation>(this)) {}

// 先销毁实现对象，确保工作线程在 ROS 节点接口前停止。
RknnYolov6Node::~RknnYolov6Node() = default;

}  // namespace rknn_yolov6
