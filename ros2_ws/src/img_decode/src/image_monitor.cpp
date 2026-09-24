#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <chrono>
#include <cstring>
#include <memory>
#include <string>

class ImageMonitor : public rclcpp::Node {
 public:
  ImageMonitor() : Node("image_monitor"), started_(std::chrono::steady_clock::now()) {
    topic_ = declare_parameter<std::string>("topic", "/camera/image_raw");
    snapshot_path_ = declare_parameter<std::string>("snapshot_path", "");
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    subscription_ = create_subscription<sensor_msgs::msg::Image>(
      topic_, qos, [this](sensor_msgs::msg::Image::SharedPtr message) { receive(message); });
  }

 private:
  void receive(const sensor_msgs::msg::Image::SharedPtr & message) {
    if (message->encoding != "rgb8" || message->step < message->width * 3 ||
        message->data.size() < static_cast<size_t>(message->step) * message->height) {
      RCLCPP_ERROR(get_logger(), "invalid image encoding or buffer");
      return;
    }
    ++frames_;
    if (!snapshot_path_.empty() && !saved_) {
      cv::Mat rgb(message->height, message->width, CV_8UC3, message->data.data(), message->step);
      cv::Mat bgr;
      cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
      saved_ = cv::imwrite(snapshot_path_, bgr);
      RCLCPP_INFO(get_logger(), "snapshot %s: %s", snapshot_path_.c_str(), saved_ ? "saved" : "failed");
    }
    auto current = std::chrono::steady_clock::now();
    if (current - last_report_ >= std::chrono::seconds(5)) {
      const double elapsed = std::chrono::duration<double>(current - started_).count();
      RCLCPP_INFO(get_logger(), "%ux%u %s, %.1f fps, %llu frames",
                  message->width, message->height, message->encoding.c_str(), frames_ / elapsed,
                  static_cast<unsigned long long>(frames_));
      last_report_ = current;
    }
  }

  std::string topic_, snapshot_path_;
  bool saved_{false};
  uint64_t frames_{0};
  std::chrono::steady_clock::time_point started_, last_report_{started_};
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr subscription_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ImageMonitor>());
  rclcpp::shutdown();
  return 0;
}
