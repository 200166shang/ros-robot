#pragma once

#include <cstdint>
#include <string>

namespace usb_camera {

struct CameraBenchConfig {
    std::string device;
    uint32_t width{0};
    uint32_t height{0};
    uint32_t requested_fps{0};
    double duration_seconds{0.0};
};

struct CameraBenchSummary {
    CameraBenchConfig config;
    uint32_t actual_width{0};
    uint32_t actual_height{0};
    uint64_t capture_count{0};
    uint64_t publish_count{0};
    uint64_t receive_count{0};
    uint64_t sequence_gaps{0};
    int64_t publish_receive_difference{0};
    double capture_fps{0.0};
    double publish_fps{0.0};
    double receive_fps{0.0};
    double average_latency_ms{0.0};
    double average_jpeg_bytes{0.0};
};

// Deterministic observation seam: the benchmark supplies capture, publish, and receive facts;
// this module owns gap accounting, averages, rates, and serialization.
class CameraBenchMetrics {
public:
    explicit CameraBenchMetrics(CameraBenchConfig config);
    void observe_capture(uint32_t sequence, uint64_t jpeg_bytes);
    void observe_publish();
    void observe_receive(double latency_ms);
    CameraBenchSummary summarize(uint32_t actual_width, uint32_t actual_height) const;
    static std::string csv_header();
    static std::string csv_row(const CameraBenchSummary &summary);
    static std::string console_summary(const CameraBenchSummary &summary);

private:
    CameraBenchConfig config_;
    uint64_t capture_count_{0}, publish_count_{0}, receive_count_{0};
    uint64_t sequence_gaps_{0}, jpeg_bytes_{0};
    double latency_ms_{0.0};
    uint32_t previous_sequence_{0};
    bool has_previous_sequence_{false};
};

}  // namespace usb_camera
