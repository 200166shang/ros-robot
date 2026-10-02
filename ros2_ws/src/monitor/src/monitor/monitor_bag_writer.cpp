#include "monitor/monitor_bag_writer.h"

#include <cstring>
#include <stdexcept>

#include "rclcpp/serialization.hpp"
#include "rclcpp/serialized_message.hpp"
#include "rcutils/allocator.h"
#include "rcutils/types/uint8_array.h"
#include "rmw/rmw.h"
#include "rosbag2_cpp/converter_options.hpp"
#include "rosbag2_cpp/storage_options.hpp"
#include "rosbag2_cpp/writers/sequential_writer.hpp"
#include "rosbag2_storage/serialized_bag_message.hpp"
#include "rosbag2_storage/topic_metadata.hpp"

namespace monitor {
MonitorBagWriter::MonitorBagWriter(const std::string &uri, const std::string &topic)
    : writer_(new rosbag2_cpp::writers::SequentialWriter()), topic_(topic) {
    rosbag2_cpp::StorageOptions storage_options;
    storage_options.uri        = uri;
    storage_options.storage_id = "sqlite3";

    // 输入和输出都使用当前 RMW 的序列化格式，避免 bag 写入时发生不必要的转换。
    const std::string format = rmw_get_serialization_format();
    rosbag2_cpp::ConverterOptions converter_options{format, format};

    try {
        writer_->open(storage_options, converter_options);

        rosbag2_storage::TopicMetadata metadata;
        metadata.name                 = topic_;
        metadata.type                 = "monitor_interfaces/msg/MonitorInfo";
        metadata.serialization_format = format;
        // rosbag2 要求先注册 topic 类型，再写入该 topic 的序列化消息。
        writer_->create_topic(metadata);
    } catch (const std::exception &error) {
        throw std::runtime_error("cannot open rosbag URI '" + uri + "': " + error.what());
    }
}

MonitorBagWriter::~MonitorBagWriter() = default;

void MonitorBagWriter::Write(const MonitorInfo &message, int64_t timestamp_ns) {
    rclcpp::Serialization<MonitorInfo> serializer;
    rclcpp::SerializedMessage serialized;
    serializer.serialize_message(&message, &serialized);

    auto *buffer         = new rcutils_uint8_array_t(rcutils_get_zero_initialized_uint8_array());
    const auto allocator = rcutils_get_default_allocator();
    if (rcutils_uint8_array_init(buffer, serialized.size(), &allocator) != RCUTILS_RET_OK) {
        delete buffer;
        throw std::runtime_error("cannot allocate serialized rosbag message buffer");
    }

    // bag 消息共享底层缓冲区；自定义 deleter 保证按 rcutils 规则释放。
    auto serialized_data =
        std::shared_ptr<rcutils_uint8_array_t>(buffer, [](rcutils_uint8_array_t *value) {
            const auto fini_result = rcutils_uint8_array_fini(value);
            (void)fini_result;
            delete value;
        });
    // Foxy writer 接收 rcutils 数组，因此将 rclcpp 序列化结果复制到其所有权缓冲区。
    std::memcpy(buffer->buffer, serialized.get_rcl_serialized_message().buffer, serialized.size());
    buffer->buffer_length = serialized.size();

    auto bag_message             = std::make_shared<rosbag2_storage::SerializedBagMessage>();
    bag_message->serialized_data = std::move(serialized_data);
    bag_message->time_stamp      = timestamp_ns;
    bag_message->topic_name      = topic_;
    writer_->write(std::move(bag_message));
}
}  // namespace monitor
