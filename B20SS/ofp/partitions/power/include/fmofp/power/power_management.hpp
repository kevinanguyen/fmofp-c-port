#ifndef FMOFP_POWER_POWER_MANAGEMENT_HPP
#define FMOFP_POWER_POWER_MANAGEMENT_HPP

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The power management terminal's logic (RT 8), ported from
// Systems/powerManagement: elec/powerManagementSystem.py (PowerManagementSystem's
// 1 Hz loop: the electrical balance routed through the main battery, the APU
// battery charged at a quarter, the emergency battery under its critical load,
// the avionics heat load into the coolant loop, the cabin's HVAC), the
// batteries of batts/ (Battery and its four kinds), the coolant loop of
// thermalManagement/coolingSystems/cooling.py with the fan-driven heat exchanger
// of thermalDissipation/activeDissipation.py, and the cabin climate of
// coolingSystems/HVAC.py. The readings the Python drew at random (generator
// output, consumption, bus voltages, frequency, power factor) come from the plant
// (PLANT_ELECTRICAL relayed as PWR_ELECTRICAL); the bookkeeping runs once per new
// reading with the Python's constant step of one second. Pure: ICD messages in,
// ICD messages out.

namespace fmofp::power {

constexpr double kDtHours = 1.0 / 3600.0;              // adjust_power_parameters(dt_hours=1.0/3600.0): the loop's constant step
constexpr double kHeatWattsPerKw = 6.0;                // cooling.set_heat_load('avionics_bus', total_power_consumption * 6.0)
constexpr double kApuChargeDivisor = 4.0;              // apu_battery.charge(amps / 4.0, dt_hours)
constexpr std::uint32_t kElectricalStaleFrames = 150;  // PLANT_ELECTRICAL is a 1 Hz reading: three periods
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kEquipmentCount = 3;             // MissionEquipmentBatteryBank: Radar, Comms, Mission Computer

// batts/mainBatt.Battery: the charge as a percentage of the rated amp-hours, with the charge and discharge
// arithmetic every kind of battery shares.
class Battery {
public:
    Battery() noexcept = default;
    Battery(double capacity, double voltage, double initial_charge) noexcept;

    // Draw `amps` for `dt_hours`: the amp-hours actually supplied (less than asked when the battery runs out,
    // and then the load reads 0, as the Python had it).
    double discharge(double amps, double dt_hours) noexcept;
    // Charge at `amps` for `dt_hours`: the amp-hours accepted (capped at full).
    double charge(double amps, double dt_hours) noexcept;

    [[nodiscard]] double capacity_remaining_ah() const noexcept { return capacity_ah_ * (charge_pct_ / 100.0); }
    [[nodiscard]] bool depleted() const noexcept { return charge_pct_ <= 0.0; }
    [[nodiscard]] double capacity_ah() const noexcept { return capacity_ah_; }
    [[nodiscard]] double nominal_voltage() const noexcept { return nominal_voltage_; }
    [[nodiscard]] double charge_pct() const noexcept { return charge_pct_; }
    [[nodiscard]] double load_amps() const noexcept { return load_amps_; }
    [[nodiscard]] bool online() const noexcept { return online_; }
    void set_online(bool on) noexcept { online_ = on; }

protected:
    void clear_load() noexcept { load_amps_ = 0.0; }

private:
    double capacity_ah_{0.0};
    double nominal_voltage_{0.0};
    double charge_pct_{0.0};
    double load_amps_{0.0};
    bool online_{true};
};

// MainBattery: 40 Ah at 24 V; an engine start draws 300 A for 5 s.
class MainBattery : public Battery {
public:
    static constexpr double kEngineStartAmps = 300.0;
    static constexpr double kEngineStartDurationHours = 5.0 / 3600.0;
    static constexpr double kStartMinimumPct = 20.0;

    MainBattery() noexcept : Battery(40.0, 24.0, 100.0) {}
    // start_engine: false under 20 % of charge, or when the start draw could not be met.
    bool start_engine() noexcept;
    double supply_essential_loads(double amps, double dt_hours) noexcept { return discharge(amps, dt_hours); }
};

// APUBattery: 15 Ah at 24 V; an APU light-off draws 150 A for 8 s.
class ApuBattery : public Battery {
public:
    static constexpr double kApuStartAmps = 150.0;
    static constexpr double kApuStartDurationHours = 8.0 / 3600.0;
    static constexpr double kStartMinimumPct = 15.0;

