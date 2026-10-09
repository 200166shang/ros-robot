#ifndef IMG_ENCODE__JPEG_ENCODER_BACKEND_HPP_
#define IMG_ENCODE__JPEG_ENCODER_BACKEND_HPP_

#include <cstdint>
#include <memory>
#include <opencv2/core/mat.hpp>
#include <string>
#include <vector>

namespace img_encode {

// 定义 RGB8 到 JPEG 字节的内部替换点，具体实现由构建选项决定。
class JpegEncoderBackend {
public:
    // 允许通过基类指针安全释放不同编码 adapter。
    virtual ~JpegEncoderBackend() = default;

    // 将连续 RGB8 图像编码为 JPEG 字节，失败时说明原因。
    virtual bool encode(const cv::Mat& rgb, std::vector<uint8_t>& jpeg, std::string& error) = 0;
};

// 创建当前构建配置对应的软件或硬件编码 adapter。
std::unique_ptr<JpegEncoderBackend> create_jpeg_encoder_backend(int quality);

}  // namespace img_encode

#endif  // IMG_ENCODE__JPEG_ENCODER_BACKEND_HPP_
