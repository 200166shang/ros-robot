#pragma once

#include <algorithm>

namespace object_track {

inline double angular_command(double target_center_x, double image_width, double gain,
                              double maximum) {
  if (image_width <= 0.0 || maximum < 0.0) return 0.0;
  const double command = gain * (image_width * 0.5 - target_center_x);
  return std::max(-maximum, std::min(maximum, command));
}

}  // namespace object_track
