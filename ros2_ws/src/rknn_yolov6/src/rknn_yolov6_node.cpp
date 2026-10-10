#include "rknn_yolov6/rknn_yolov6_node.hpp"

#include <sys/stat.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <robot_interfaces/msg/det.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/header.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "detector_backend.hpp"
#include "rknn_yolov6/bounded_queue.hpp"

namespace rknn_yolov6 {
namespace {

constexpr std::size_t kQueueCapacity = 2;

// 保存单帧图像、推理输出及 ROS 时间信息，贯穿两个处理阶段。
struct FrameData {
    sensor_msgs::msg::Image::ConstSharedPtr input_message;
    std_msgs::msg::Header header;
    cv::Mat image;
    std::uint64_t offline_index{0};
    std::unique_ptr<detail::DetectorBackendFrameResult> backend_result;
};

}  // namespace

// 集中管理 ROS 接口、检测后端和有界双阶段处理队列。
struct RknnYolov6Node::Implementation {
    // 读取参数、初始化后端并启动 ROS 接口和处理线程。
    explicit Implementation(RknnYolov6Node *node) : node_(node) {
        // 先读取并校验配置，再准备推理后端和 ROS 接口。
        read_parameters();
        backend_ = detail::create_detector_backend(backend_config_, node_->get_logger(), node_->get_clock());
        create_ros_interfaces();

        // ROS 接口就绪后启动后处理线程和推理线程。
        started_at_        = std::chrono::steady_clock::now();
        last_report_at_    = started_at_;
        processing_thread_ = std::thread(&Implementation::run_processing_stage, this);
        inference_thread_  = std::thread(&Implementation::run_inference_stage, this);
    }

    // 关闭队列并等待工作线程释放所有帧结果。
    ~Implementation() {
        stopping_.store(true);
        input_queue_.close();

        // 先等待推理结束，再关闭输出队列并等待后处理排空。
        if (inference_thread_.joinable()) {
            inference_thread_.join();
        }
        output_queue_.close();
        if (processing_thread_.joinable()) {
            processing_thread_.join();
        }
    }

    // 声明 ROS 参数并校验离线输入输出配置。
    void read_parameters() {
        // 后端资源与检测阈值参数由对应 adapter 使用。
        backend_config_.model_path           = node_->declare_parameter<std::string>("model_path", "");
        backend_config_.labels_path          = node_->declare_parameter<std::string>("labels_path", "");
        backend_config_.confidence_threshold = static_cast<float>(node_->declare_parameter<double>("confidence_threshold", 0.30));
        backend_config_.nms_threshold        = static_cast<float>(node_->declare_parameter<double>("nms_threshold", 0.30));
        backend_config_.print_perf_detail    = node_->declare_parameter<bool>("print_perf_detail", false);
        backend_config_.use_multi_npu_core   = node_->declare_parameter<bool>("use_multi_npu_core", false);
        backend_config_.haar_cascade_path    = node_->declare_parameter<std::string>("haar_cascade_path", "");

        // ROS 输入输出话题及实时处理开关。
        input_topic_      = node_->declare_parameter<std::string>("input_topic", "/camera/image_raw");
        detections_topic_ = node_->declare_parameter<std::string>("detections_topic", "/ai_msg_det");
        annotated_topic_  = node_->declare_parameter<std::string>("annotated_topic", "/camera/image_det");
        enabled_.store(node_->declare_parameter<bool>("enabled", true));
        always_process_ = node_->declare_parameter<bool>("always_process", false);

        // 离线图片和输出目录仍由共享 ROS 流程管理。
        offline_mode_        = node_->declare_parameter<bool>("is_offline_image_mode", false);
        offline_images_path_ = node_->declare_parameter<std::string>("offline_images_path", "");
        offline_output_path_ = node_->declare_parameter<std::string>("offline_output_path", "");
        if (offline_mode_ && (offline_images_path_.empty() || offline_output_path_.empty())) {
            throw std::runtime_error("offline image mode requires offline_images_path and offline_output_path");
        }
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

    // 接收符合启用状态及订阅状态的 RGB 图像并送入输入队列。
    void receive_image(sensor_msgs::msg::Image::ConstSharedPtr message) {
        // 实时模式下按启用状态和订阅需求决定是否接收图像。
        if (offline_mode_ || !enabled_.load()) {
            return;
        }
        if (!always_process_ && detections_publisher_->get_subscription_count() == 0 && annotated_publisher_->get_subscription_count() == 0) {
            return;
        }

        // 校验消息布局，保证下游取得完整的 rgb8 图像数据。
        const auto row_size  = static_cast<std::size_t>(message->width) * 3;
        const auto data_size = static_cast<std::size_t>(message->step) * message->height;
        if (message->encoding != "rgb8" || message->width == 0 || message->height == 0 || message->step < row_size || message->data.size() < data_size) {
            RCLCPP_WARN_THROTTLE(node_->get_logger(), *node_->get_clock(), 2000, "expected a complete rgb8 image");
            return;
        }

        // 克隆图像像素，确保异步推理不依赖回调期间的消息内存。
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
            // 离线图片复用同一套推理和后处理队列。
            run_offline_images();
        } else {
            // 实时模式从输入队列取帧，推理成功后交给输出队列。
            while (auto frame = input_queue_.wait_and_pop()) {
                if (stopping_.load()) {
                    break;
                }
                if (run_inference(*frame)) {
                    queue_inference_result(std::move(frame));
                }
            }
        }

        // 通知后处理线程：不会再有新的推理结果。
        output_queue_.close();
    }

