#pragma once

#include <string>

namespace object_track {

struct VelocityCommand {
    double linear_x{0.0};   // 前进/后退速度，单位：米/秒。
    double angular_z{0.0};  // 平面转向角速度，单位：弧度/秒。
};

// 速度输出的副作用边界：preview 仅展示命令，publish 可能将命令发送给下游。
class VelocityOutputPort {
public:
    // 通过虚析构允许节点销毁具体输出适配器时正确释放资源。
    virtual ~VelocityOutputPort() = default;

    // 显示待执行命令，不应产生机器人运动副作用。
    virtual void preview(const VelocityCommand& command, const std::string& reason) = 0;

    // 将命令交给 ROS 输出端；是否安全发布由调用方的 dry-run 分流决定。
    virtual void publish(const VelocityCommand& command, const std::string& reason) = 0;
};

// 统一输出分流：dry-run 只走预览，关闭 dry-run 才走可能产生运动的发布端。
inline void emit_velocity(VelocityOutputPort& output, bool dry_run, const VelocityCommand& command, const std::string& reason) {
    // 1. 先依据安全开关选择出口，不在控制计算处创建 ROS publisher。
    if (dry_run) {
        output.preview(command, reason);
    } else {
        output.publish(command, reason);
    }
}

}  // namespace object_track
