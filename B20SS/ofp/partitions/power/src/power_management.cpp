#include <fmofp/power/power_management.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::power {

using icd::TerminalState;

namespace {

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

}  // namespace

// ---- the batteries (batts/mainBatt.py and its three siblings) ----------------------------------------

Battery::Battery(double capacity, double voltage, double initial_charge) noexcept
    : capacity_ah_(capacity), nominal_voltage_(voltage), charge_pct_(std::max(0.0, std::min(100.0, initial_charge))) {}

double Battery::discharge(double amps, double dt_hours) noexcept {
    if (!online_ || amps <= 0.0 || dt_hours <= 0.0) {
        return 0.0;
    }
    const double requested_ah = amps * dt_hours;
    const double available_ah = capacity_remaining_ah();
    const double supplied_ah = std::min(requested_ah, available_ah);
    charge_pct_ = std::max(0.0, charge_pct_ - (supplied_ah / capacity_ah_) * 100.0);
    load_amps_ = supplied_ah >= requested_ah ? amps : 0.0;  // depleted mid-draw: the Python logged a warning
    return supplied_ah;
}

double Battery::charge(double amps, double dt_hours) noexcept {
    if (amps <= 0.0 || dt_hours <= 0.0) {
        return 0.0;
    }
    const double offered_ah = amps * dt_hours;
    const double headroom_ah = capacity_ah_ - capacity_remaining_ah();
    const double accepted_ah = std::min(offered_ah, headroom_ah);
    charge_pct_ = std::min(100.0, charge_pct_ + (accepted_ah / capacity_ah_) * 100.0);
    return accepted_ah;
}

bool MainBattery::start_engine() noexcept {
    if (charge_pct() < kStartMinimumPct) {
        return false;
    }
    const double supplied = discharge(kEngineStartAmps, kEngineStartDurationHours);
    const double required = kEngineStartAmps * kEngineStartDurationHours;
    return supplied >= required * 0.999;
}

bool ApuBattery::start_apu() noexcept {
    if (apu_running_) {
        return true;
    }
    if (charge_pct() < kStartMinimumPct) {
        return false;
    }
    const double supplied = discharge(kApuStartAmps, kApuStartDurationHours);
    const double required = kApuStartAmps * kApuStartDurationHours;
    apu_running_ = supplied >= required * 0.999;
    return apu_running_;
}

void EmergencyBattery::deactivate_emergency_power() noexcept {
    if (emergency_mode_active_) {
        emergency_mode_active_ = false;
        clear_load();
    }
}

bool EmergencyBattery::sustain_critical_systems(double dt_hours) noexcept {
    if (!emergency_mode_active_) {
        return true;
    }
    const double supplied = discharge(kCriticalLoadAmps, dt_hours);
    const double required = kCriticalLoadAmps * dt_hours;
    return supplied >= required * 0.999;  // the Python logged an error when not
}

bool MissionEquipmentBattery::power_equipment(double draw_amps, double dt_hours) noexcept {
    const double supplied = discharge(draw_amps, dt_hours);
    const double required = draw_amps * dt_hours;
    powering_equipment_ = supplied >= required * 0.999 && draw_amps > 0.0;
    return powering_equipment_;
}

// ---- the thermal units (cooling.py, activeDissipation.py, HVAC.py) -----------------------------------

void ActiveDissipationUnit::set_fan_speed(double pct) noexcept {
    fan_pct_ = std::max(active_ ? kMinFanPct : 0.0, std::min(kMaxFanPct, pct));
}

void ActiveDissipationUnit::activate() noexcept {
    active_ = true;
    if (fan_pct_ < kMinFanPct) {
        fan_pct_ = kMinFanPct;
    }
}

void ActiveDissipationUnit::deactivate() noexcept {
    active_ = false;
    fan_pct_ = 0.0;
    last_rejected_watts_ = 0.0;
}

double ActiveDissipationUnit::reject_heat(double coolant_temp_c, double ambient_temp_c) noexcept {
    if (!active_) {
        last_rejected_watts_ = 0.0;
        return 0.0;
    }
    const double delta_t = std::max(0.0, coolant_temp_c - ambient_temp_c);
    last_rejected_watts_ = fan_pct_ * delta_t * kRejectionWPerPctPerC;
    return last_rejected_watts_;
}

void ActiveDissipationUnit::auto_control(double coolant_temp_c, double target_temp_c) noexcept {
    if (!active_) {
        return;
    }
    const double error = coolant_temp_c - target_temp_c;
    if (error <= 0.0) {
        set_fan_speed(kMinFanPct);
    } else {
        set_fan_speed(kMinFanPct + (error / 5.0) * (kMaxFanPct - kMinFanPct));  // 5 C over the target: full speed
    }
}

void CoolingSystem::set_heat_load(double watts) noexcept { heat_load_w_ = std::max(0.0, watts); }

