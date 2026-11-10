#include <fmofp/hydraulics/hydraulic_controller.hpp>

#include <cmath>

namespace fmofp::hydraulics {

namespace {

using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

}  // namespace

Status HydraulicController::init() noexcept {
    reading_ = icd::PlantHydraulics{};
    have_reading_ = false;
    reading_frame_ = 0;
    active_system_ = icd::HydraulicSystem::PRIMARY;  // self.active_system = self.primary_system
    pressure_status_ = icd::PressureStatus::OK;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::HydStatus{};
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

void HydraulicController::reset() noexcept { (void)init(); }

void HydraulicController::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool HydraulicController::pressures_fresh(std::uint32_t frame) const noexcept {
    return have_reading_ && frame >= reading_frame_ && frame - reading_frame_ < kPressureStaleFrames;
}

double HydraulicController::active_psi() const noexcept {
    return active_system_ == icd::HydraulicSystem::BACKUP ? reading_.backup_psi : reading_.primary_psi;
}

void HydraulicController::activate_backup() noexcept { active_system_ = icd::HydraulicSystem::BACKUP; }

void HydraulicController::monitor(double primary, double backup) noexcept {
    if (!std::isfinite(primary) || !std::isfinite(backup)) {
        return;
    }
    reading_.primary_psi = primary;
    reading_.backup_psi = backup;
    have_reading_ = true;
    // monitor_pressure: the status on the active system's pressure, critical first; CRITICAL activates the
    // backup (the status of this pass stays CRITICAL: the Python judged, then switched).
    const double current = active_psi();
    if (current <= kCriticalPsi) {
        pressure_status_ = icd::PressureStatus::CRITICAL;
        activate_backup();
    } else if (current <= kWarningPsi) {
        pressure_status_ = icd::PressureStatus::WARNING;
    } else {
        pressure_status_ = icd::PressureStatus::OK;
    }
}

void HydraulicController::step(const icd::PlantHydraulics* pressures, std::uint32_t frame) noexcept {
    if (pressures != nullptr && pressures->epoch != 0) {
        const bool new_reading = !have_reading_ || pressures->epoch != reading_.epoch;
        reading_.epoch = pressures->epoch;
        reading_frame_ = frame;
        if (new_reading) {
            monitor(pressures->primary_psi, pressures->backup_psi);  // the 1 Hz pass, once per reading
        } else {
            have_reading_ = true;
        }
    }
    const bool fresh = pressures_fresh(frame);

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

void HydraulicController::command_mode(const icd::HydModeCmd& cmd) noexcept {
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

void HydraulicController::command(const icd::HydCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::HydraulicCommand::ACTIVATE_BACKUP:
            activate_backup();
            break;
        case icd::HydraulicCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

void HydraulicController::fill_status(std::uint32_t frame) noexcept {
    status_.active_system = active_system_;
    status_.hyd_cmd_status = cmd_status_;
    status_.pressures_valid = pressures_fresh(frame);
    status_.pressure_status = pressure_status_;
    status_.healthy = !bit_.failed;
    status_.primary_psi = reading_.primary_psi;
    status_.backup_psi = reading_.backup_psi;
}

}  // namespace fmofp::hydraulics
