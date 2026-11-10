#ifndef FMOFP_HYDRAULICS_HYDRAULIC_CONTROLLER_HPP
#define FMOFP_HYDRAULICS_HYDRAULIC_CONTROLLER_HPP

#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The hydraulics terminal's logic (RT 19), ported from
// Systems/hydraulics/hydrControl.py: HydraulicSystemController's 1 Hz
// monitor_pressure over hydrConfig.xml's thresholds (nominal 3000, warning 2500,
// critical 2000 psi), the switch to the backup system on a CRITICAL pressure
// (for good: nothing switched back) and activate_backup by hand. The pressure
// the Python read was a constant 2800 compared for equality with the
// thresholds, which no real pressure ever meets: here the primary and backup
// pressures come from the plant (PLANT_HYDRAULICS relayed as HYD_PRESSURES) and
// the active system's is judged at-or-under (ICD README section 2). Pure: ICD
// messages in, ICD messages out.

namespace fmofp::hydraulics {

constexpr double kNominalPsi = 3000.0;             // hydrConfig.xml nominalPressure
constexpr double kWarningPsi = 2500.0;             // warningThreshold
constexpr double kCriticalPsi = 2000.0;            // criticalThreshold
constexpr std::uint32_t kPressureStaleFrames = 150;  // PLANT_HYDRAULICS is a 1 Hz reading: three periods
constexpr std::uint32_t kSelfTestFrames = 10;

class HydraulicController {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the pressures received this frame, or null. A reading with a new epoch runs
    // monitor_pressure once (an epoch of 0 is no reading).
    void step(const icd::PlantHydraulics* pressures, std::uint32_t frame) noexcept;

    // monitor_pressure on a reading: the active system's pressure against the thresholds; CRITICAL activates the
    // backup. Public so the oracle tool can drive it directly.
    void monitor(double primary, double backup) noexcept;
    void activate_backup() noexcept;  // HydraulicSystemController.activate_backup

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::HydModeCmd& cmd) noexcept;
    void command(const icd::HydCmd& cmd, std::uint32_t frame) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::HydStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] icd::HydraulicSystem active_system() const noexcept { return active_system_; }
    [[nodiscard]] icd::PressureStatus pressure_status() const noexcept { return pressure_status_; }
    [[nodiscard]] double primary_psi() const noexcept { return reading_.primary_psi; }
    [[nodiscard]] double backup_psi() const noexcept { return reading_.backup_psi; }
    [[nodiscard]] double active_psi() const noexcept;
    [[nodiscard]] bool have_reading() const noexcept { return have_reading_; }

private:
    [[nodiscard]] bool pressures_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    icd::PlantHydraulics reading_{};
    bool have_reading_{false};
    std::uint32_t reading_frame_{0};
    icd::HydraulicSystem active_system_{icd::HydraulicSystem::PRIMARY};
    icd::PressureStatus pressure_status_{icd::PressureStatus::OK};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::HydStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::hydraulics

#endif