void CoolingSystem::update(double dt_hours) noexcept {
    dissipation_.auto_control(coolant_temp_c_, target_temp_c_);
    const double rejected_watts = dissipation_.reject_heat(coolant_temp_c_, ambient_temp_c_);
    const double net_watts = heat_load_w_ - rejected_watts;
    const double delta_c = net_watts * dt_hours * kThermalMassCPerWh;
    coolant_temp_c_ = std::max(ambient_temp_c_, coolant_temp_c_ + delta_c);
}

icd::ThermalStatus CoolingSystem::thermal_status() const noexcept {
    if (coolant_temp_c_ >= kCriticalTempC) {
        return icd::ThermalStatus::CRITICAL;
    }
    return coolant_temp_c_ >= kWarningTempC ? icd::ThermalStatus::WARNING : icd::ThermalStatus::OK;
}

void HvacSystem::set_temperature(double target_c) noexcept {
    setpoint_c_ = std::max(kMinTempC, std::min(kMaxTempC, target_c));
}

void HvacSystem::set_airflow(double pct) noexcept { airflow_pct_ = std::max(kMinAirflowPct, std::min(kMaxAirflowPct, pct)); }

void HvacSystem::update(double dt_hours) noexcept {
    if (!powered_ || airflow_pct_ <= 0.0) {
        // Passive drift toward ambient while the system is not conditioning.
        const double drift = (ambient_temp_c_ - cabin_temp_c_) * std::min(1.0, dt_hours * 2.0);
        cabin_temp_c_ += drift;
        return;
    }
    const double error = setpoint_c_ - cabin_temp_c_;
    const double max_delta = airflow_pct_ * kResponseCPerPctPerHour * dt_hours;
    const double delta = std::max(-max_delta, std::min(max_delta, error));
    cabin_temp_c_ += delta;
}

// ---- PowerManagementSystem -----------------------------------------------------------------------------

Status PowerManagement::init() noexcept {
    main_battery_ = MainBattery{};
    emergency_battery_ = EmergencyBattery{};
    apu_battery_ = ApuBattery{};
    equipment_.fill(MissionEquipmentBattery{});  // add_equipment("Radar", "Comms", "Mission Computer")
    cooling_ = CoolingSystem{};
    hvac_ = HvacSystem{};
    reading_ = icd::PlantElectrical{};
    have_reading_ = false;
    reading_frame_ = 0;
    updated_ = false;
    frame_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::PwrStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    gen_cmd_ = icd::PwrGenCmd{};
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_status(0);
    return Status::kOk;
}

void PowerManagement::reset() noexcept { (void)init(); }

void PowerManagement::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool PowerManagement::electrical_fresh(std::uint32_t frame) const noexcept {
    return have_reading_ && frame >= reading_frame_ && frame - reading_frame_ < kElectricalStaleFrames;
}

