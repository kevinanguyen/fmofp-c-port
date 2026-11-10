#include <fmofp/ecs/ecs_control.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::ecs {

namespace {

using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

}  // namespace

Status EcsControl::init() noexcept {
    reading_ = icd::PlantCabin{};
    have_reading_ = false;
    reading_frame_ = 0;
    passes_ = 0;
    climate_temperature_ = kInitialClimateTemperatureC;  // ClimateControl()
    humidity_ = kInitialHumidityPct;
    oxygen_level_ = kInitialOxygenPct;  // OxygenControl()
    oxygen_rate_ = kInitialOxygenRate;
    temperature_adjusting_ = false;
    pressure_adjusting_ = false;
    purification_active_ = false;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::EcsStatus{};
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

void EcsControl::reset() noexcept { (void)init(); }

void EcsControl::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool EcsControl::cabin_fresh(std::uint32_t frame) const noexcept {
    return have_reading_ && frame >= reading_frame_ && frame - reading_frame_ < kCabinStaleFrames;
}

void EcsControl::monitor(double temperature_c, double pressure_kpa, double air_quality_pct) noexcept {
    if (!std::isfinite(temperature_c) || !std::isfinite(pressure_kpa) || !std::isfinite(air_quality_pct)) {
        return;
    }
    // The readings as set_sensor_readings stored them (get_temperature and its siblings return them).
    reading_.temperature = temperature_c;
    reading_.pressure = pressure_kpa;
    reading_.air_quality = air_quality_pct;
    // adjust_temperature, adjust_pressure, adjust_air_quality: each logged what it would do and did nothing.
    temperature_adjusting_ = std::fabs(temperature_c - kTargetTemperatureC) > kTemperatureToleranceC;
    pressure_adjusting_ = std::fabs(pressure_kpa - kTargetPressureKpa) > kPressureToleranceKpa;
    purification_active_ = air_quality_pct < kMinAirQualityPct;
    // oxygen.generate_oxygen(): += 0.1, capped at 23.
    oxygen_level_ += kOxygenStepPct;
    if (oxygen_level_ > kOxygenCapPct) {
        oxygen_level_ = kOxygenCapPct;
    }
    // climate.adjust_temperature(temperature): the sub-component takes the reading as its temperature.
    climate_temperature_ = temperature_c;
    if (passes_ < 0xFFFFFFFFU) {
        ++passes_;
    }
}

void EcsControl::step(const icd::PlantCabin* cabin, std::uint32_t frame) noexcept {
    if (cabin != nullptr && cabin->epoch != 0) {
        const bool new_reading = !have_reading_ || cabin->epoch != reading_.epoch;
        reading_ = *cabin;
        have_reading_ = true;
        reading_frame_ = frame;
        if (new_reading) {
            monitor(cabin->temperature, cabin->pressure, cabin->air_quality);  // the 2 Hz pass, once per reading
        }
    }
    const bool fresh = cabin_fresh(frame);

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    // The cabin is there to be read while the plant's readings arrive.
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

void EcsControl::set_oxygen_rate(double rate) noexcept {
    if (std::isfinite(rate)) {
        oxygen_rate_ = rate;  // stored as given; generate_oxygen never read it
    }
}

void EcsControl::set_humidity(double pct) noexcept {
    if (std::isfinite(pct)) {
        humidity_ = pct;
    }
}

void EcsControl::set_climate_temperature(double temperature_c) noexcept {
    if (std::isfinite(temperature_c)) {
        climate_temperature_ = temperature_c;  // until the next pass with a reading overwrites it
    }
}

void EcsControl::command_mode(const icd::EcsModeCmd& cmd) noexcept {
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

void EcsControl::command(const icd::EcsCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::EcsCommand::SET_OXYGEN_RATE:
            set_oxygen_rate(cmd.value);
            break;
        case icd::EcsCommand::SET_HUMIDITY:
            set_humidity(cmd.value);
            break;
        case icd::EcsCommand::SET_CLIMATE_TEMPERATURE:
            set_climate_temperature(cmd.value);
            break;
        case icd::EcsCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

void EcsControl::fill_status(std::uint32_t frame) noexcept {
    status_.ecs_cmd_status = cmd_status_;
    status_.sensors_valid = cabin_fresh(frame);
    status_.temperature_adjusting = temperature_adjusting_;
    status_.pressure_adjusting = pressure_adjusting_;
    status_.purification_active = purification_active_;
    status_.healthy = !bit_.failed;
    status_.temperature = reading_.temperature;
    status_.pressure = reading_.pressure;
    status_.air_quality = reading_.air_quality;
    status_.climate_temperature = climate_temperature_;
    status_.humidity = humidity_;
    status_.oxygen_level = oxygen_level_;
    status_.oxygen_rate = oxygen_rate_;
    status_.passes = std::min(kMaxPasses, static_cast<double>(passes_));
}

}  // namespace fmofp::ecs
