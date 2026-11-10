#include <fmofp/surfaces/flight_surfaces.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::surfaces {

namespace {

using icd::Ssm;
using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

// max(lo, min(hi, value)), nested as the Python wrote every clamp.
double clamp(double value, double lo, double hi) noexcept { return std::max(lo, std::min(hi, value)); }

Surface make_surface(double rate_deg_s, double limit_lo, double limit_hi) noexcept {
    Surface s;
    s.rate_deg_s = rate_deg_s;
    s.limit_lo = limit_lo;
    s.limit_hi = limit_hi;
    return s;
}

// The trim dictionary's keys, in FSF_STATUS order; kTrimAxes for a key the Python's `if axis in self._trim` refused.
std::size_t axis_index(icd::TrimAxis axis) noexcept {
    switch (axis) {
        case icd::TrimAxis::PITCH:
            return 0;
        case icd::TrimAxis::ROLL:
            return 1;
        case icd::TrimAxis::YAW:
            return 2;
        default:
            return kTrimAxes;
    }
}

Ssm ssm_of(const Surface& s) noexcept { return s.healthy ? Ssm::NORMAL : Ssm::FAILURE_WARNING; }

}  // namespace

// ---- Surface --------------------------------------------------------------------------------------

void Surface::step(double dt) noexcept {
    // Surface.step: error = cmd - position; delta = copysign(min(abs(error), rate_deg_s * dt), error);
    // position = max(limit_lo, min(limit_hi, position + delta)). The last step lands exactly on cmd.
    const double error = cmd - position;
    const double delta = std::copysign(std::min(std::fabs(error), rate_deg_s * dt), error);
    position = std::max(limit_lo, std::min(limit_hi, position + delta));
}

// ---- FlightSurfaces ---------------------------------------------------------------------------------

Status FlightSurfaces::init() noexcept {
    // FlightSurfaceService.__init__: the primary surfaces, the secondary surfaces, the trim, the flap command.
    surfaces_[index_of(SurfaceId::AILERON_L)] = make_surface(60.0, -25.0, 25.0);
    surfaces_[index_of(SurfaceId::AILERON_R)] = make_surface(60.0, -25.0, 25.0);
    surfaces_[index_of(SurfaceId::ELEVATOR_L)] = make_surface(50.0, -30.0, 30.0);
    surfaces_[index_of(SurfaceId::ELEVATOR_R)] = make_surface(50.0, -30.0, 30.0);
    surfaces_[index_of(SurfaceId::RUDDER)] = make_surface(40.0, -30.0, 30.0);
    surfaces_[index_of(SurfaceId::FLAP_L)] = make_surface(5.0, 0.0, 30.0);
    surfaces_[index_of(SurfaceId::FLAP_R)] = make_surface(5.0, 0.0, 30.0);
    surfaces_[index_of(SurfaceId::SLAT_L)] = make_surface(5.0, 0.0, 20.0);
    surfaces_[index_of(SurfaceId::SLAT_R)] = make_surface(5.0, 0.0, 20.0);
    surfaces_[index_of(SurfaceId::SPEEDBRAKE)] = make_surface(30.0, 0.0, 60.0);
    trim_.fill(0.0);
    flap_cmd_ = 0.0;
    slats_extended_ = false;
    have_sensors_ = false;
    sensor_frame_ = 0;
    frame_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::FsfStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    positions_ = icd::FsfPositions{};
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_outputs(0);
    return Status::kOk;
}

void FlightSurfaces::reset() noexcept { (void)init(); }

void FlightSurfaces::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool FlightSurfaces::sensors_fresh(std::uint32_t frame) const noexcept {
    return have_sensors_ && frame >= sensor_frame_ && frame - sensor_frame_ < kSensorStaleFrames;
}