void PowerManagement::step(const icd::PlantElectrical* electrical, std::uint32_t frame) noexcept {
    frame_ = frame;
    if (electrical != nullptr && electrical->epoch != 0) {
        const bool new_reading = !have_reading_ || electrical->epoch != reading_.epoch;
        have_reading_ = true;
        reading_frame_ = frame;
        if (new_reading) {
            update(*electrical);  // the 1 Hz body, once per reading
        }
    }
    const bool fresh = electrical_fresh(frame);

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    // The generator and the buses are there to be measured while the plant's readings arrive.
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

// adjust_power_parameters(dt_hours = 1/3600) with the reading's draws in place of random.uniform, then monitor().
void PowerManagement::update(const icd::PlantElectrical& electrical) noexcept {
    reading_ = electrical;
    const double power_balance_kw = electrical.generator_output - electrical.total_power_consumption;
    // P = IV: the surplus or deficit as current on the main battery's 24 V bus.
    const double amps = std::fabs(power_balance_kw) * 1000.0 / main_battery_.nominal_voltage();
    if (power_balance_kw >= 0.0) {
        (void)main_battery_.charge(amps, kDtHours);
        (void)apu_battery_.charge(amps / kApuChargeDivisor, kDtHours);
    } else {
        (void)main_battery_.discharge(amps, kDtHours);
    }
    // The emergency battery supplies its load only while the emergency mode is on.
    (void)emergency_battery_.sustain_critical_systems(kDtHours);
    // The avionics heat load scales with the consumption: 6 W per kW (the Python's own tuning note).
    cooling_.set_heat_load(electrical.total_power_consumption * kHeatWattsPerKw);
    cooling_.update(kDtHours);
    hvac_.update(kDtHours);
    updated_ = true;
    fill_status(frame_);
}

void PowerManagement::set_generator_output(double kw, std::uint8_t sequence) noexcept {
    gen_cmd_.override = true;
    gen_cmd_.generator_output = std::max(0.0, kw);  // set_generator_output: max(0, output)
    gen_cmd_.sequence = sequence;
}

void PowerManagement::generator_auto(std::uint8_t sequence) noexcept {
    gen_cmd_.override = false;
    gen_cmd_.generator_output = 0.0;
    gen_cmd_.sequence = sequence;
}

void PowerManagement::set_emergency_power(bool on) noexcept {
    if (on) {
        emergency_battery_.activate_emergency_power();
    } else {
        emergency_battery_.deactivate_emergency_power();
    }
    fill_status(frame_);
}

bool PowerManagement::start_apu() noexcept {
    const bool started = apu_battery_.start_apu();
    fill_status(frame_);
    return started;
}

void PowerManagement::stop_apu() noexcept {
    apu_battery_.stop_apu();
    fill_status(frame_);
}

bool PowerManagement::start_engine() noexcept {
    const bool started = main_battery_.start_engine();
    fill_status(frame_);
    return started;
}

void PowerManagement::set_hvac_setpoint(double target_c) noexcept {
    hvac_.set_temperature(target_c);
    fill_status(frame_);
}

void PowerManagement::set_hvac_airflow(double pct) noexcept {
    hvac_.set_airflow(pct);
    fill_status(frame_);
}

void PowerManagement::set_hvac_power(bool on) noexcept {
    if (on) {
        hvac_.power_on();
    } else {
        hvac_.power_off();
    }
    fill_status(frame_);
}

void PowerManagement::set_dissipation(bool on) noexcept {
    if (on) {
        cooling_.dissipation_unit().activate();
    } else {
        cooling_.dissipation_unit().deactivate();
    }
    fill_status(frame_);
}

bool PowerManagement::power_equipment(std::size_t index, double draw_amps) noexcept {
    if (index >= kEquipmentCount) {
        return false;
    }
    return equipment_[index].power_equipment(draw_amps, kDtHours);
}

void PowerManagement::command_mode(const icd::PwrModeCmd& cmd) noexcept {
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

void PowerManagement::command(const icd::PwrCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    frame_ = frame;
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    switch (cmd.command) {
        case icd::PowerCommand::SET_GENERATOR_OUTPUT:
            set_generator_output(cmd.value, cmd.cmd_seq);
            break;
        case icd::PowerCommand::GENERATOR_AUTO:
            generator_auto(cmd.cmd_seq);
            break;
        case icd::PowerCommand::EMERGENCY_POWER_ON:
            set_emergency_power(true);
            break;
        case icd::PowerCommand::EMERGENCY_POWER_OFF:
            set_emergency_power(false);
            break;
        case icd::PowerCommand::APU_START:
            if (!start_apu()) {
                cmd_status_ = icd::CmdStatus::FAILED;  // the APU battery under 15 %
            }
            break;
        case icd::PowerCommand::APU_STOP:
            stop_apu();
            break;
        case icd::PowerCommand::ENGINE_START:
            if (cmd.engine != icd::EngineSelect::ENGINE_1 && cmd.engine != icd::EngineSelect::ENGINE_2) {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            } else if (!start_engine()) {
                cmd_status_ = icd::CmdStatus::FAILED;  // the main battery under 20 %
            }
            break;
        case icd::PowerCommand::HVAC_SETPOINT:
            set_hvac_setpoint(cmd.value);
            break;
        case icd::PowerCommand::HVAC_AIRFLOW:
            set_hvac_airflow(cmd.value);
            break;
        case icd::PowerCommand::HVAC_POWER_ON:
            set_hvac_power(true);
            break;
        case icd::PowerCommand::HVAC_POWER_OFF:
            set_hvac_power(false);
            break;
        case icd::PowerCommand::DISSIPATION_ON:
            set_dissipation(true);
            break;
        case icd::PowerCommand::DISSIPATION_OFF:
            set_dissipation(false);
            break;
        case icd::PowerCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

// monitor()'s snapshot plus the component classes' states.
void PowerManagement::fill_status(std::uint32_t frame) noexcept {
    status_.thermal_status = cooling_.thermal_status();
    status_.power_cmd_status = cmd_status_;
    status_.electrical_valid = electrical_fresh(frame);
    status_.generator_online = updated_ && reading_.generator_output > 0.0;
    status_.emergency_mode_active = emergency_battery_.emergency_mode_active();
    status_.apu_running = apu_battery_.apu_running();
    status_.hvac_powered = hvac_.powered();
    status_.dissipation_active = cooling_.dissipation_unit().active();
    status_.hvac_at_setpoint = hvac_.at_setpoint();
    status_.healthy = !bit_.failed;
    status_.main_battery_charge = main_battery_.charge_pct();
    status_.emergency_battery_charge = emergency_battery_.charge_pct();
    status_.apu_battery_charge = apu_battery_.charge_pct();
    status_.generator_output = reading_.generator_output;
    status_.total_power_consumption = reading_.total_power_consumption;
    status_.power_balance = reading_.generator_output - reading_.total_power_consumption;
    status_.main_bus_voltage = reading_.main_bus_voltage;
    status_.aux_bus_voltage = reading_.aux_bus_voltage;
    status_.generator_frequency = reading_.generator_frequency;
    status_.power_factor = reading_.power_factor;
    status_.coolant_temp = cooling_.coolant_temp_c();
    status_.cabin_temp = hvac_.cabin_temp_c();
    status_.fan_pct = cooling_.dissipation_unit().fan_pct();
    status_.heat_load = cooling_.heat_load_w();
}

}  // namespace fmofp::power
