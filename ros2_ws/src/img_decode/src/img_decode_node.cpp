#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <chrono>
#include <cstring>
#include <memory>
#include <string>

class ImageDecodeNode : public rclcpp::Node {
 public:
  ImageDecodeNode() : Node("img_decode") {
    input_topic_ = declare_parameter<std::string>("input_topic", "/image_raw/compressed");
    output_topic_ = declare_parameter<std::string>("output_topic", "/camera/image_raw");
    scale_ = declare_parameter<double>("scale", 1.0);
    frame_divider_ = std::max<int>(1, static_cast<int>(declare_parameter<int>("frame_divider", 1)));
    lazy_ = declare_parameter<bool>("lazy", true);
    if (scale_ <= 0.0 || scale_ > 1.0) throw std::runtime_error("scale must be in (0, 1]");

    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    publisher_ = create_publisher<sensor_msgs::msg::Image>(output_topic_, qos);
    timer_ = create_wall_timer(std::chrono::milliseconds(100), [this] { update_subscription(); });
    if (!lazy_) subscribe();
    RCLCPP_INFO(get_logger(), "%s -> %s, OpenCV backend", input_topic_.c_str(), output_topic_.c_str());
  }

 private:
  void update_subscription() {
    const bool needed = !lazy_ || publisher_->get_subscription_count() > 0;
    if (needed && !subscription_) subscribe();
    if (!needed && subscription_) {
      subscription_.reset();
      RCLCPP_INFO(get_logger(), "no output subscribers; decoder paused");
    }
  }

  void subscribe() {
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    subscription_ = create_subscription<sensor_msgs::msg::CompressedImage>(
      input_topic_, qos, [this](sensor_msgs::msg::CompressedImage::SharedPtr message) { decode(message); });
    RCLCPP_INFO(get_logger(), "decoder subscribed");
  }

  void decode(const sensor_msgs::msg::CompressedImage::SharedPtr & compressed) {
    if (++input_count_ % static_cast<uint64_t>(frame_divider_) != 0) return;
    cv::Mat encoded(1, static_cast<int>(compressed->data.size()), CV_8UC1,
                    const_cast<uint8_t *>(compressed->data.data()));
    cv::Mat bgr = cv::imdecode(encoded, cv::IMREAD_COLOR);
    if (bgr.empty()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "JPEG decode failed");
      return;
    }
    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    if (scale_ != 1.0) cv::resize(rgb, rgb, cv::Size(), scale_, scale_, cv::INTER_AREA);
    if (!rgb.isContinuous()) rgb = rgb.clone();

    sensor_msgs::msg::Image output;
    output.header = compressed->header;
    output.height = static_cast<uint32_t>(rgb.rows);
    output.width = static_cast<uint32_t>(rgb.cols);
    output.encoding = "rgb8";
    output.is_bigendian = false;
    output.step = output.width * 3;
    output.data.assign(rgb.data, rgb.data + rgb.total() * rgb.elemSize());
    publisher_->publish(std::move(output));
  }

  std::string input_topic_, output_topic_;
  double scale_;
  int frame_divider_;
  bool lazy_;
  uint64_t input_count_{0};
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr publisher_;
  rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr subscription_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ImageDecodeNode>());
  rclcpp::shutdown();
  return 0;
}
