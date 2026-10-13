// clang-format off
#include <cstddef>
#include <cstring>
#include <fcntl.h>
#include <RgaUtils.h>
#include <im2d.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
// clang-format on

#include <rockchip/mpp_buffer.h>
#include <rockchip/mpp_err.h>
#include <rockchip/mpp_frame.h>
#include <rockchip/mpp_meta.h>
#include <rockchip/mpp_packet.h>
#include <rockchip/mpp_task.h>
#include <rockchip/rk_mpi.h>
#include <rockchip/rk_mpi_cmd.h>

#include <algorithm>
#include <cstdint>
#include <cerrno>
#include <opencv2/core/fast_math.hpp>
#include <stdexcept>
#include <string>
#include <system_error>

#include "img_decode/image_processor.hpp"

namespace img_decode {
namespace {

constexpr uint32_t kStrideAlignment = 16;

// 将像素尺寸按 MPP 解码输出要求对齐。
uint32_t align_dimension(uint32_t value) { return (value + kStrideAlignment - 1) & ~(kStrideAlignment - 1); }

// 持有 RGA 可寻址的 RGB DMA32 缓冲区及导入句柄。
class Dma32RgbBuffer final {
public:
    // 从系统 DMA32 heap 分配可供 RGA 访问的 RGB 缓冲区。
    Dma32RgbBuffer(uint32_t width, uint32_t height)
        : width_(width), height_(height), stride_((width + 3U) & ~3U), size_(static_cast<size_t>(stride_) * height_ * 3) {
        const int heap_fd = open("/dev/dma_heap/system-uncached-dma32", O_RDWR | O_CLOEXEC);
        if (heap_fd < 0) {
            throw std::system_error(errno, std::generic_category(), "open RGA DMA32 heap");
        }

        DmaHeapAllocationData allocation{};
        allocation.len             = size_;
        allocation.fd_flags        = O_RDWR | O_CLOEXEC;
        const int result           = ioctl(heap_fd, _IOWR('H', 0, DmaHeapAllocationData), &allocation);
        const int allocation_error = errno;
        close(heap_fd);
        if (result < 0) {
            throw std::system_error(allocation_error, std::generic_category(), "allocate RGA DMA32 buffer");
        }
        fd_ = static_cast<int>(allocation.fd);

        data_ = mmap(nullptr, size_, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
        if (data_ == MAP_FAILED) {
            const int mapping_error = errno;
            close(fd_);
            fd_ = -1;
            throw std::system_error(mapping_error, std::generic_category(), "map RGA DMA32 buffer");
        }

        handle_ = importbuffer_fd(fd_, static_cast<int>(size_));
        if (handle_ == 0) {
            munmap(data_, size_);
            close(fd_);
            data_ = MAP_FAILED;
            fd_   = -1;
            throw std::runtime_error("import RGA DMA32 buffer failed");
        }
    }

    // 释放 RGA 导入句柄、CPU 映射和 DMA-BUF fd。
    ~Dma32RgbBuffer() {
        releasebuffer_handle(handle_);
        munmap(data_, size_);
        close(fd_);
    }

    // 禁止复制 DMA-BUF 资源所有权。
    Dma32RgbBuffer(const Dma32RgbBuffer &) = delete;
    // 禁止赋值复制 DMA-BUF 资源所有权。
    Dma32RgbBuffer &operator=(const Dma32RgbBuffer &) = delete;

    // 返回可供 CPU 拷贝像素的缓冲区起始地址。
    uint8_t *data() const { return static_cast<uint8_t *>(data_); }

    // 返回缓冲区可见宽度。
    uint32_t width() const { return width_; }

    // 返回缓冲区可见高度。
    uint32_t height() const { return height_; }

    // 返回包含 RGB 行填充的像素 stride。
    uint32_t stride() const { return stride_; }

    // 返回含可见宽度和对齐 stride 的 RGA 缓冲区描述。
    rga_buffer_t rga_buffer() const {
        return wrapbuffer_handle_t(
            handle_, static_cast<int>(width_), static_cast<int>(height_), static_cast<int>(stride_), static_cast<int>(height_), RK_FORMAT_RGB_888);
    }

private:
    struct DmaHeapAllocationData {
        uint64_t len;
        uint32_t fd;
        uint32_t fd_flags;
        uint64_t heap_flags;
    };

    uint32_t width_;
    uint32_t height_;
    uint32_t stride_;
    size_t size_;
    int fd_{-1};
    void *data_{MAP_FAILED};
    rga_buffer_handle_t handle_{0};
};

class RockchipImageProcessor final : public ImageProcessor {
public:
    // 创建 MPP JPEG 解码上下文并按配置尺寸准备输入输出缓冲区。
    RockchipImageProcessor(uint32_t max_width, uint32_t max_height) : max_width_(max_width), max_height_(max_height) { initialize(); }