void FlightSurfaces::sync_from_fcc(double roll_deg, double pitch_deg, double aoa_deg) noexcept {
    if (!std::isfinite(roll_deg) || !std::isfinite(pitch_deg) || !std::isfinite(aoa_deg)) {
        return;
    }
    // Aileron follows roll demand (simplified fly-by-wire): aileron_cmd = max(-25, min(25, -roll * 0.5)), the
    // left aileron commanded to -aileron_cmd and the right to aileron_cmd.
    const double aileron_cmd = clamp(-roll_deg * kAileronGain, -kAileronLimitDeg, kAileronLimitDeg);
    surfaces_[index_of(SurfaceId::AILERON_L)].cmd = -aileron_cmd;
    surfaces_[index_of(SurfaceId::AILERON_R)].cmd = aileron_cmd;
    // Elevator follows pitch demand: elev_cmd = max(-30, min(30, -pitch * 0.8)) for both elevators.
    const double elev_cmd = clamp(-pitch_deg * kElevatorGain, -kElevatorLimitDeg, kElevatorLimitDeg);
    surfaces_[index_of(SurfaceId::ELEVATOR_L)].cmd = elev_cmd;
    surfaces_[index_of(SurfaceId::ELEVATOR_R)].cmd = elev_cmd;
    // Auto-slat: extend when AOA > 8 degrees.
    slats_extended_ = aoa_deg > kSlatAoaDeg;
    const double slat_cmd = slats_extended_ ? kSlatExtendedDeg : 0.0;
    surfaces_[index_of(SurfaceId::SLAT_L)].cmd = slat_cmd;
    surfaces_[index_of(SurfaceId::SLAT_R)].cmd = slat_cmd;
}

void FlightSurfaces::step_all(double dt) noexcept {
    if (!std::isfinite(dt) || dt < 0.0) {
        return;
    }
    for (Surface& s : surfaces_) {
        s.step(dt);
    }
}

