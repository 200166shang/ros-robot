#pragma once

#include <cstdint>

namespace usb_camera {

class FrameDivider {
public:
    // 使用已校验的正整数帧间隔初始化抽帧器。
    explicit FrameDivider(uint32_t divider) : divider_(divider) {}

    // 记录一帧采集，并判断本帧是否应发布。
    bool shouldPublish() { return ++frame_index_ % divider_ == 0; }

private:
    uint32_t divider_;
    uint64_t frame_index_{0};
};

}  // namespace usb_camera