    // 释放 MPP context 和缓冲区组，归还硬件 Adapter 持有的资源。
    ~RockchipImageProcessor() override { release(); }

    // 通过 MPP task 队列解码 JPEG，再由 RGA 缩放 RGB 输出。
    bool process(const std::vector<uint8_t> &jpeg, double scale, DecodedImage &image, std::string &error) override {
        // 检查输入数据及 MPP packet 缓冲区容量。
        if (jpeg.empty()) {
            error = "compressed image is empty";
            return false;
        }
        if (jpeg.size() > mpp_buffer_get_size(packet_buffer_)) {
            error = "compressed image exceeds the configured MPP packet buffer";
            return false;
        }

        // 复制 JPEG 到 MPP 管理的 packet 缓冲区，并设置本次输入长度。
        std::memcpy(packet_data_, jpeg.data(), jpeg.size());
        mpp_packet_set_pos(packet_, packet_data_);
        mpp_packet_set_length(packet_, jpeg.size());

        // 从 MPP 输入队列获取 task，提交 JPEG packet 和预分配的输出 frame。
        MppTask task = nullptr;
        MPP_RET ret  = mpi_->poll(context_, MPP_PORT_INPUT, MPP_POLL_BLOCK);
        if (ret == MPP_OK) {
            ret = mpi_->dequeue(context_, MPP_PORT_INPUT, &task);
        }
        if (ret != MPP_OK || task == nullptr) {
            error = "MPP could not acquire an input task: " + std::to_string(ret);
            return false;
        }

        mpp_task_meta_set_packet(task, KEY_INPUT_PACKET, packet_);
        mpp_task_meta_set_frame(task, KEY_OUTPUT_FRAME, frame_);
        ret = mpi_->enqueue(context_, MPP_PORT_INPUT, task);
        if (ret != MPP_OK) {
            error = "MPP could not submit an input task: " + std::to_string(ret);
            return false;
        }

        // 等待解码完成并取回包含输出 frame 的 task。
        ret = mpi_->poll(context_, MPP_PORT_OUTPUT, MPP_POLL_BLOCK);
        if (ret == MPP_OK) {
            ret = mpi_->dequeue(context_, MPP_PORT_OUTPUT, &task);
        }
        if (ret != MPP_OK || task == nullptr) {
            error = "MPP could not acquire an output task: " + std::to_string(ret);
            return false;
        }

        // 取得解码 frame，经 RGA 缩放并整理为连续 RGB 字节数据。
        MppFrame output_frame = nullptr;
        mpp_task_meta_get_frame(task, KEY_OUTPUT_FRAME, &output_frame);
        if (output_frame == nullptr) {
            error = "MPP output task did not contain a decoded frame";
        } else {
            resize_frame(output_frame, scale, image, error);
        }

        // 将输出 task 交还给 MPP；若处理成功但归还失败，则向调用方报告错误。
        const MPP_RET output_ret = mpi_->enqueue(context_, MPP_PORT_OUTPUT, task);
        if (output_ret != MPP_OK && error.empty()) {
            error = "MPP could not release an output task: " + std::to_string(output_ret);
        }
        return error.empty();
    }

private:
    // 初始化 MPP decoder、RGB 格式和解码所需的缓冲区。
    void initialize() {
        MPP_RET ret = mpp_create(&context_, &mpi_);
        if (ret == MPP_OK) {
            RK_U32 enable_parser_split = 1;
            ret                        = mpi_->control(context_, MPP_DEC_SET_PARSER_SPLIT_MODE, &enable_parser_split);
        }
        if (ret == MPP_OK) {
            ret = mpp_init(context_, MPP_CTX_DEC, MPP_VIDEO_CodingMJPEG);
        }
        if (ret == MPP_OK) {
            MppFrameFormat format = MPP_FMT_RGB888;
            ret                   = mpi_->control(context_, MPP_DEC_SET_OUTPUT_FORMAT, &format);
        }
        if (ret == MPP_OK) {
            ret = mpp_buffer_group_get_internal(&frame_group_, MPP_BUFFER_TYPE_ION);
        }
        if (ret == MPP_OK) {
            ret = mpp_buffer_group_get_internal(&packet_group_, MPP_BUFFER_TYPE_ION);
        }

        const uint32_t horizontal_stride = align_dimension(max_width_);
        const uint32_t vertical_stride   = align_dimension(max_height_);
        const size_t frame_buffer_size   = static_cast<size_t>(horizontal_stride) * vertical_stride * 4;
        if (ret == MPP_OK) {
            ret = mpp_frame_init(&frame_);
        }
        if (ret == MPP_OK) {
            ret = mpp_buffer_get(frame_group_, &frame_buffer_, frame_buffer_size);
        }
        if (ret == MPP_OK) {
            ret = mpp_buffer_get(packet_group_, &packet_buffer_, frame_buffer_size);
        }
        if (ret == MPP_OK) {
            ret = mpp_packet_init_with_buffer(&packet_, packet_buffer_);
        }
        if (ret == MPP_OK) {
            packet_data_ = static_cast<uint8_t *>(mpp_buffer_get_ptr(packet_buffer_));
            if (packet_data_ == nullptr) {
                ret = MPP_ERR_NULL_PTR;
            }
        }
        if (ret == MPP_OK) {
            mpp_frame_set_width(frame_, max_width_);
            mpp_frame_set_height(frame_, max_height_);
            mpp_frame_set_hor_stride(frame_, horizontal_stride);
            mpp_frame_set_ver_stride(frame_, vertical_stride);
            mpp_frame_set_fmt(frame_, MPP_FMT_RGB888);
            mpp_frame_set_buffer(frame_, frame_buffer_);
        }
        if (ret != MPP_OK) {
            release();
            throw std::runtime_error("MPP JPEG decoder initialization failed: " + std::to_string(ret));
        }
    }

