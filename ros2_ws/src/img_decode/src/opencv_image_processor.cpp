#include <algorithm>
#include <limits>
#include <opencv2/core/fast_math.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "img_decode/image_processor.hpp"

namespace img_decode {
namespace {

class OpenCvImageProcessor final : public ImageProcessor {
public:
    // 通过 OpenCV 将 JPEG 解码为 RGB 并执行软件缩放。
    bool process(const std::vector<uint8_t> &jpeg, double scale, DecodedImage &image, std::string &error) override {
        // 先检查输入数据是否为空或超出 OpenCV 可接受的长度。
        if (jpeg.empty()) {
            error = "compressed image is empty";
            return false;
        }
        if (jpeg.size() > static_cast<size_t>(std::numeric_limits<int>::max())) {
            error = "compressed image exceeds OpenCV's supported input size";
            return false;
        }

        // 将 JPEG 字节包装成 OpenCV 输入矩阵并解码为 BGR 图像。
        cv::Mat encoded(1, static_cast<int>(jpeg.size()), CV_8UC1, const_cast<uint8_t *>(jpeg.data()));
        cv::Mat bgr = cv::imdecode(encoded, cv::IMREAD_COLOR);
        if (bgr.empty()) {
            error = "OpenCV could not decode JPEG";
            return false;
        }

        // 转成 ROS 输出所需的 RGB 通道顺序。
        cv::Mat rgb;
        cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);

        // 按 OpenCV 的尺寸舍入规则计算目标大小，并在需要时执行面积插值缩放。
        const int output_width  = std::max(1, cvRound(rgb.cols * scale));
        const int output_height = std::max(1, cvRound(rgb.rows * scale));
        if (output_width != rgb.cols || output_height != rgb.rows) {
            cv::resize(rgb, rgb, cv::Size(output_width, output_height), 0.0, 0.0, cv::INTER_AREA);
        }

        // 保证像素连续后复制成无行间填充的 RGB 字节数组。
        if (!rgb.isContinuous()) {
            rgb = rgb.clone();
        }

        image.width  = static_cast<uint32_t>(rgb.cols);
        image.height = static_cast<uint32_t>(rgb.rows);
        image.rgb.assign(rgb.data, rgb.data + rgb.total() * rgb.elemSize());
        return true;
    }
};

}  // namespace

// 返回使用 OpenCV 软件路径的图像处理 Adapter。
std::unique_ptr<ImageProcessor> make_image_processor(uint32_t, uint32_t) { return std::make_unique<OpenCvImageProcessor>(); }

// 标识 OpenCV 软件处理路径，便于启动日志记录。
const char *image_processor_backend() { return "OpenCV"; }

}  // namespace img_decode
