#include "usb_camera/v4l2_camera.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <unistd.h>

namespace usb_camera {

V4l2Camera::~V4l2Camera() { close_device(); }

int V4l2Camera::xioctl(unsigned long request, void * argument) {
  int result;
  do { result = ioctl(fd_, request, argument); } while (result < 0 && errno == EINTR);
  return result;
}

bool V4l2Camera::open_device(const std::string & device, uint32_t width, uint32_t height,
                             uint32_t fps, std::string & error) {
  close_device();
  fd_ = ::open(device.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
  if (fd_ < 0) { error = "open " + device + ": " + std::strerror(errno); return false; }

  v4l2_capability capability{};
  if (xioctl(VIDIOC_QUERYCAP, &capability) < 0 ||
      !(capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) ||
      !(capability.capabilities & V4L2_CAP_STREAMING)) {
    error = device + " is not a streaming capture device"; close_device(); return false;
  }

  v4l2_format format{};
  format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  format.fmt.pix.width = width;
  format.fmt.pix.height = height;
  format.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
  format.fmt.pix.field = V4L2_FIELD_ANY;
  if (xioctl(VIDIOC_S_FMT, &format) < 0 || format.fmt.pix.pixelformat != V4L2_PIX_FMT_MJPEG) {
    error = "camera does not accept MJPEG at requested size"; close_device(); return false;
  }
  width_ = format.fmt.pix.width;
  height_ = format.fmt.pix.height;

  v4l2_streamparm stream_parameter{};
  stream_parameter.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  stream_parameter.parm.capture.timeperframe.numerator = 1;
  stream_parameter.parm.capture.timeperframe.denominator = fps;
  xioctl(VIDIOC_S_PARM, &stream_parameter);

  v4l2_requestbuffers request{};
  request.count = 4;
  request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  request.memory = V4L2_MEMORY_MMAP;
  if (xioctl(VIDIOC_REQBUFS, &request) < 0 || request.count < 2) {
    error = "VIDIOC_REQBUFS failed"; close_device(); return false;
  }

  buffers_.resize(request.count);
  for (uint32_t index = 0; index < request.count; ++index) {
    v4l2_buffer buffer{};
    buffer.type = request.type;
    buffer.memory = request.memory;
    buffer.index = index;
    if (xioctl(VIDIOC_QUERYBUF, &buffer) < 0) {
      error = "VIDIOC_QUERYBUF failed"; close_device(); return false;
    }
    void * mapped = mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, buffer.m.offset);
    if (mapped == MAP_FAILED) {
      error = "mmap failed"; close_device(); return false;
    }
    buffers_[index] = {mapped, buffer.length};
    if (xioctl(VIDIOC_QBUF, &buffer) < 0) {
      error = "VIDIOC_QBUF failed"; close_device(); return false;
    }
  }

  auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if (xioctl(VIDIOC_STREAMON, &type) < 0) {
    error = "VIDIOC_STREAMON failed"; close_device(); return false;
  }
  streaming_ = true;
  return true;
}

bool V4l2Camera::capture(std::vector<uint8_t> & jpeg, int timeout_ms, std::string & error) {
  if (fd_ < 0) { error = "camera is closed"; return false; }
  fd_set descriptors;
  FD_ZERO(&descriptors);
  FD_SET(fd_, &descriptors);
  timeval timeout{timeout_ms / 1000, (timeout_ms % 1000) * 1000};
  const int ready = select(fd_ + 1, &descriptors, nullptr, nullptr, &timeout);
  if (ready <= 0) { error = ready == 0 ? "capture timeout" : std::strerror(errno); return false; }

  v4l2_buffer buffer{};
  buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  buffer.memory = V4L2_MEMORY_MMAP;
  if (xioctl(VIDIOC_DQBUF, &buffer) < 0) { error = "VIDIOC_DQBUF failed"; return false; }

  bool valid = buffer.index < buffers_.size() && buffer.bytesused >= 4 &&
    buffer.bytesused <= buffers_[buffer.index].length;
  if (valid) {
    const auto * begin = static_cast<const uint8_t *>(buffers_[buffer.index].data);
    valid = begin[0] == 0xff && begin[1] == 0xd8;
    if (valid) jpeg.assign(begin, begin + buffer.bytesused);  // copy before returning the buffer
  }
  const int queue_result = xioctl(VIDIOC_QBUF, &buffer);
  if (!valid) error = "invalid JPEG frame";
  if (queue_result < 0) { error = "VIDIOC_QBUF failed"; return false; }
  return valid;
}

void V4l2Camera::close_device() {
  if (fd_ >= 0 && streaming_) {
    auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    ioctl(fd_, VIDIOC_STREAMOFF, &type);
  }
  streaming_ = false;
  for (auto & buffer : buffers_) {
    if (buffer.data && buffer.data != MAP_FAILED) munmap(buffer.data, buffer.length);
  }
  buffers_.clear();
  if (fd_ >= 0) ::close(fd_);
  fd_ = -1;
  width_ = height_ = 0;
}

}  // namespace usb_camera