    // 读取 MPP RGB frame；同尺寸时按 stride 拷贝，缩放时交由 RGA 处理。
    bool resize_frame(MppFrame frame, double scale, DecodedImage &image, std::string &error) {
        // 读取解码图像的可见尺寸、对齐 stride 和底层像素缓冲区。
        const uint32_t width                    = mpp_frame_get_width(frame);
        const uint32_t height                   = mpp_frame_get_height(frame);
        const uint32_t horizontal_stride_bytes  = mpp_frame_get_hor_stride(frame);
        const uint32_t horizontal_stride_pixels = mpp_frame_get_hor_stride_pixel(frame);
        const uint32_t vertical_stride          = mpp_frame_get_ver_stride(frame);
        MppBuffer buffer                        = mpp_frame_get_buffer(frame);
        auto *pixels                            = buffer == nullptr ? nullptr : static_cast<uint8_t *>(mpp_buffer_get_ptr(buffer));

        // 确认图像未超出配置尺寸，stride、像素格式和 MPP 解码状态均有效。
        const bool valid_frame = width > 0 && height > 0 && width <= max_width_ && height <= max_height_ && horizontal_stride_bytes >= width * 3 &&
                                 horizontal_stride_pixels >= width && vertical_stride >= height && pixels != nullptr &&
                                 mpp_frame_get_fmt(frame) == MPP_FMT_RGB888 && mpp_frame_get_errinfo(frame) == 0;
        if (!valid_frame) {
            error = "MPP returned an invalid, oversized, or non-RGB frame";
            return false;
        }

        // 按 OpenCV 一致的舍入规则计算缩放尺寸，并分配紧凑 RGB 输出区。
        image.width  = static_cast<uint32_t>(std::max(1, cvRound(width * scale)));
        image.height = static_cast<uint32_t>(std::max(1, cvRound(height * scale)));
        image.rgb.resize(static_cast<size_t>(image.width) * image.height * 3);

        const size_t output_row_bytes = static_cast<size_t>(image.width) * 3;
        if (image.width == width && image.height == height) {
            // 相机当前配置不缩放；逐行跳过 MPP 对齐填充，避免无意义的 RGA 地址映射。
            for (uint32_t row = 0; row < height; ++row) {
                std::copy_n(pixels + row * horizontal_stride_bytes, output_row_bytes, image.rgb.data() + row * output_row_bytes);
            }
            return true;
        }

        // 1. 将 MPP stride 帧拷贝到 RGA 支持的 DMA32 源缓冲区。
        if (!source_buffer_ || source_buffer_->width() != width || source_buffer_->height() != height) {
            source_buffer_ = std::make_unique<Dma32RgbBuffer>(width, height);
        }
        uint8_t *source_data          = source_buffer_->data();
        const size_t source_row_bytes = static_cast<size_t>(source_buffer_->stride()) * 3;
        for (uint32_t row = 0; row < height; ++row) {
            std::copy_n(pixels + row * horizontal_stride_bytes, static_cast<size_t>(width) * 3, source_data + row * source_row_bytes);
        }

        // 2. 使用 DMA32 目标缓冲区执行真正的缩放；RGA 不直接映射 MPP 或 std::vector 虚拟地址。
        if (!destination_buffer_ || destination_buffer_->width() != image.width || destination_buffer_->height() != image.height) {
            destination_buffer_ = std::make_unique<Dma32RgbBuffer>(image.width, image.height);
        }
        const rga_buffer_t source      = source_buffer_->rga_buffer();
        const rga_buffer_t destination = destination_buffer_->rga_buffer();
        im_rect source_rect{};
        im_rect destination_rect{};
        IM_STATUS status = imcheck(source, destination, source_rect, destination_rect, IM_SYNC);

        if (status == IM_STATUS_NOERROR) {
            status = imresize(source, destination);
        }
        const bool resize_succeeded = status == IM_STATUS_SUCCESS || status == IM_STATUS_NOERROR;
        if (!resize_succeeded) {
            error = std::string("RGA resize failed: ") + imStrError(status);
            image = DecodedImage{};
            return false;
        }

        // 3. 从 DMA32 输出逐行取出可见像素，形成 ROS rgb8 的紧凑排列。
        const size_t destination_row_bytes = static_cast<size_t>(destination_buffer_->stride()) * 3;
        const uint8_t *destination_data    = destination_buffer_->data();
        for (uint32_t row = 0; row < image.height; ++row) {
            std::copy_n(destination_data + row * destination_row_bytes, output_row_bytes, image.rgb.data() + row * output_row_bytes);
        }
        return true;
    }

