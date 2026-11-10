#ifndef FMOFP_AIRFRAME_AIRFRAME_MANAGER_HPP
#define FMOFP_AIRFRAME_AIRFRAME_MANAGER_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The airframe systems terminal's logic (RT 20), ported from
// Systems/airframeSystemManagement/airframeControl.py: AirframeSystemManager's
// 1 Hz monitor_airframe over asmConfig.xml's three sensors (two strain gauges, a
// leading-edge temperature; the config lists no limits, so the readings are
// reported, not judged) and control_landing_gear, a state the class records
// without sensing a position. The readings the Python never had
// (set_sensor_reading had no caller) come from the plant (PLANT_AIRFRAME relayed
// as AFR_SENSORS); the gear command comes from the FMS (FMS_CONTROL_STATUS
// relayed as AFR_FMS_CONTROL, applied when its gear field changes) and from
// AFR_CMD by hand. Pure: ICD messages in, ICD messages out.

namespace fmofp::airframe {

constexpr std::uint32_t kSensorStaleFrames = 150;  // PLANT_AIRFRAME is a 1 Hz reading: three periods
constexpr std::uint32_t kFmsStaleFrames = 30;      // FMS_CONTROL_STATUS is 5 Hz
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kSensorCount = 3;

// asmConfig.xml's sensors table: id, type, location.
struct SensorInfo {
    std::uint8_t id;
    const char* type;
    const char* location;
};
constexpr std::array<SensorInfo, kSensorCount> kSensors{{{1, "strain", "Wing root"},
                                                         {2, "strain", "Fuselage"},
                                                         {3, "temperature", "LeadingEdges"}}};

// control_landing_gear's two commands ("deploy", "retract"); anything else the Python ignored with a warning.
enum class GearCommand : std::uint8_t { DEPLOY = 0, RETRACT = 1 };

class AirframeManager {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the sensor readings and the FMS control status received this frame, each null if
    // none arrived. A reading with a new epoch is monitor_airframe's pass; an FMS gear field that changed is a
    // gear command.
    void step(const icd::PlantAirframe* sensors, const icd::FmsControlStatus* fms, std::uint32_t frame) noexcept;

    // control_landing_gear: idempotent, records the commanded state, returns it. Public for the oracle tool.
    icd::GearState control_landing_gear(GearCommand what) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::AfrModeCmd& cmd) noexcept;
    void command(const icd::AfrCmd& cmd, std::uint32_t frame) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::AfrStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] icd::GearState gear_state() const noexcept { return gear_state_; }
    [[nodiscard]] bool have_reading() const noexcept { return have_reading_; }
    [[nodiscard]] double wing_root_strain() const noexcept { return reading_.wing_root_strain; }
    [[nodiscard]] double fuselage_strain() const noexcept { return reading_.fuselage_strain; }
    [[nodiscard]] double leading_edge_temp() const noexcept { return reading_.leading_edge_temp; }
    [[nodiscard]] std::uint32_t passes() const noexcept { return passes_; }

private:
    [[nodiscard]] bool sensors_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    icd::PlantAirframe reading_{};
    bool have_reading_{false};
    std::uint32_t reading_frame_{0};
    std::uint32_t passes_{0};
    icd::GearState gear_state_{icd::GearState::UNKNOWN};
    icd::GearPosition fms_gear_{icd::GearPosition::UNKNOWN};
    bool have_fms_gear_{false};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::AfrStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::airframe

#endif
