#include <memory>
#include <string>
#include <utility>

#include "rclcpp/rclcpp.hpp"
#include "src/CYdLidar.h"
#include "ydlidar/ydlidar_node.hpp"

namespace {

class YdLidarSdkSource final : public ydlidar::LidarSource {
 public:
  bool initialize(const ydlidar::Configuration &configuration) override {
    laser_.setlidaropt(
        LidarPropSerialPort, configuration.port.c_str(), configuration.port.size());
    laser_.setlidaropt(LidarPropIgnoreArray,
                       configuration.ignore_array.c_str(),
                       configuration.ignore_array.size());
    set(LidarPropSerialBaudrate, configuration.baudrate);
    set(LidarPropLidarType, configuration.lidar_type);
    set(LidarPropDeviceType, configuration.device_type);
    set(LidarPropSampleRate, configuration.sample_rate);
    set(LidarPropAbnormalCheckCount, configuration.abnormal_check_count);
    set(LidarPropFixedResolution, configuration.fixed_resolution);
    set(LidarPropReversion, configuration.reversion);
    set(LidarPropInverted, configuration.inverted);
    set(LidarPropAutoReconnect, configuration.auto_reconnect);
    set(LidarPropSingleChannel, configuration.single_channel);
    set(LidarPropIntenstiy, configuration.intensity);
    set(LidarPropSupportMotorDtrCtrl, configuration.support_motor_dtr);
    set(LidarPropMaxAngle, configuration.angle_max);
    set(LidarPropMinAngle, configuration.angle_min);
    set(LidarPropMaxRange, configuration.range_max);
    set(LidarPropMinRange, configuration.range_min);
    set(LidarPropScanFrequency, configuration.frequency);
    return laser_.initialize();
  }

  bool start() override { return laser_.turnOn(); }
  bool stop() override { return laser_.turnOff(); }

  bool read(ydlidar::Scan &destination) override {
    LaserScan source;
    if (!laser_.doProcessSimple(source)) {
      return false;
    }
    destination.stamp_ns = source.stamp;
    destination.angle_min = source.config.min_angle;
    destination.angle_max = source.config.max_angle;
    destination.angle_increment = source.config.angle_increment;
    destination.scan_time = source.config.scan_time;
    destination.time_increment = source.config.time_increment;
    destination.range_min = source.config.min_range;
    destination.range_max = source.config.max_range;
    destination.points.clear();
    destination.points.reserve(source.points.size());
    for (const auto &point : source.points) {
      destination.points.push_back({point.angle, point.range, point.intensity});
    }
    return true;
  }

  void disconnect() override { laser_.disconnecting(); }
  std::string error() const override { return laser_.DescribeError(); }

 private:
  template<typename T>
  void set(int property, const T &value) {
    laser_.setlidaropt(property, &value, sizeof(T));
  }

  CYdLidar laser_;
};

}  // namespace

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<YdLidarNode>(std::make_unique<YdLidarSdkSource>());
    rclcpp::spin(node);
  } catch (const std::exception &error) {
    RCLCPP_FATAL(rclcpp::get_logger("ydlidar"), "YDLIDAR driver failed: %s", error.what());
  }
  rclcpp::shutdown();
  return 0;
}