    // 销毁 MPP objects、buffers 和 context，按依赖顺序释放资源。
    void release() {
        if (packet_ != nullptr) {
            mpp_packet_deinit(&packet_);
            packet_ = nullptr;
        }
        if (frame_ != nullptr) {
            mpp_frame_deinit(&frame_);
            frame_ = nullptr;
        }
        if (context_ != nullptr) {
            mpp_destroy(context_);
            context_ = nullptr;
            mpi_     = nullptr;
        }
        if (packet_buffer_ != nullptr) {
            mpp_buffer_put(packet_buffer_);
            packet_buffer_ = nullptr;
        }
        if (frame_buffer_ != nullptr) {
            mpp_buffer_put(frame_buffer_);
            frame_buffer_ = nullptr;
        }
        if (packet_group_ != nullptr) {
            mpp_buffer_group_put(packet_group_);
            packet_group_ = nullptr;
        }
        if (frame_group_ != nullptr) {
            mpp_buffer_group_put(frame_group_);
            frame_group_ = nullptr;
        }
        packet_data_ = nullptr;
    }

    uint32_t max_width_;
    uint32_t max_height_;
    MppCtx context_{nullptr};
    MppApi *mpi_{nullptr};
    MppBufferGroup frame_group_{nullptr};
    MppBufferGroup packet_group_{nullptr};
    MppBuffer frame_buffer_{nullptr};
    MppBuffer packet_buffer_{nullptr};
    MppPacket packet_{nullptr};
    MppFrame frame_{nullptr};
    uint8_t *packet_data_{nullptr};
    std::unique_ptr<Dma32RgbBuffer> source_buffer_;
    std::unique_ptr<Dma32RgbBuffer> destination_buffer_;
};

}  // namespace

// 返回使用 Rockchip MPP/RGA 硬件处理路径的 Adapter。
std::unique_ptr<ImageProcessor> make_image_processor(uint32_t max_width, uint32_t max_height) {
    return std::make_unique<RockchipImageProcessor>(max_width, max_height);
}

// 标识 Rockchip 硬件处理路径，便于启动日志记录。
const char *image_processor_backend() { return "Rockchip MPP/RGA"; }

}  // namespace img_decode
