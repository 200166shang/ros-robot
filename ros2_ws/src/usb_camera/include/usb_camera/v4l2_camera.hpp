#pragma once

#include <linux/videodev2.h>

#include <cstdint>
#include <string>
#include <vector>

namespace usb_camera {

class V4l2Camera {
public:
    V4l2Camera() = default;
    ~V4l2Camera();
    V4l2Camera(const V4l2Camera &) = delete;
    V4l2Camera &operator=(const V4l2Camera &) = delete;

    // 配置设备并启动采集流；失败时会释放已取得的资源。
    bool open_device(const std::string &device,
                     uint32_t width,
                     uint32_t height,
                     uint32_t fps,
                     std::string &error);
    // 等待并取出一帧 JPEG，复制到 jpeg 后再把 V4L2 缓冲区归还给驱动。
    bool capture(std::vector<uint8_t> &jpeg,
                 int timeout_ms,
                 std::string &error,
                 uint32_t *sequence = nullptr);
    // 停止采集、解除缓冲区映射并关闭设备；可重复调用。
    void close_device();
    bool is_open() const { return fd_ >= 0; }
    uint32_t width() const { return width_; }
    uint32_t height() const { return height_; }

private:
    struct Buffer {
        void *data{nullptr};
        size_t length{0};
    };
    int xioctl(unsigned long request, void *argument);

    int fd_{-1};
    bool streaming_{false};
    uint32_t width_{0};
    uint32_t height_{0};
    std::vector<Buffer> buffers_;
};

}  // namespace usb_camera
