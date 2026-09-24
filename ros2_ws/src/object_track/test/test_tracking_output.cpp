#include "object_track/tracking_output.hpp"

#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace {

class RecordingOutput final : public object_track::VelocityOutputPort {
 public:
  using Event = std::pair<object_track::VelocityCommand, std::string>;

  void preview(const object_track::VelocityCommand & command,
               const std::string & reason) override {
    previews.emplace_back(command, reason);
  }

  void publish(const object_track::VelocityCommand & command,
               const std::string & reason) override {
    publications.emplace_back(command, reason);
  }

  std::vector<Event> previews;
  std::vector<Event> publications;
};

bool dry_run_previews_command_without_publishing() {
  RecordingOutput output;
  const object_track::VelocityCommand command{0.0, 0.25};

  object_track::emit_velocity(output, true, command, "target acquired");

  if (output.previews.size() != 1 || !output.publications.empty()) {
    std::cerr << "dry-run must preview exactly once and publish nothing\n";
    return false;
  }
  if (output.previews.front().first.linear_x != 0.0 ||
      output.previews.front().first.angular_z != 0.25 ||
      output.previews.front().second != "target acquired") {
    std::cerr << "dry-run preview must preserve the calculated command\n";
    return false;
  }
  return true;
}

bool live_mode_publishes_command_without_preview() {
  RecordingOutput output;
  const object_track::VelocityCommand command{0.0, -0.4};

  object_track::emit_velocity(output, false, command, "target acquired");

  if (!output.previews.empty() || output.publications.size() != 1) {
    std::cerr << "live mode must publish exactly once and not preview\n";
    return false;
  }
  if (output.publications.front().first.linear_x != 0.0 ||
      output.publications.front().first.angular_z != -0.4 ||
      output.publications.front().second != "target acquired") {
    std::cerr << "live publication must preserve the calculated command\n";
    return false;
  }
  return true;
}

}  // namespace

int main() {
  if (!dry_run_previews_command_without_publishing()) return 1;
  if (!live_mode_publishes_command_without_preview()) return 1;
  std::cout << "PASS: output mode routes commands to preview or publish\n";
  return 0;
}