    // 将当前图像交给所选后端推理并保存其私有帧结果。
    bool run_inference(FrameData &frame) {
        frame.backend_result = backend_->infer(frame.image);
        return frame.backend_result != nullptr;
    }

    // 推入结果处理队列；被淘汰帧由其后端结果自动释放资源。
    void queue_inference_result(std::shared_ptr<FrameData> frame) { output_queue_.push(std::move(frame)); }

    // 从外部图片目录构造离线帧并送入实时处理路径。
    void run_offline_images() {
        // 展开图片匹配模式，并在开始处理前确认输出目录可用。
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

            // 统一转为 RGB，并为离线结果生成对应的 ROS 头信息。
            auto frame = std::make_shared<FrameData>();
            cv::cvtColor(bgr_image, frame->image, cv::COLOR_BGR2RGB);
            frame->offline_index   = index;
            frame->header.stamp    = node_->now();
            frame->header.frame_id = "image";

            // 离线帧进入与实时帧相同的推理、后处理链路。
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

    // 从结果处理队列取帧并发布检测结果及标注图像。
    void run_processing_stage() {
        while (auto frame = output_queue_.wait_and_pop()) {
            try {
                // 正常路径完成后处理、发布和离线保存。
                process_frame(*frame);
            } catch (const std::exception &error) {
                // 异常帧不影响后续处理；帧结果析构时释放后端资源。
                RCLCPP_ERROR(node_->get_logger(), "frame processing failed: %s", error.what());
            }
        }
    }

    // 后处理单帧检测结果，绘制标注、发布消息并保存离线图像。
    void process_frame(FrameData &frame) {
        // 通过统一 seam 将后端私有帧状态转换为 Detection。
        auto detections = backend_->detections(*frame.backend_result);
        frame.backend_result.reset();

        // 构造带原始图像头信息和尺寸的检测消息，并绘制标注框。
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

        // 发布检测结果；有图像订阅者或处于离线模式时发布标注图像。
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

        // 离线模式额外保存编号图片，随后统一报告处理速率。
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
    std::string input_topic_;
    std::string detections_topic_;
    std::string annotated_topic_;
    std::string offline_images_path_;
    std::string offline_output_path_;
    bool always_process_{false};
    bool offline_mode_{false};
    std::atomic<bool> enabled_{true};
    std::atomic<bool> stopping_{false};

    // 后端必须晚于队列销毁，以便残留帧结果先归还后端资源。
    detail::DetectorBackendConfig backend_config_;
    std::unique_ptr<detail::DetectorBackend> backend_;

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
};

// 使用 ROS 2 参数创建检测节点实现。
RknnYolov6Node::RknnYolov6Node(const rclcpp::NodeOptions &options) : Node("rknn_yolov6", options), implementation_(std::make_unique<Implementation>(this)) {}

// 先销毁实现对象，确保工作线程在 ROS 节点接口前停止。
RknnYolov6Node::~RknnYolov6Node() = default;

}  // namespace rknn_yolov6
