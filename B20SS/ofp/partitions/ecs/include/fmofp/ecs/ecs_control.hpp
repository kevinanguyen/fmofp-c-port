#ifndef FMOFP_ECS_ECS_CONTROL_HPP
#define FMOFP_ECS_ECS_CONTROL_HPP

#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The environmental control terminal's logic (RT 4), ported from
// Systems/enviornmentalControlSystem: ecsControl.py (ECSControl's 2 Hz
// monitor_ecs: three threshold checks that only logged, then the oxygen
// generator's step and the climate's copy of the temperature reading),
// climate/climateControl.py (ClimateControl: a temperature and a humidity set by
// whoever calls it) and oxygenGenerationsys/oxygenControl.py (OxygenControl: a
// level that climbs 0.1 a pass to a cap of 23, and a rate that changes nothing).
// The cabin readings the Python never had (set_sensor_readings had no caller)
// come from the plant (PLANT_CABIN relayed as ECS_CABIN); without them
// monitor_ecs returned early, and so does step(). ecsConfig.xml's limits were
// never read by the code and are not here. Pure: ICD messages in, ICD messages
// out.

namespace fmofp::ecs {

constexpr double kTargetTemperatureC = 22.0;        // adjust_temperature: target_temp
constexpr double kTemperatureToleranceC = 0.5;      // abs(current - target) > 0.5
constexpr double kTargetPressureKpa = 101.3;        // adjust_pressure: target_pressure
constexpr double kPressureToleranceKpa = 0.5;
constexpr double kMinAirQualityPct = 95.0;          // adjust_air_quality: current_quality < 95
constexpr double kInitialOxygenPct = 21.0;          // OxygenControl.oxygen_level
constexpr double kOxygenStepPct = 0.1;              // generate_oxygen: += 0.1
constexpr double kOxygenCapPct = 23.0;              // capped at 23 to prevent hyperoxia
constexpr double kInitialOxygenRate = 1.0;          // oxygen_generation_rate, L/min
constexpr double kInitialClimateTemperatureC = 22.0;  // ClimateControl.current_temperature
constexpr double kInitialHumidityPct = 50.0;        // ClimateControl.current_humidity
constexpr std::uint32_t kCabinStaleFrames = 75;     // PLANT_CABIN is a 2 Hz reading: three periods
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr double kMaxPasses = 65535.0;              // ECS_STATUS.passes saturates

class EcsControl {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the cabin reading received this frame, or null. A reading with a new epoch runs
    // monitor_ecs once (an epoch of 0 is no reading); the rest is the state bookkeeping.
    void step(const icd::PlantCabin* cabin, std::uint32_t frame) noexcept;

    // monitor_ecs with sensor data: the three checks, generate_oxygen, climate.adjust_temperature(reading).
    // Public so the oracle tool can drive it directly.
    void monitor(double temperature_c, double pressure_kpa, double air_quality_pct) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::EcsModeCmd& cmd) noexcept;
    void command(const icd::EcsCmd& cmd, std::uint32_t frame) noexcept;

    // The sub-components' manual controls ECS_CMD carries (public for the oracle tool), as the Python wrote them.
    void set_oxygen_rate(double rate) noexcept;              // OxygenControl.adjust_generation_rate
    void set_humidity(double pct) noexcept;                  // ClimateControl.adjust_humidity
    void set_climate_temperature(double temperature_c) noexcept;  // ClimateControl.adjust_temperature

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::EcsStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] bool have_reading() const noexcept { return have_reading_; }
    [[nodiscard]] double temperature() const noexcept { return reading_.temperature; }
    [[nodiscard]] double pressure() const noexcept { return reading_.pressure; }
    [[nodiscard]] double air_quality() const noexcept { return reading_.air_quality; }
    [[nodiscard]] double climate_temperature() const noexcept { return climate_temperature_; }
    [[nodiscard]] double humidity() const noexcept { return humidity_; }
    [[nodiscard]] double oxygen_level() const noexcept { return oxygen_level_; }
    [[nodiscard]] double oxygen_rate() const noexcept { return oxygen_rate_; }
    [[nodiscard]] std::uint32_t passes() const noexcept { return passes_; }
    [[nodiscard]] bool temperature_adjusting() const noexcept { return temperature_adjusting_; }
    [[nodiscard]] bool pressure_adjusting() const noexcept { return pressure_adjusting_; }
    [[nodiscard]] bool purification_active() const noexcept { return purification_active_; }

private:
    [[nodiscard]] bool cabin_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    icd::PlantCabin reading_{};
    bool have_reading_{false};
    std::uint32_t reading_frame_{0};
    std::uint32_t passes_{0};
    double climate_temperature_{kInitialClimateTemperatureC};
    double humidity_{kInitialHumidityPct};
    double oxygen_level_{kInitialOxygenPct};
    double oxygen_rate_{kInitialOxygenRate};
    bool temperature_adjusting_{false};
    bool pressure_adjusting_{false};
    bool purification_active_{false};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::EcsStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::ecs

#endif
