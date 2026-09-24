#include "usb_camera/v4l2_camera.hpp"

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>

class UsbCameraNode : public rclcpp::Node {
 public:
  UsbCameraNode() : Node("usb_camera"), running_(true) {
    device_ = declare_parameter<std::string>("device", "/dev/video0");
    topic_ = declare_parameter<std::string>("topic", "/image_raw/compressed");
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_link");
    width_ = declare_parameter<int>("width", 1280);
    height_ = declare_parameter<int>("height", 720);
    fps_ = declare_parameter<int>("fps", 30);
    lazy_ = declare_parameter<bool>("lazy", true);

    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(topic_, qos);
    enable_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "/enable_camera", 10, [this](std_msgs::msg::Bool::SharedPtr message) {
        enabled_.store(message->data);
      });
    worker_ = std::thread([this] { capture_loop(); });
  }

  ~UsbCameraNode() override {
    running_.store(false);
    if (worker_.joinable()) worker_.join();
    camera_.close_device();
  }

 private:
  void capture_loop() {
    std::vector<uint8_t> jpeg;
    std::string error;
    auto last_log = std::chrono::steady_clock::now() - std::chrono::seconds(10);
    uint64_t frame_count = 0;
    auto fps_start = std::chrono::steady_clock::now();
    while (rclcpp::ok() && running_.load()) {
      if (!enabled_.load() || (lazy_ && publisher_->get_subscription_count() == 0)) {
        camera_.close_device();
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        continue;
      }
      if (!camera_.is_open()) {
        if (!camera_.open_device(device_, width_, height_, fps_, error)) {
          auto now = std::chrono::steady_clock::now();
          if (now - last_log > std::chrono::seconds(2)) {
            RCLCPP_WARN(get_logger(), "%s; retrying", error.c_str());
            last_log = now;
          }
          std::this_thread::sleep_for(std::chrono::seconds(1));
          continue;
        }
        RCLCPP_INFO(get_logger(), "opened %s as MJPEG %ux%u", device_.c_str(),
                    camera_.width(), camera_.height());
      }
      if (!camera_.capture(jpeg, 2000, error)) {
        RCLCPP_WARN(get_logger(), "%s; reopening camera", error.c_str());
        camera_.close_device();
        continue;
      }
      sensor_msgs::msg::CompressedImage message;
      message.header.stamp = now();
      message.header.frame_id = frame_id_;
      message.format = "jpeg";
      message.data = jpeg;
      publisher_->publish(std::move(message));
      ++frame_count;
      auto current = std::chrono::steady_clock::now();
      if (current - fps_start >= std::chrono::seconds(5)) {
        const double seconds = std::chrono::duration<double>(current - fps_start).count();
        RCLCPP_INFO(get_logger(), "capture %.1f fps, subscribers=%zu",
                    frame_count / seconds, publisher_->get_subscription_count());
        frame_count = 0;
        fps_start = current;
      }
    }
  }

  usb_camera::V4l2Camera camera_;
  std::atomic<bool> enabled_{true};
  std::atomic<bool> running_;
  std::thread worker_;
  std::string device_, topic_, frame_id_;
  int width_, height_, fps_;
  bool lazy_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr enable_subscription_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<UsbCameraNode>());
  rclcpp::shutdown();
  return 0;
}
