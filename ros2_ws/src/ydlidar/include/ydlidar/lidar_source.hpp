#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ydlidar {

struct Configuration {
  std::string port;
  std::string ignore_array;
  std::string frame_id;
  int baudrate{115200};
  int lidar_type{1};
  int device_type{0};
  int sample_rate{3};
  int abnormal_check_count{4};
  bool fixed_resolution{true};
  bool reversion{false};
  bool inverted{true};
  bool auto_reconnect{true};
  bool single_channel{true};
  bool intensity{false};
  bool support_motor_dtr{true};
  bool invalid_range_is_inf{false};
  float angle_min{0.0F};
  float angle_max{180.0F};
  float range_min{0.1F};
  float range_max{10.0F};
  float frequency{10.0F};
};

struct Point {
  float angle{0.0F};
  float range{0.0F};
  float intensity{0.0F};
};

struct Scan {
  uint64_t stamp_ns{0};
  float angle_min{0.0F};
  float angle_max{0.0F};
  float angle_increment{0.0F};
  float scan_time{0.0F};
  float time_increment{0.0F};
  float range_min{0.0F};
  float range_max{0.0F};
  std::vector<Point> points;
};

class LidarSource {
 public:
  virtual ~LidarSource() = default;
  virtual bool initialize(const Configuration &configuration) = 0;
  virtual bool start() = 0;
  virtual bool stop() = 0;
  virtual bool read(Scan &scan) = 0;
  virtual void disconnect() = 0;
  virtual std::string error() const = 0;
};

}  // namespace ydlidar
