#include "usb_camera/v4l2_camera.hpp"

#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>

namespace usb_camera {

V4l2Camera::~V4l2Camera() { close_device(); }

int V4l2Camera::xioctl(unsigned long request, void *argument) {
    int result;
    // 系统调用被信号中断时重试，避免把 EINTR 当成设备错误。
    do {
        result = ioctl(fd_, request, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}

bool V4l2Camera::open_device(
    const std::string &device, uint32_t width, uint32_t height, uint32_t fps, std::string &error) {
    // 先清理旧状态，保证重连时不会遗留文件描述符或映射区。
    close_device();
    fd_ = ::open(device.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (fd_ < 0) {
        error = "open " + device + ": " + std::strerror(errno);
        return false;
    }

    // 只接受支持视频采集和流式 I/O 的 V4L2 设备。
    v4l2_capability capability{};
    if (xioctl(VIDIOC_QUERYCAP, &capability) < 0 ||
        !(capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) ||
        !(capability.capabilities & V4L2_CAP_STREAMING)) {
        error = device + " is not a streaming capture device";
        close_device();
        return false;
    }

    // 请求相机输出 MJPEG；驱动可能调整分辨率，实际值从 format 读回。
    v4l2_format format{};
    format.type                = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    format.fmt.pix.width       = width;
    format.fmt.pix.height      = height;
    format.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
    format.fmt.pix.field       = V4L2_FIELD_ANY;
    if (xioctl(VIDIOC_S_FMT, &format) < 0 || format.fmt.pix.pixelformat != V4L2_PIX_FMT_MJPEG) {
        error = "camera does not accept MJPEG at requested size";
        close_device();
        return false;
    }
    width_  = format.fmt.pix.width;
    height_ = format.fmt.pix.height;

    // 请求帧率；当前实现忽略 S_PARM 失败，最终帧率由设备能力决定。
    v4l2_streamparm stream_parameter{};
    stream_parameter.type                                  = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    stream_parameter.parm.capture.timeperframe.numerator   = 1;
    stream_parameter.parm.capture.timeperframe.denominator = fps;
    xioctl(VIDIOC_S_PARM, &stream_parameter);

    // 申请驱动管理的 MMAP 缓冲区，并把每块缓冲区映射到本进程地址空间。
    v4l2_requestbuffers request{};
    request.count  = 4;
    request.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request.memory = V4L2_MEMORY_MMAP;
    if (xioctl(VIDIOC_REQBUFS, &request) < 0 || request.count < 2) {
        error = "VIDIOC_REQBUFS failed";
        close_device();
        return false;
    }

    buffers_.resize(request.count);
    for (uint32_t index = 0; index < request.count; ++index) {
        v4l2_buffer buffer{};
        buffer.type   = request.type;
        buffer.memory = request.memory;
        buffer.index  = index;
        if (xioctl(VIDIOC_QUERYBUF, &buffer) < 0) {
            error = "VIDIOC_QUERYBUF failed";
            close_device();
            return false;
        }
        void *mapped =
            mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, buffer.m.offset);
        if (mapped == MAP_FAILED) {
            error = "mmap failed";
            close_device();
            return false;
        }
        buffers_[index] = {mapped, buffer.length};
        // QBUF 将空缓冲区交给驱动排队，驱动之后会在其中填入相机帧。
        if (xioctl(VIDIOC_QBUF, &buffer) < 0) {
            error = "VIDIOC_QBUF failed";
            close_device();
            return false;
        }
    }

    // 所有缓冲区入队后才启动连续采集。
    auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(VIDIOC_STREAMON, &type) < 0) {
        error = "VIDIOC_STREAMON failed";
        close_device();
        return false;
    }
    streaming_ = true;
    return true;
}

bool V4l2Camera::capture(std::vector<uint8_t> &jpeg,
                         int timeout_ms,
                         std::string &error,
                         uint32_t *sequence) {
    if (fd_ < 0) {
        error = "camera is closed";
        return false;
    }
    // 先等设备变为可读，避免在非阻塞 fd 上忙等。
    fd_set descriptors;
    FD_ZERO(&descriptors);
    FD_SET(fd_, &descriptors);
    timeval timeout{timeout_ms / 1000, (timeout_ms % 1000) * 1000};
    const int ready = select(fd_ + 1, &descriptors, nullptr, nullptr, &timeout);
    if (ready <= 0) {
        error = ready == 0 ? "capture timeout" : std::strerror(errno);
        return false;
    }

    // DQBUF 取回一块已由驱动填好的缓冲区，应用暂时获得它的使用权。
    v4l2_buffer buffer{};
    buffer.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buffer.memory = V4L2_MEMORY_MMAP;
    if (xioctl(VIDIOC_DQBUF, &buffer) < 0) {
        error = "VIDIOC_DQBUF failed";
        return false;
    }
    if (sequence) *sequence = buffer.sequence;

    // 校验索引、有效长度和 JPEG 起始标记，防止读取无效映射数据。
    bool valid = buffer.index < buffers_.size() && buffer.bytesused >= 4 &&
                 buffer.bytesused <= buffers_[buffer.index].length;
    if (valid) {
        const auto *begin = static_cast<const uint8_t *>(buffers_[buffer.index].data);
        valid             = begin[0] == 0xff && begin[1] == 0xd8;
        if (valid) {
            // 复制到调用者拥有的 vector；这样缓冲区归还后，帧数据仍然有效。
            jpeg.assign(begin, begin + buffer.bytesused);
        }
    }
    // 无论 JPEG 是否有效，都尝试归还这块缓冲区以供驱动继续采集。
    const int queue_result = xioctl(VIDIOC_QBUF, &buffer);
    if (!valid) error = "invalid JPEG frame";
    if (queue_result < 0) {
        error = "VIDIOC_QBUF failed";
        return false;
    }
    return valid;
}

void V4l2Camera::close_device() {
    // 停止流后再解除映射并关闭 fd，按资源取得的逆序清理。
    if (fd_ >= 0 && streaming_) {
        auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        ioctl(fd_, VIDIOC_STREAMOFF, &type);
    }
    streaming_ = false;
    for (auto &buffer : buffers_) {
        if (buffer.data && buffer.data != MAP_FAILED) munmap(buffer.data, buffer.length);
    }
    buffers_.clear();
    if (fd_ >= 0) ::close(fd_);
    fd_    = -1;
    width_ = height_ = 0;
}

}  // namespace usb_camera
