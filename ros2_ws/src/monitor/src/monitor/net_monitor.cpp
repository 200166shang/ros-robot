#include "monitor/net_monitor.h"

#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace monitor {
void NetMonitor::UpdateOnce(MonitorInfo *info) {
    // /proc/net/dev 每行前两列是接收字节/包数，第九、十列是发送字节/包数。
    std::ifstream input("/proc/net/dev");
    std::string line;
    std::getline(input, line);
    std::getline(input, line);

    const auto now = std::chrono::steady_clock::now();
    while (std::getline(input, line)) {
        const auto colon = line.find(':');
        if (colon == std::string::npos) continue;
        std::string name = line.substr(0, colon);
        name.erase(0, name.find_first_not_of(" \\t"));
        name.erase(name.find_last_not_of(" \\t") + 1);
        std::istringstream fields(line.substr(colon + 1));
        std::vector<uint64_t> values;
        uint64_t value = 0;
        while (fields >> value) {
            values.push_back(value);
        }
        if (name.empty() || values.size() < 16) continue;

        // 首次读取只保存累计值作为基线；之后计算差值并换算为 KiB/s 或包/s。
        InterfaceStats current{values[0], values[1], values[8], values[9], now};
        auto old = previous_.find(name);
        if (old != previous_.end()) {
            const double elapsed =
                std::chrono::duration<double>(now - old->second.timepoint).count();
            if (elapsed > 0.0) {
                NetInfo out;
                out.name     = name;
                out.rcv_rate = current.rx_bytes >= old->second.rx_bytes
                                   ? static_cast<float>((current.rx_bytes - old->second.rx_bytes) /
                                                        1024.0 / elapsed)
                                   : 0.0F;
                out.send_rate = current.tx_bytes >= old->second.tx_bytes
                                    ? static_cast<float>((current.tx_bytes - old->second.tx_bytes) /
                                                         1024.0 / elapsed)
                                    : 0.0F;
                out.rcv_packets_rate =
                    current.rx_packets >= old->second.rx_packets
                        ? static_cast<float>((current.rx_packets - old->second.rx_packets) /
                                             elapsed)
                        : 0.0F;
                out.send_packets_rate =
                    current.tx_packets >= old->second.tx_packets
                        ? static_cast<float>((current.tx_packets - old->second.tx_packets) /
                                             elapsed)
                        : 0.0F;
                if (std::isfinite(out.rcv_rate) && std::isfinite(out.send_rate))
                    info->net_info.push_back(std::move(out));
            }
        }

        previous_[name] = current;
    }
}
}  // namespace monitor
