#ifndef FMOFP_RADAR_MISSION_ALLOCATION_HPP
#define FMOFP_RADAR_MISSION_ALLOCATION_HPP

// The radars following the mission phase (v1.29, unit 37): radarControl.update_mission_phase and
// _allocate_radar_resources, which nothing called upstream. The Python's configurations are kept as written;
// the Python keyed them on its own flight phases (TAKEOFF and APPROACH the airport set, CRUISE the en-route set),
// which the mission computer does not have, so the mapping from the mission computer's phases is new (ICD README
// section 2): INGRESS, OBJECTIVE and EGRESS en route, COMPLETE the airport set, PLANNING none.

#include <cstdint>

#include <fmofp/icd/enums.hpp>
#include <fmofp/icd/messages.hpp>

namespace fmofp::radar {

enum class RadarConfiguration : std::uint8_t {
    kNone,     // the phase configures nothing (PRE_FLIGHT, CLIMB, DESCENT, ... upstream)
    kAirport,  // _configure_airport_departure / _configure_airport_arrival (the two are the same)
    kEnRoute,  // _configure_enroute_surveillance
};

struct RadarAllocation {
    icd::WeatherMode weather{icd::WeatherMode::NONE};
    icd::TfrMode tfr{icd::TfrMode::NONE};
    icd::TargetingMode targeting{icd::TargetingMode::NONE};
    icd::AewcMode aewc{icd::AewcMode::NONE};
    icd::SarMode sar{icd::SarMode::NONE};
};

// The configuration a mission phase asks for.
[[nodiscard]] RadarConfiguration configuration_for(icd::MissionPhase phase) noexcept;

// Each radar's mode in a configuration (kNone: all NONE, which no caller applies). A radar the Python set to
// STANDBY is NONE here: the radars' allocate() stands a radar by for NONE.
[[nodiscard]] RadarAllocation allocation_for(RadarConfiguration configuration) noexcept;

// Watches BCAST_MSN_STATUS and says when the radars are to be reconfigured: when the configuration the phase asks for
// changes to one that configures something. The same configuration twice in a row (INGRESS to OBJECTIVE) leaves the
// radars as they are, so an operator's command since the last change stands.
class MissionAllocator {
public:
    void reset() noexcept;
    // The mission computer's status heard this frame. True, with the configuration in `out`, when the radars are to
    // be reconfigured now.
    [[nodiscard]] bool observe(const icd::MsnStatus& status, RadarConfiguration& out) noexcept;
    [[nodiscard]] std::uint32_t allocations() const noexcept { return allocations_; }
    [[nodiscard]] RadarConfiguration current() const noexcept { return current_; }

private:
    RadarConfiguration current_{RadarConfiguration::kNone};
    std::uint32_t allocations_{0};
};

}  // namespace fmofp::radar

#endif
