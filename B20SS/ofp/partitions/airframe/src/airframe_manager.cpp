#include <fmofp/airframe/airframe_manager.hpp>

namespace fmofp::airframe {

namespace {

using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

}  // namespace

Status AirframeManager::init() noexcept {
    reading_ = icd::PlantAirframe{};
    have_reading_ = false;
    reading_frame_ = 0;
    passes_ = 0;
    gear_state_ = icd::GearState::UNKNOWN;  // UNKNOWN until something commands it
    fms_gear_ = icd::GearPosition::UNKNOWN;
    have_fms_gear_ = false;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::AfrStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_status(0);
    return Status::kOk;
}

void AirframeManager::reset() noexcept { (void)init(); }

void AirframeManager::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool AirframeManager::sensors_fresh(std::uint32_t frame) const noexcept {
    return have_reading_ && frame >= reading_frame_ && frame - reading_frame_ < kSensorStaleFrames;
}

icd::GearState AirframeManager::control_landing_gear(GearCommand what) noexcept {
    // target = "DEPLOYED" if command == "deploy" else "RETRACTED"; the same state again is no action.
    const icd::GearState target = what == GearCommand::DEPLOY ? icd::GearState::DEPLOYED : icd::GearState::RETRACTED;
    gear_state_ = target;
    return gear_state_;
}

void AirframeManager::step(const icd::PlantAirframe* sensors, const icd::FmsControlStatus* fms,
                           std::uint32_t frame) noexcept {
    if (sensors != nullptr && sensors->epoch != 0) {
        const bool new_reading = !have_reading_ || sensors->epoch != reading_.epoch;
        reading_ = *sensors;
        have_reading_ = true;
        reading_frame_ = frame;
        if (new_reading && passes_ < 0xFFFFFFFFU) {
            ++passes_;  // monitor_airframe: the readings logged, nothing judged
        }
    }
    // The FMS's gear command drives control_landing_gear when it changes: DOWN deploys, UP retracts; UNKNOWN and
    // IN_TRANSIT command nothing.
    if (fms != nullptr && (!have_fms_gear_ || fms->gear != fms_gear_)) {
        fms_gear_ = fms->gear;
        have_fms_gear_ = true;
        if (fms->gear == icd::GearPosition::DOWN) {
            (void)control_landing_gear(GearCommand::DEPLOY);
        } else if (fms->gear == icd::GearPosition::UP) {
            (void)control_landing_gear(GearCommand::RETRACT);
        }
    }
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

    if (status_.state == TerminalState::INITIALIZING && fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status(frame);
}

void AirframeManager::command_mode(const icd::AfrModeCmd& cmd) noexcept {
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

void AirframeManager::command(const icd::AfrCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::AirframeCommand::GEAR_DEPLOY:
            (void)control_landing_gear(GearCommand::DEPLOY);
            break;
        case icd::AirframeCommand::GEAR_RETRACT:
            (void)control_landing_gear(GearCommand::RETRACT);
            break;
        case icd::AirframeCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

void AirframeManager::fill_status(std::uint32_t frame) noexcept {
    status_.gear_state = gear_state_;
    status_.afr_cmd_status = cmd_status_;
    status_.sensors_valid = sensors_fresh(frame);
    status_.healthy = !bit_.failed;
    status_.wing_root_strain = reading_.wing_root_strain;
    status_.fuselage_strain = reading_.fuselage_strain;
    status_.leading_edge_temp = reading_.leading_edge_temp;
}

}  // namespace fmofp::airframe
