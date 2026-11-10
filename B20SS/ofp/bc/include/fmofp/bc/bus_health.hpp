#ifndef FMOFP_BC_BUS_HEALTH_HPP
#define FMOFP_BC_BUS_HEALTH_HPP

#include <array>
#include <cstdint>

#include <fmofp/bc/bus_controller.hpp>
#include <fmofp/bus/command_word.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// AVN_BUS_HEALTH: what the bus controller knows about every terminal, as the
// avionics computer (RT 1) receives it once a second. It is the one periodic
// message a terminal does not produce: the controller writes it from its own
// poll statistics and each terminal's last TERM_STATUS (ICD README section 2,
// v1.20).

namespace fmofp::bc {

// A TERM_STATUS is polled at 1 Hz: three periods old is stale.
constexpr std::uint32_t kTermStatusStaleFrames = 150;

class BusHealthReporter {
public:
    // Builds the report and makes it the data of the controller's
    // AVN_BUS_HEALTH slot. Call once per major frame.
    [[nodiscard]] Status report(BusController& controller) noexcept;

    [[nodiscard]] const icd::AvnBusHealth& last() const noexcept { return last_; }

private:
    std::array<std::uint32_t, bus::kBroadcastRt> no_response_{};
    std::uint8_t epoch_{0};
    icd::AvnBusHealth last_{};
};

}  // namespace fmofp::bc

#endif
