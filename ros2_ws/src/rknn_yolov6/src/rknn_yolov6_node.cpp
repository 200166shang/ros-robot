#include "rknn_yolov6/postprocess.hpp"
#include <rknn_api.h>

#include <rclcpp/rclcpp.hpp>
#include <robot_interfaces/msg/det.hpp>
#include <robot_interfaces/msg/dets.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

class RknnYolov6Node : public rclcpp::Node {
 public:
  RknnYolov6Node() : Node("rknn_yolov6") {
    model_path_ = declare_parameter<std::string>("model_path", "");
    labels_path_ = declare_parameter<std::string>("labels_path", "");
    input_topic_ = declare_parameter<std::string>("input_topic", "/camera/image_raw");
    detections_topic_ = declare_parameter<std::string>("detections_topic", "/ai_msg_det");
    annotated_topic_ = declare_parameter<std::string>("annotated_topic", "/camera/image_det");
    confidence_threshold_ = declare_parameter<double>("confidence_threshold", 0.30);
    nms_threshold_ = declare_parameter<double>("nms_threshold", 0.30);
    enabled_ = declare_parameter<bool>("enabled", true);
    always_process_ = declare_parameter<bool>("always_process", false);

    load_labels();
    initialize_rknn();
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    detections_publisher_ = create_publisher<robot_interfaces::msg::Dets>(detections_topic_, qos);
    annotated_publisher_ = create_publisher<sensor_msgs::msg::Image>(annotated_topic_, qos);
    image_subscription_ = create_subscription<sensor_msgs::msg::Image>(
      input_topic_, qos, [this](sensor_msgs::msg::Image::SharedPtr message) { infer(message); });
    enable_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "/enable_detector", 10, [this](std_msgs::msg::Bool::SharedPtr message) { enabled_ = message->data; });
    started_ = std::chrono::steady_clock::now();
    RCLCPP_INFO(get_logger(), "RKNN YOLOv6 ready: model=%dx%d labels=%zu", model_width_, model_height_, labels_.size());
  }

  ~RknnYolov6Node() override {
    if (context_ != 0) rknn_destroy(context_);
  }

 private:
  void load_labels() {
    std::ifstream input(labels_path_);
    std::string line;
    while (std::getline(input, line)) if (!line.empty()) labels_.push_back(line);
    if (labels_.empty()) throw std::runtime_error("labels_path is empty or unreadable: " + labels_path_);
  }

  void initialize_rknn() {
    std::ifstream model(model_path_, std::ios::binary | std::ios::ate);
    if (!model) throw std::runtime_error("model_path is unreadable: " + model_path_);
    const auto size = model.tellg();
    model.seekg(0);
    model_data_.resize(static_cast<size_t>(size));
    if (!model.read(reinterpret_cast<char *>(model_data_.data()), size)) throw std::runtime_error("failed to read RKNN model");

    int result = rknn_init(&context_, model_data_.data(), static_cast<uint32_t>(model_data_.size()), 0, nullptr);
    if (result < 0) throw std::runtime_error("rknn_init failed: " + std::to_string(result));
    rknn_sdk_version version{};
    rknn_query(context_, RKNN_QUERY_SDK_VERSION, &version, sizeof(version));
    RCLCPP_INFO(get_logger(), "RKNN runtime=%s driver=%s", version.api_version, version.drv_version);

    if (rknn_query(context_, RKNN_QUERY_IN_OUT_NUM, &io_count_, sizeof(io_count_)) < 0 ||
        io_count_.n_input != 1 || io_count_.n_output < 3) {
      throw std::runtime_error("unexpected RKNN input/output count");
    }
    rknn_tensor_attr input_attribute{};
    input_attribute.index = 0;
    if (rknn_query(context_, RKNN_QUERY_INPUT_ATTR, &input_attribute, sizeof(input_attribute)) < 0)
      throw std::runtime_error("cannot query RKNN input");
    if (input_attribute.fmt == RKNN_TENSOR_NHWC) {
      model_height_ = input_attribute.dims[1]; model_width_ = input_attribute.dims[2]; channels_ = input_attribute.dims[3];
    } else {
      channels_ = input_attribute.dims[1]; model_height_ = input_attribute.dims[2]; model_width_ = input_attribute.dims[3];
    }
    if (channels_ != 3) throw std::runtime_error("model input is not RGB");

    for (uint32_t index = 0; index < io_count_.n_output; ++index) {
      rknn_tensor_attr attribute{};
      attribute.index = index;
      if (rknn_query(context_, RKNN_QUERY_OUTPUT_ATTR, &attribute, sizeof(attribute)) < 0)
        throw std::runtime_error("cannot query RKNN output");
      output_zero_points_.push_back(attribute.zp);
      output_scales_.push_back(attribute.scale);
    }
    outputs_.resize(io_count_.n_output);
    for (auto & output : outputs_) output.want_float = 1;
  }

  void infer(const sensor_msgs::msg::Image::SharedPtr & message) {
    if (!enabled_ || (!always_process_ && detections_publisher_->get_subscription_count() == 0 &&
                      annotated_publisher_->get_subscription_count() == 0)) return;
    if (message->encoding != "rgb8" || message->step < message->width * 3) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "expected rgb8 image");
      return;
    }
    cv::Mat source(message->height, message->width, CV_8UC3, message->data.data(), message->step);
    cv::Mat resized;
    cv::resize(source, resized, cv::Size(model_width_, model_height_), 0, 0, cv::INTER_LINEAR);
    if (!resized.isContinuous()) resized = resized.clone();

    rknn_input input{};
    input.index = 0;
    input.buf = resized.data;
    input.size = resized.total() * resized.elemSize();
    input.type = RKNN_TENSOR_UINT8;
    input.fmt = RKNN_TENSOR_NHWC;
    input.pass_through = 0;
    int result = rknn_inputs_set(context_, 1, &input);
    if (result >= 0) result = rknn_run(context_, nullptr);
    if (result >= 0) result = rknn_outputs_get(context_, io_count_.n_output, outputs_.data(), nullptr);
    if (result < 0) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000, "RKNN inference failed: %d", result);
      return;
    }

    std::vector<int> output_indices{0, 1, 2};
    std::vector<Det> detections;
    post_process(outputs_[0].want_float, outputs_[0].buf, outputs_[1].buf, outputs_[2].buf,
      model_height_, model_width_, confidence_threshold_, nms_threshold_,
      static_cast<float>(message->width) / model_width_, static_cast<float>(message->height) / model_height_,
      output_zero_points_, output_scales_, output_indices, labels_, static_cast<int>(labels_.size()), detections);

    robot_interfaces::msg::Dets detection_message;
    detection_message.header = message->header;
    detection_message.image_width = message->width;
    detection_message.image_height = message->height;
    cv::Mat annotated = source.clone();
    for (const auto & detection : detections) {
      robot_interfaces::msg::Det converted;
      converted.x1 = detection.x1; converted.y1 = detection.y1;
      converted.x2 = detection.x2; converted.y2 = detection.y2;
      converted.confidence = detection.conf; converted.class_name = detection.cls_name;
      converted.class_id = detection.cls_id; converted.object_id = detection.obj_id;
      detection_message.detections.push_back(converted);
      cv::rectangle(annotated, {detection.x1, detection.y1}, {detection.x2, detection.y2}, {0, 255, 0}, 2);
      cv::putText(annotated, detection.cls_name, {detection.x1, std::max<int>(15, detection.y1 - 4)},
                  cv::FONT_HERSHEY_SIMPLEX, 0.5, {0, 255, 0}, 1);
    }
    rknn_outputs_release(context_, io_count_.n_output, outputs_.data());
    detections_publisher_->publish(detection_message);

    if (annotated_publisher_->get_subscription_count() > 0) {
      sensor_msgs::msg::Image output;
      output.header = message->header; output.height = message->height; output.width = message->width;
      output.encoding = "rgb8"; output.is_bigendian = false; output.step = output.width * 3;
      output.data.assign(annotated.data, annotated.data + annotated.total() * annotated.elemSize());
      annotated_publisher_->publish(std::move(output));
    }
    ++frames_;
    auto now = std::chrono::steady_clock::now();
    if (now - last_report_ >= std::chrono::seconds(5)) {
      const double elapsed = std::chrono::duration<double>(now - started_).count();
      RCLCPP_INFO(get_logger(), "inference %.1f fps, detections=%zu", frames_ / elapsed, detections.size());
      last_report_ = now;
    }
  }

  std::string model_path_, labels_path_, input_topic_, detections_topic_, annotated_topic_;
  double confidence_threshold_, nms_threshold_;
  bool enabled_, always_process_;
  int model_width_{0}, model_height_{0}, channels_{0};
  rknn_context context_{0};
  rknn_input_output_num io_count_{};
  std::vector<uint8_t> model_data_;
  std::vector<rknn_output> outputs_;
  std::vector<int32_t> output_zero_points_;
  std::vector<float> output_scales_;
  std::vector<std::string> labels_;
  uint64_t frames_{0};
  std::chrono::steady_clock::time_point started_, last_report_{started_};
  rclcpp::Publisher<robot_interfaces::msg::Dets>::SharedPtr detections_publisher_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr annotated_publisher_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_subscription_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<RknnYolov6Node>());
  } catch (const std::exception & error) {
    RCLCPP_FATAL(rclcpp::get_logger("rknn_yolov6"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
