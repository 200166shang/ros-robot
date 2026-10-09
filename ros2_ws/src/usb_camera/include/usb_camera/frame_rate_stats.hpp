#pragma once

#include <chrono>
#include <cstdint>

namespace usb_camera {

struct FpsSnapshot {
    double capture_fps{0.0};
    double publish_fps{0.0};
};

class FrameRateStats {
private:
    using Clock = std::chrono::steady_clock;

public:
    // 初始化一个五秒速率统计窗口。
    FrameRateStats() : window_start_(Clock::now()) {}

    // 记录成功采集的一帧。
    void onCaptured() { ++captured_; }

    // 记录一次已发布的图像消息。
    void onPublished() { ++published_; }

    // 到达统计周期时输出速率快照，并开始新的窗口。
    bool reportIfDue(FpsSnapshot& snapshot) {
        const auto now = Clock::now();
        if (now - window_start_ < std::chrono::seconds(5)) {
            return false;
        }

        const double elapsed_seconds = std::chrono::duration<double>(now - window_start_).count();
        snapshot.capture_fps         = captured_ / elapsed_seconds;
        snapshot.publish_fps         = published_ / elapsed_seconds;
        captured_                    = 0;
        published_                   = 0;
        window_start_                = now;
        return true;
    }

    // 相机暂停、无订阅者或采集失败时丢弃当前窗口，避免把空闲时间算入 FPS。
    void resetWindow() {
        captured_     = 0;
        published_    = 0;
        window_start_ = Clock::now();
    }

private:
    uint64_t captured_{0};
    uint64_t published_{0};
    Clock::time_point window_start_;
};

}  // namespace usb_camera