    ApuBattery() noexcept : Battery(15.0, 24.0, 100.0) {}
    // start_apu: true on a light-off, and when the APU is already running (no draw then); false under 15 %.
    bool start_apu() noexcept;
    void stop_apu() noexcept { apu_running_ = false; }
    double assist_main_battery_start(double amps, double dt_hours) noexcept { return discharge(amps, dt_hours); }
    [[nodiscard]] bool apu_running() const noexcept { return apu_running_; }

private:
    bool apu_running_{false};
};

// EmergencyBattery: 12 Ah at 24 V, sustaining a fixed 8 A critical load while the emergency mode is on.
class EmergencyBattery : public Battery {
public:
    static constexpr double kCriticalLoadAmps = 8.0;

    EmergencyBattery() noexcept : Battery(12.0, 24.0, 100.0) {}
    void activate_emergency_power() noexcept { emergency_mode_active_ = true; }
    void deactivate_emergency_power() noexcept;
    // sustain_critical_systems: one tick of the critical load while on; false when it could not be fully met.
    bool sustain_critical_systems(double dt_hours) noexcept;
    [[nodiscard]] double estimated_endurance_minutes() const noexcept {
        return (capacity_remaining_ah() / kCriticalLoadAmps) * 60.0;
    }
    [[nodiscard]] bool emergency_mode_active() const noexcept { return emergency_mode_active_; }

private:
    bool emergency_mode_active_{false};
};

// MissionEquipmentBattery: 6 Ah at 28 V for one piece of mission equipment.
class MissionEquipmentBattery : public Battery {
public:
    MissionEquipmentBattery() noexcept : Battery(6.0, 28.0, 100.0) {}
    // power_equipment: one tick of the equipment's draw; true when the full load was supplied (and the draw > 0).
    bool power_equipment(double draw_amps, double dt_hours) noexcept;
    [[nodiscard]] bool powering_equipment() const noexcept { return powering_equipment_; }

private:
    bool powering_equipment_{false};
};

// thermalDissipation/activeDissipation.ActiveDissipationUnit: the fan-driven heat exchanger.
class ActiveDissipationUnit {
public:
    static constexpr double kRejectionWPerPctPerC = 0.6;
    static constexpr double kMaxFanPct = 100.0;
    static constexpr double kMinFanPct = 10.0;

    void set_fan_speed(double pct) noexcept;
    void activate() noexcept;
    void deactivate() noexcept;
    // reject_heat: the watts rejected this tick; 0 when inactive or the coolant is at or below ambient.
    double reject_heat(double coolant_temp_c, double ambient_temp_c) noexcept;
    // auto_control: the proportional fan controller, full speed 5 C over the target.
    void auto_control(double coolant_temp_c, double target_temp_c) noexcept;
    [[nodiscard]] double fan_pct() const noexcept { return fan_pct_; }
    [[nodiscard]] bool active() const noexcept { return active_; }
    [[nodiscard]] double last_rejected_watts() const noexcept { return last_rejected_watts_; }

private:
    double fan_pct_{kMinFanPct};
    bool active_{true};
    double last_rejected_watts_{0.0};
};

// coolingSystems/cooling.CoolingSystem: the avionics coolant loop, one heat source (the Python's dictionary
// of named sources only ever held 'avionics_bus').
class CoolingSystem {
public:
    static constexpr double kThermalMassCPerWh = 0.02;
    static constexpr double kWarningTempC = 55.0;
    static constexpr double kCriticalTempC = 70.0;

    void set_heat_load(double watts) noexcept;
    void update(double dt_hours) noexcept;
    [[nodiscard]] icd::ThermalStatus thermal_status() const noexcept;
    [[nodiscard]] double coolant_temp_c() const noexcept { return coolant_temp_c_; }
    [[nodiscard]] double target_temp_c() const noexcept { return target_temp_c_; }
    [[nodiscard]] double ambient_temp_c() const noexcept { return ambient_temp_c_; }
    [[nodiscard]] double heat_load_w() const noexcept { return heat_load_w_; }
    [[nodiscard]] const ActiveDissipationUnit& dissipation_unit() const noexcept { return dissipation_; }
    [[nodiscard]] ActiveDissipationUnit& dissipation_unit() noexcept { return dissipation_; }

private:
    double coolant_temp_c_{20.0};
    double ambient_temp_c_{20.0};
    double target_temp_c_{25.0};
    double heat_load_w_{0.0};
    ActiveDissipationUnit dissipation_;
};

// coolingSystems/HVAC.HVACSystem: the cabin's temperature toward its setpoint at a rate the airflow sets.
class HvacSystem {
public:
    static constexpr double kMinTempC = 10.0;
    static constexpr double kMaxTempC = 30.0;
    static constexpr double kMinAirflowPct = 0.0;
    static constexpr double kMaxAirflowPct = 100.0;
    static constexpr double kResponseCPerPctPerHour = 0.15;

