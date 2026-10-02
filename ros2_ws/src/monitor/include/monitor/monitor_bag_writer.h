#pragma once

#include <memory>
#include <string>

#include "monitor/ros2_types.hpp"

namespace rosbag2_cpp {
namespace writers {
class SequentialWriter;
}
}  // namespace rosbag2_cpp

namespace monitor {
class MonitorBagWriter {
public:
    MonitorBagWriter(const std::string &uri, const std::string &topic);
    ~MonitorBagWriter();

    MonitorBagWriter(const MonitorBagWriter &) = delete;
    MonitorBagWriter &operator=(const MonitorBagWriter &) = delete;

    void Write(const MonitorInfo &message, int64_t timestamp_ns);

private:
    std::unique_ptr<rosbag2_cpp::writers::SequentialWriter> writer_;
    std::string topic_;
};
}  // namespace monitor
