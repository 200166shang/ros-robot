#include "usb_camera/camera_bench_metrics.hpp"

#include <iomanip>
#include <sstream>

namespace usb_camera {
namespace {
std::string csv_escape(const std::string &value) {
    std::string escaped = "\"";
    for (const char character : value) {
        if (character == '"') escaped += '"';
        escaped += character;
    }
    return escaped + '"';
}
}  // namespace

CameraBenchMetrics::CameraBenchMetrics(CameraBenchConfig config) : config_(std::move(config)) {}

void CameraBenchMetrics::observe_capture(uint32_t sequence, uint64_t jpeg_bytes) {
    if (has_previous_sequence_) {
        const uint32_t difference = sequence - previous_sequence_;
        if (difference > 1) sequence_gaps_ += difference - 1;
    }
    previous_sequence_     = sequence;
    has_previous_sequence_ = true;
    ++capture_count_;
    jpeg_bytes_ += jpeg_bytes;
}

void CameraBenchMetrics::observe_publish() { ++publish_count_; }

void CameraBenchMetrics::observe_receive(double latency_ms) {
    ++receive_count_;
    latency_ms_ += latency_ms;
}

CameraBenchSummary CameraBenchMetrics::summarize(uint32_t actual_width,
                                                 uint32_t actual_height) const {
    CameraBenchSummary result;
    result.config        = config_;
    result.actual_width  = actual_width;
    result.actual_height = actual_height;
    result.capture_count = capture_count_;
    result.publish_count = publish_count_;
    result.receive_count = receive_count_;
    result.sequence_gaps = sequence_gaps_;
    result.publish_receive_difference =
        static_cast<int64_t>(publish_count_) - static_cast<int64_t>(receive_count_);
    const double duration = config_.duration_seconds;
    if (duration > 0.0) {
        result.capture_fps = capture_count_ / duration;
        result.publish_fps = publish_count_ / duration;
        result.receive_fps = receive_count_ / duration;
    }
    if (receive_count_) result.average_latency_ms = latency_ms_ / receive_count_;
    if (capture_count_)
        result.average_jpeg_bytes = static_cast<double>(jpeg_bytes_) / capture_count_;
    return result;
}

std::string CameraBenchMetrics::csv_header() {
    return "device,requested_width,requested_height,actual_width,actual_height,requested_fps,"
           "duration_seconds,"
           "capture_count,capture_fps,publish_count,publish_fps,receive_count,receive_fps,sequence_"
           "gaps,"
           "publish_receive_difference,average_latency_ms,average_jpeg_bytes";
}

std::string CameraBenchMetrics::csv_row(const CameraBenchSummary &s) {
    std::ostringstream out;
    out << std::setprecision(10) << csv_escape(s.config.device) << ',' << s.config.width << ','
        << s.config.height << ',' << s.actual_width << ',' << s.actual_height << ','
        << s.config.requested_fps << ',' << s.config.duration_seconds << ',' << s.capture_count
        << ',' << s.capture_fps << ',' << s.publish_count << ',' << s.publish_fps << ','
        << s.receive_count << ',' << s.receive_fps << ',' << s.sequence_gaps << ','
        << s.publish_receive_difference << ',' << s.average_latency_ms << ','
        << s.average_jpeg_bytes;
    return out.str();
}

std::string CameraBenchMetrics::console_summary(const CameraBenchSummary &s) {
    std::ostringstream out;
    out << std::fixed << std::setprecision(2) << s.config.device << ' ' << s.actual_width << 'x'
        << s.actual_height << " requested " << s.config.requested_fps << " fps, "
        << s.config.duration_seconds << " s | capture " << s.capture_count << " (" << s.capture_fps
        << " fps), publish " << s.publish_count << " (" << s.publish_fps << " fps), receive "
        << s.receive_count << " (" << s.receive_fps << " fps), gaps " << s.sequence_gaps
        << ", pub-recv " << s.publish_receive_difference << ", latency " << s.average_latency_ms
        << " ms, JPEG " << s.average_jpeg_bytes << " B";
    return out.str();
}

}  // namespace usb_camera
