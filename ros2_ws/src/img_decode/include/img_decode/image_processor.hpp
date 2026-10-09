#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace img_decode {

struct DecodedImage {
    uint32_t width{0};
    uint32_t height{0};
    std::vector<uint8_t> rgb;
};

class ImageProcessor {
public:
    // 允许通过 Adapter 接口安全销毁具体处理实现。
    virtual ~ImageProcessor() = default;

    // 解码 JPEG 并按比例缩放为连续 RGB8 像素数据。
    virtual bool process(const std::vector<uint8_t> &jpeg, double scale, DecodedImage &image, std::string &error) = 0;
};

// 创建当前构建配置选择的图像处理 Adapter。
std::unique_ptr<ImageProcessor> make_image_processor(uint32_t max_width, uint32_t max_height);
// 返回当前构建所选择的图像处理后端名称。
const char *image_processor_backend();

}  // namespace img_decode
