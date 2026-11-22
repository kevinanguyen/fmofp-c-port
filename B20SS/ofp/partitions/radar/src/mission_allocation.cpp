#include <fmofp/radar/mission_allocation.hpp>

namespace fmofp::radar {

RadarConfiguration configuration_for(icd::MissionPhase phase) noexcept {
    switch (phase) {
        case icd::MissionPhase::INGRESS:
        case icd::MissionPhase::OBJECTIVE:
        case icd::MissionPhase::EGRESS:
            return RadarConfiguration::kEnRoute;  // the CRUISE of the Python's phases
        case icd::MissionPhase::COMPLETE:
            return RadarConfiguration::kAirport;  // its APPROACH
        case icd::MissionPhase::PLANNING:
            break;  // its PRE_FLIGHT configures nothing
    }
    return RadarConfiguration::kNone;
}

RadarAllocation allocation_for(RadarConfiguration configuration) noexcept {
    RadarAllocation a{};
    switch (configuration) {
        case RadarConfiguration::kAirport:
            a.weather = icd::WeatherMode::SURVEILLANCE;
            a.tfr = icd::TfrMode::TERRAIN_FOLLOWING;
            break;  // targeting, SAR and AEWC STANDBY
        case RadarConfiguration::kEnRoute:
            a.weather = icd::WeatherMode::SURVEILLANCE;
            a.tfr = icd::TfrMode::TERRAIN_FOLLOWING;
            a.targeting = icd::TargetingMode::TARGET_SEARCH;  // targeting_radarMode.SEARCH
            a.sar = icd::SarMode::STRIPMAP;
            a.aewc = icd::AewcMode::AEWC_SEARCH;  // aewc_radarMode.SEARCH
            break;
        case RadarConfiguration::kNone:
            break;
    }
    return a;
}

void MissionAllocator::reset() noexcept {
    current_ = RadarConfiguration::kNone;
    allocations_ = 0;
}

bool MissionAllocator::observe(const icd::MsnStatus& status, RadarConfiguration& out) noexcept {
    if (status.state != icd::TerminalState::NORMAL && status.state != icd::TerminalState::DEGRADED) {
        return false;  // a mission computer still initializing (or failed) has no phase to follow; one that lost the
                       // FMS's flight data (DEGRADED) still has the mission's phase
    }
    const RadarConfiguration wanted = configuration_for(status.phase);
    if (wanted == current_) {
        return false;
    }
    current_ = wanted;
    if (wanted == RadarConfiguration::kNone) {
        return false;  // back to PLANNING leaves the radars as they are, as PRE_FLIGHT did
    }
    out = wanted;
    ++allocations_;
    return true;
}

}  // namespace fmofp::radar
