#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "jpeg_encoder_backend.hpp"

namespace img_encode {
namespace {

// 使用 OpenCV 完成 RGB 到 JPEG 的软件编码。
class OpenCvJpegEncoderBackend final : public JpegEncoderBackend {
public:
    // 保存此 adapter 使用的 JPEG 质量。
    explicit OpenCvJpegEncoderBackend(int quality) : quality_(quality) {}

    // 将 RGB 顺序转换为 OpenCV 编码器所需的 BGR 并压缩。
    bool encode(const cv::Mat& rgb, std::vector<uint8_t>& jpeg, std::string& error) override {
        cv::Mat bgr;
        cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);

        const std::vector<int> options{cv::IMWRITE_JPEG_QUALITY, quality_};
        if (!cv::imencode(".jpg", bgr, jpeg, options)) {
            error = "OpenCV JPEG encoder failed";
            return false;
        }
        return true;
    }

private:
    int quality_;
};

}  // namespace

// 创建 OpenCV 软件编码 adapter。
std::unique_ptr<JpegEncoderBackend> create_jpeg_encoder_backend(int quality) { return std::make_unique<OpenCvJpegEncoderBackend>(quality); }

}  // namespace img_encode
