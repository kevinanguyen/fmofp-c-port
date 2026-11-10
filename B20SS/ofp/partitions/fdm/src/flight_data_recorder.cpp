#include <fmofp/fdm/flight_data_recorder.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::fdm {

namespace {

using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

}  // namespace

Status FlightDataRecorder::init() noexcept {
    ring_.fill(Record{});
    next_ = 0;
    held_ = 0;
    records_ = 0;
    slot_present_.fill(true);
    flight_data_ = icd::FmsFlightData{};
    have_flight_data_ = false;
    flight_data_frame_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::FdmStatus{};
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

void FlightDataRecorder::reset() noexcept { (void)init(); }

void FlightDataRecorder::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool FlightDataRecorder::flight_data_fresh(std::uint32_t frame) const noexcept {
    return have_flight_data_ && frame >= flight_data_frame_ && frame - flight_data_frame_ < kFlightDataStaleFrames;
}

void FlightDataRecorder::record(std::uint32_t frame, double altitude_ft, double airspeed_kt) noexcept {
    if (!std::isfinite(altitude_ft) || !std::isfinite(airspeed_kt)) {
        return;
    }
    ring_[next_] = Record{frame, altitude_ft, airspeed_kt};
    next_ = (next_ + 1) % kRingCapacity;
    held_ = std::min(held_ + 1, kRingCapacity);
    if (records_ < 0xFFFFFFFFU) {
        ++records_;
    }
}

Record FlightDataRecorder::record_at(std::size_t index) const noexcept {
    if (index >= held_) {
        return Record{};
    }
    const std::size_t oldest = (next_ + kRingCapacity - held_) % kRingCapacity;
    return ring_[(oldest + index) % kRingCapacity];
}

bool FlightDataRecorder::slot_present(std::uint8_t slot) const noexcept {
    return valid_slot(slot) && slot_present_[static_cast<std::size_t>(slot - 1)];
}

bool FlightDataRecorder::eject_storage(std::uint8_t slot) noexcept {
    if (!slot_present(slot)) {
        return false;  // "No storage card in slot"
    }
    slot_present_[static_cast<std::size_t>(slot - 1)] = false;
    return true;
}

void FlightDataRecorder::step(const icd::FmsFlightData* flight_data, std::uint32_t frame) noexcept {
    if (flight_data != nullptr) {
        flight_data_ = *flight_data;
        have_flight_data_ = true;
        flight_data_frame_ = frame;
    }
    const bool fresh = flight_data_fresh(frame);
    // collect_data, twice a second: the flight data recorder's three parameters from the flight data in hand.
    if (frame % kRecordFrames == 0 && fresh) {
        record(frame, flight_data_.altitude, flight_data_.airspeed);
    }

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    // Recording while the flight data arrives; DEGRADED when it stops, as a recorder with nothing to record.
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

void FlightDataRecorder::command_mode(const icd::FdmModeCmd& cmd) noexcept {
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

void FlightDataRecorder::command(const icd::FdmCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::FdmCommand::EJECT_STORAGE:
            if (!valid_slot(cmd.slot)) {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            } else if (!eject_storage(cmd.slot)) {
                cmd_status_ = icd::CmdStatus::FAILED;  // no card in the slot
            }
            break;
        case icd::FdmCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

void FlightDataRecorder::fill_status(std::uint32_t frame) noexcept {
    status_.fdm_cmd_status = cmd_status_;
    status_.flight_data_valid = flight_data_fresh(frame);
    status_.slot_1_present = slot_present_[0];
    status_.slot_2_present = slot_present_[1];
    status_.healthy = !bit_.failed;
    status_.records = std::min(kMaxRecordCount, static_cast<double>(records_));
    status_.held = static_cast<double>(held_);
    const Record last = held_ > 0 ? record_at(held_ - 1) : Record{};
    status_.last_altitude = last.altitude_ft;
    status_.last_airspeed = last.airspeed_kt;
    status_.last_frame = static_cast<double>(last.frame);
}

}  // namespace fmofp::fdm
