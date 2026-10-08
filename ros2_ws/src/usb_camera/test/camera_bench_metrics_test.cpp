#include "usb_camera/camera_bench_metrics.hpp"

#include <gtest/gtest.h>

namespace usb_camera {
namespace {
CameraBenchMetrics metrics() { return CameraBenchMetrics({"/dev/video\"2", 640, 480, 30, 2.0}); }

TEST(CameraBenchMetricsTest, ReportsSteadyDeliveryAndAverages) {
    auto subject = metrics();
    for (uint32_t sequence = 10; sequence < 16; ++sequence) {
        subject.observe_capture(sequence, 1000);
        subject.observe_publish();
        subject.observe_receive(4.0);
    }
    const auto result = subject.summarize(640, 480);
    EXPECT_EQ(result.capture_count, 6u);
    EXPECT_EQ(result.publish_count, 6u);
    EXPECT_EQ(result.receive_count, 6u);
    EXPECT_EQ(result.sequence_gaps, 0u);
    EXPECT_EQ(result.publish_receive_difference, 0);
    EXPECT_DOUBLE_EQ(result.capture_fps, 3.0);
    EXPECT_DOUBLE_EQ(result.publish_fps, 3.0);
    EXPECT_DOUBLE_EQ(result.receive_fps, 3.0);
    EXPECT_DOUBLE_EQ(result.average_latency_ms, 4.0);
    EXPECT_DOUBLE_EQ(result.average_jpeg_bytes, 1000.0);
}

TEST(CameraBenchMetricsTest, CountsSequenceGapsAndAggregateDeliveryDifference) {
    auto subject = metrics();
    subject.observe_capture(100, 500);
    subject.observe_capture(101, 700);
    subject.observe_capture(104, 900);
    subject.observe_publish();
    subject.observe_publish();
    subject.observe_publish();
    subject.observe_receive(2.0);
    subject.observe_receive(6.0);
    const auto result = subject.summarize(800, 600);
    EXPECT_EQ(result.sequence_gaps, 2u);
    EXPECT_EQ(result.publish_receive_difference, 1);
    EXPECT_DOUBLE_EQ(result.average_latency_ms, 4.0);
    EXPECT_DOUBLE_EQ(result.average_jpeg_bytes, 700.0);
    EXPECT_EQ(result.actual_width, 800u);
    EXPECT_EQ(result.actual_height, 600u);
}

TEST(CameraBenchMetricsTest, SerializesCsvAndConciseSummary) {
    auto subject = metrics();
    subject.observe_capture(7, 1024);
    subject.observe_publish();
    subject.observe_receive(1.25);
    const auto result = subject.summarize(640, 480);
    EXPECT_EQ(CameraBenchMetrics::csv_header(),
              "device,requested_width,requested_height,actual_width,actual_height,requested_fps,"
              "duration_seconds,capture_count,capture_fps,publish_count,publish_fps,receive_count,"
              "receive_fps,sequence_gaps,publish_receive_difference,average_latency_ms,average_"
              "jpeg_bytes");
    EXPECT_NE(CameraBenchMetrics::csv_row(result).find("\"/dev/video\"\"2\""), std::string::npos);
    EXPECT_NE(CameraBenchMetrics::csv_row(result).find(",640,480,640,480,30,2,"),
              std::string::npos);
    EXPECT_NE(CameraBenchMetrics::console_summary(result).find("capture 1 (0.50 fps)"),
              std::string::npos);
}

}  // namespace
}  // namespace usb_camera