    void set_temperature(double target_c) noexcept;
    void set_airflow(double pct) noexcept;
    void power_off() noexcept { powered_ = false; }
    void power_on() noexcept { powered_ = true; }
    void update(double dt_hours) noexcept;
    [[nodiscard]] bool at_setpoint() const noexcept { return std::fabs(cabin_temp_c_ - setpoint_c_) < 0.5; }
    [[nodiscard]] double cabin_temp_c() const noexcept { return cabin_temp_c_; }
    [[nodiscard]] double setpoint_c() const noexcept { return setpoint_c_; }
    [[nodiscard]] double airflow_pct() const noexcept { return airflow_pct_; }
    [[nodiscard]] double ambient_temp_c() const noexcept { return ambient_temp_c_; }
    [[nodiscard]] bool powered() const noexcept { return powered_; }

private:
    double cabin_temp_c_{22.0};
    double ambient_temp_c_{15.0};
    double setpoint_c_{22.0};
    double airflow_pct_{50.0};
    bool powered_{true};
};

class PowerManagement {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the electrical reading received this frame (or null), the frame count. A reading
    // with a new epoch runs the 1 Hz bookkeeping; an epoch of 0 is no reading (a plant without the model).
    void step(const icd::PlantElectrical* electrical, std::uint32_t frame) noexcept;

    // adjust_power_parameters() and monitor() on one reading: the balance through the batteries, the heat load
    // through the coolant loop, the HVAC. Public so the oracle tool can drive it directly.
    void update(const icd::PlantElectrical& electrical) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::PwrModeCmd& cmd) noexcept;
    void command(const icd::PwrCmd& cmd, std::uint32_t frame) noexcept;

    // The controls PWR_CMD carries (public so the oracle tool can drive them).
    void set_generator_output(double kw, std::uint8_t sequence) noexcept;  // the hold on the plant's generator
    void generator_auto(std::uint8_t sequence) noexcept;
    void set_emergency_power(bool on) noexcept;
    bool start_apu() noexcept;
    void stop_apu() noexcept;
    bool start_engine() noexcept;
    void set_hvac_setpoint(double target_c) noexcept;
    void set_hvac_airflow(double pct) noexcept;
    void set_hvac_power(bool on) noexcept;
    void set_dissipation(bool on) noexcept;
    // The mission equipment bank's battery `index` powers its equipment for one step; false for a bad index.
    bool power_equipment(std::size_t index, double draw_amps) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::PwrStatus& status() const noexcept { return status_; }
    [[nodiscard]] const icd::PwrGenCmd& gen_cmd() const noexcept { return gen_cmd_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] bool updated() const noexcept { return updated_; }
    [[nodiscard]] const MainBattery& main_battery() const noexcept { return main_battery_; }
    [[nodiscard]] const EmergencyBattery& emergency_battery() const noexcept { return emergency_battery_; }
    [[nodiscard]] const ApuBattery& apu_battery() const noexcept { return apu_battery_; }
    [[nodiscard]] const MissionEquipmentBattery& equipment(std::size_t index) const noexcept {
        return equipment_[index < kEquipmentCount ? index : 0];
    }
    [[nodiscard]] const CoolingSystem& cooling() const noexcept { return cooling_; }
    [[nodiscard]] const HvacSystem& hvac() const noexcept { return hvac_; }

private:
    [[nodiscard]] bool electrical_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    MainBattery main_battery_;
    EmergencyBattery emergency_battery_;
    ApuBattery apu_battery_;
    std::array<MissionEquipmentBattery, kEquipmentCount> equipment_{};
    CoolingSystem cooling_;
    HvacSystem hvac_;
    icd::PlantElectrical reading_{};
    bool have_reading_{false};
    std::uint32_t reading_frame_{0};
    bool updated_{false};
    std::uint32_t frame_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::PwrStatus status_{};
    icd::PwrGenCmd gen_cmd_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::power

#endif
