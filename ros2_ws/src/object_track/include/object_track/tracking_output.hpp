#pragma once

#include <string>

namespace object_track {

struct VelocityCommand {
  double linear_x{0.0};
  double angular_z{0.0};
};

// 速度输出的副作用边界：preview 仅展示命令，publish 可能将命令发送给下游。
class VelocityOutputPort {
 public:
  virtual ~VelocityOutputPort() = default;

  virtual void preview(const VelocityCommand & command, const std::string & reason) = 0;
  virtual void publish(const VelocityCommand & command, const std::string & reason) = 0;
};

inline void emit_velocity(VelocityOutputPort & output, bool dry_run,
                          const VelocityCommand & command, const std::string & reason) {
  if (dry_run) {
    output.preview(command, reason);
  } else {
    output.publish(command, reason);
  }
}

}  // namespace object_track