void FlightSurfaces::step(const icd::PlantSensors* sensors, std::uint32_t frame) noexcept {
    frame_ = frame;
    // _sync_from_fcc read the flight control computer's current data every pass; here the pass with a fresh copy
    // of the sensed flight state syncs, and a copy with a failed roll, pitch or angle of attack is no data.
    if (sensors != nullptr && sensors->roll_ssm == Ssm::NORMAL && sensors->pitch_ssm == Ssm::NORMAL &&
        sensors->aoa_ssm == Ssm::NORMAL) {
        have_sensors_ = true;
        sensor_frame_ = frame;
        sync_from_fcc(sensors->roll, sensors->pitch, sensors->angle_of_attack);
    }
    step_all(kDt);
    const bool fresh = sensors_fresh(frame);

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    // The surfaces are there to be moved while the flight state arrives; without it they finish their travel.
    if (status_.state == TerminalState::INITIALIZING && fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_outputs(frame);
}

void FlightSurfaces::set_flaps(double detent_deg) noexcept {
    if (!std::isfinite(detent_deg)) {
        return;
    }
    // nearest = min(FLAP_DETENTS, key=lambda d: abs(d - detent)): the first of the nearest detents.
    const auto nearest = std::min_element(kFlapDetents.begin(), kFlapDetents.end(), [detent_deg](double a, double b) {
        return std::fabs(a - detent_deg) < std::fabs(b - detent_deg);
    });
    flap_cmd_ = *nearest;
    surfaces_[index_of(SurfaceId::FLAP_L)].cmd = *nearest;
    surfaces_[index_of(SurfaceId::FLAP_R)].cmd = *nearest;
}

void FlightSurfaces::set_speedbrake(double pct) noexcept {
    if (!std::isfinite(pct)) {
        return;
    }
    surfaces_[index_of(SurfaceId::SPEEDBRAKE)].cmd = clamp(pct * kSpeedbrakeDegPerPct, 0.0, kSpeedbrakeLimitDeg);
}

void FlightSurfaces::set_rudder(double deg) noexcept {
    if (!std::isfinite(deg)) {
        return;
    }
    surfaces_[index_of(SurfaceId::RUDDER)].cmd = clamp(deg, -kRudderLimitDeg, kRudderLimitDeg);
}

bool FlightSurfaces::set_trim(icd::TrimAxis axis, double deg) noexcept {
    const std::size_t i = axis_index(axis);
    if (i >= kTrimAxes || !std::isfinite(deg)) {
        return false;
    }
    trim_[i] = clamp(deg, -kTrimLimitDeg, kTrimLimitDeg);
    return true;
}

double FlightSurfaces::trim(icd::TrimAxis axis) const noexcept {
    const std::size_t i = axis_index(axis);
    return i < kTrimAxes ? trim_[i] : 0.0;
}

bool FlightSurfaces::all_healthy() const noexcept {
    return std::all_of(surfaces_.begin(), surfaces_.end(), [](const Surface& s) { return s.healthy; });
}

void FlightSurfaces::command_mode(const icd::FsfModeCmd& cmd) noexcept {
    if (!mode_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    status_.last_cmd_seq = cmd.cmd_seq;
    if (!commandable(cmd.requested_state)) {
        status_.cmd_rejected = true;
        return;
    }
    status_.cmd_rejected = false;
    status_.state = cmd.requested_state;
    status_.mode_transition = false;
}

void FlightSurfaces::command(const icd::FsfCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    frame_ = frame;
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::SurfaceCommand::SET_FLAPS:
            set_flaps(cmd.value);
            break;
        case icd::SurfaceCommand::SET_SPEEDBRAKE:
            set_speedbrake(cmd.value);
            break;
        case icd::SurfaceCommand::SET_RUDDER:
            set_rudder(cmd.value);
            break;
        case icd::SurfaceCommand::SET_TRIM:
            if (!set_trim(cmd.axis, cmd.value)) {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            }
            break;
        case icd::SurfaceCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_outputs(frame);
}

void FlightSurfaces::fill_outputs(std::uint32_t frame) noexcept {
    status_.surface_cmd_status = cmd_status_;
    status_.sensors_valid = sensors_fresh(frame);
    status_.slats_extended = slats_extended_;
    status_.healthy = all_healthy() && !bit_.failed;
    status_.flap_cmd = flap_cmd_;
    status_.trim_pitch = trim_[0];
    status_.trim_roll = trim_[1];
    status_.trim_yaw = trim_[2];
    positions_.aileron_l_ssm = ssm_of(surface(SurfaceId::AILERON_L));
    positions_.aileron_r_ssm = ssm_of(surface(SurfaceId::AILERON_R));
    positions_.elevator_l_ssm = ssm_of(surface(SurfaceId::ELEVATOR_L));
    positions_.elevator_r_ssm = ssm_of(surface(SurfaceId::ELEVATOR_R));
    positions_.rudder_ssm = ssm_of(surface(SurfaceId::RUDDER));
    positions_.flap_l_ssm = ssm_of(surface(SurfaceId::FLAP_L));
    positions_.flap_r_ssm = ssm_of(surface(SurfaceId::FLAP_R));
    positions_.slat_l_ssm = ssm_of(surface(SurfaceId::SLAT_L));
    positions_.slat_r_ssm = ssm_of(surface(SurfaceId::SLAT_R));
    positions_.speedbrake_ssm = ssm_of(surface(SurfaceId::SPEEDBRAKE));
    positions_.aileron_l = surface(SurfaceId::AILERON_L).position;
    positions_.aileron_r = surface(SurfaceId::AILERON_R).position;
    positions_.elevator_l = surface(SurfaceId::ELEVATOR_L).position;
    positions_.elevator_r = surface(SurfaceId::ELEVATOR_R).position;
    positions_.rudder = surface(SurfaceId::RUDDER).position;
    positions_.flap_l = surface(SurfaceId::FLAP_L).position;
    positions_.flap_r = surface(SurfaceId::FLAP_R).position;
    positions_.slat_l = surface(SurfaceId::SLAT_L).position;
    positions_.slat_r = surface(SurfaceId::SLAT_R).position;
    positions_.speedbrake = surface(SurfaceId::SPEEDBRAKE).position;
}

}  // namespace fmofp::surfaces
