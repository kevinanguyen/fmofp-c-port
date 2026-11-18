#ifndef FMOFP_CAS_CREW_ALERTING_HPP
#define FMOFP_CAS_CREW_ALERTING_HPP

#include <array>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>

// The crew alerting terminal's logic (RT 26), ported from the frozen
// Interfaces/userInterface/displays/eicas.py, which decided its alert list in
// the display process at 10 Hz: _compute_alerts (engine, fuel, hydraulic,
// electrical, the maximum-thrust advisory), the GCAS and performance rows
// _poll_data appended, _compute_defensive_alerts, _compute_sensor_alerts and
// _compute_weather_alerts. The rules are evaluate(), pure, over AlertInputs;
// CrewAlerting gathers the inputs from what the bus delivered (an input counts
// as heard for 100 frames, the displays' two seconds) and publishes CAS_ALERTS.
// The departures (the hydraulic rows judge the hydraulics terminal) are in ICD
// README section 2.

namespace fmofp::cas {

// One per alert, in the order eicas.py built its list (fmofp_bus/cas_alerts.py has the texts).
enum class Alert : std::uint8_t {
    kEngEgtHigh,
    kEngEgtCaution,
    kEngEgtUnknown,
    kEngOilPressLo,
    kEngOilPressLow,
    kEngOilPressUnknown,
    kEngOilTempHigh,
    kEngOilTempUnknown,
    kEngVibrationHigh,
    kEngVibUnknown,
    kFuelQtyUnknown,
    kFuelQuantityLow,
    kFuelQuantityCaution,
    kFuelBalanceUnknown,
    kFuelImbalance,
    kHydAUnknown,
    kHydALow,
    kHydAReduced,
    kHydBUnknown,
    kHydBLow,
    kHydBReduced,
    kHydCUnknown,
    kHydCLow,
    kHydCReduced,
    kElecGen1Unknown,
    kElecGen1Fault,
    kElecGen2Unknown,
    kElecGen2Fault,
    kElecBusVoltsUnknown,
    kElecMainBusLo,
    kEngMaxContinuousThrust,
    kFcsPullUp,
    kFcsSinkRate,
    kFcsTerrain,
    kFcsAltLow,
    kPerfGForce,
    kPerfAngleOfAttack,
    kPerfRoll,
    kPerfPitch,
    kPerfVerticalSpeed,
    kRwrHighPriThreats,
    kRwrThreatContacts,
    kCmdsChaffDepleted,
    kCmdsChaffLow,
    kCmdsFlaresDepleted,
    kCmdsFlaresLow,
    kEwEcmActive,
    kSensorSystemFault,
    kSensorDegradedMode,
    kFusionHostileTracks,
    kFusionHostileTrack,
    kWxMicroburst,
    kWxSevereWindshear,
    kWxModerateWindshear,
    kWxWindshearAhead,
    kWxExtremeTurbulence,
    kWxSevereTurbulence,
    kWxModerateTurbulence,
    kWxLightTurbulence,
    kCount,
};

constexpr std::size_t kAlertCount = static_cast<std::size_t>(Alert::kCount);

enum class Severity : std::uint8_t { kWarning, kCaution, kAdvisory };

[[nodiscard]] Severity severity_of(Alert alert) noexcept;
[[nodiscard]] const char* name_of(Alert alert) noexcept;  // the CAS_ALERTS field name

constexpr std::uint32_t kStaleFrames = 100;  // fmofp_display STALE_AFTER_S and FieldValidity: two seconds

// eicas.py's thresholds.
constexpr double kEgtWarningC = 800.0;
constexpr double kEgtCautionC = 750.0;
constexpr double kOilPressWarningPsi = 40.0;
constexpr double kOilPressCautionPsi = 50.0;
constexpr double kOilTempWarningC = 130.0;
constexpr double kVibrationCaution = 0.8;
constexpr double kFuelWarningKg = 500.0;
constexpr double kFuelCautionKg = 1000.0;
constexpr double kFuelImbalanceKg = 200.0;
constexpr double kHydWarningPsi = 2000.0;
constexpr double kHydCautionPsi = 2500.0;
constexpr double kMainBusLowV = 100.0;
constexpr double kMaxContinuousThrustPct = 95.0;
constexpr unsigned kChaffLow = 10;
constexpr unsigned kFlaresLow = 5;
constexpr unsigned kFusionWarningTracks = 3;
constexpr std::uint8_t kChaffFull = 60;   // eicas.py's default while the defensive service is silent
constexpr std::uint8_t kFlaresFull = 30;

// What the rules read: eicas.py's state at the moment it built its list. A `valid` flag is its FieldValidity.
struct AlertInputs {
    double thrust_pct{70.0};  // the profile's engine power x 100 (always given: README section 2)
    bool egt_valid{true};     // marked with the thrust
    bool oil_press_valid{false};
    double oil_psi{0.0};
    bool oil_temp_valid{false};
    double oil_temp_c{0.0};
    bool vib_valid{false};
    double vib{0.0};
    bool fuel_total_valid{false};
    double fuel_total_kg{0.0};
    bool fuel_balance_valid{false};
    double fuel_balance_kg{0.0};
    std::array<bool, 3> hyd_valid{};  // systems A, B, C
    std::array<double, 3> hyd_psi{};
    bool gen_1_valid{false};
    bool gen_1_ok{true};
    bool gen_2_valid{false};
    bool gen_2_ok{true};
    bool main_bus_valid{false};
    double main_bus_v{0.0};
    // The GCAS rows (get_alerts) and the performance rows (get_exceedances), while their messages are heard.
    bool gcas_pullup{false};
    bool gcas_sink_rate{false};
    bool gcas_terrain{false};
    bool gcas_alt_low{false};
    double gcas_vertical_speed{0.0};
    double gcas_altitude{0.0};
    double gcas_terrain_clearance{0.0};
    std::array<bool, 5> perf_exceed{};  // g, angle of attack, roll, pitch, vertical speed (LIMITS' order)
    // The defensive service's dictionary (its defaults while it is silent).
    unsigned rwr_hostile{0};
    unsigned rwr_high_priority{0};
    unsigned chaff_remaining{kChaffFull};
    unsigned flares_remaining{kFlaresFull};
    bool ecm_active{false};
    icd::SensorHealth sensor_health{icd::SensorHealth::INITIALISING};  // anything but FAULT and DEGRADED: no alert
    unsigned fused_hostile{0};
    bool wx_microburst{false};
    icd::ShearSeverity wx_windshear{icd::ShearSeverity::NONE};
    icd::TurbulenceCategory wx_turbulence{icd::TurbulenceCategory::NONE};
};

using AlertSet = std::array<bool, kAlertCount>;

// The rules, decision for decision as eicas.py made them.
[[nodiscard]] AlertSet evaluate(const AlertInputs& in) noexcept;

// The flight mode's engine power, as fmsControl's profiles give it (NORMAL's 0.7 when the FMS is not heard).
[[nodiscard]] double profile_engine_power(const icd::FmsStatus* fms) noexcept;

// What arrived in one frame; null for anything not received this frame.
struct Received {
    const icd::FmsStatus* fms{nullptr};
    const icd::FcsGcasAlerts* gcas{nullptr};
    const icd::FcsPerfStatus* perf{nullptr};
    const icd::EngEngineStatus* engine{nullptr};
    const icd::EngFuelStatus* fuel{nullptr};
    const icd::RdrWxScan* weather{nullptr};
    const icd::DefStatus* defensive{nullptr};
    const icd::SnsStatus* sensor{nullptr};
    const icd::PwrStatus* power{nullptr};
    const icd::HydStatus* hydraulics{nullptr};
    const icd::RdrFusedTracks* fused{nullptr};
    const icd::DefRwrContacts* contacts{nullptr};
};

class CrewAlerting {
public:
    [[nodiscard]] Status init() noexcept;
    void reset() noexcept;
    void start_self_test() noexcept;

    // The partition's frame: keep what arrived, gather the inputs, evaluate the rules, fill CAS_ALERTS.
    void step(const Received& received, std::uint32_t frame) noexcept;

    void command_mode(const icd::CasModeCmd& cmd) noexcept;

    [[nodiscard]] const icd::CasAlerts& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] const AlertInputs& inputs() const noexcept { return inputs_; }
    [[nodiscard]] const AlertSet& alerts() const noexcept { return alerts_; }

private:
    template <typename Message>
    struct Held {
        Message message{};
        std::uint32_t frame{0};
        bool have{false};
    };

    template <typename Message>
    static void keep(Held<Message>& held, const Message* message, std::uint32_t frame) noexcept;
    template <typename Message>
    [[nodiscard]] static const Message* heard(const Held<Message>& held, std::uint32_t frame) noexcept;

    void gather(std::uint32_t frame) noexcept;
    void gather_engine(std::uint32_t frame) noexcept;
    void gather_systems(std::uint32_t frame) noexcept;
    void gather_tactical(std::uint32_t frame) noexcept;
    [[nodiscard]] bool any_heard(std::uint32_t frame) const noexcept;
    void fill_status() noexcept;

    Held<icd::FmsStatus> fms_{};
    Held<icd::FcsGcasAlerts> gcas_{};
    Held<icd::FcsPerfStatus> perf_{};
    Held<icd::EngEngineStatus> engine_{};
    Held<icd::EngFuelStatus> fuel_{};
    Held<icd::RdrWxScan> weather_{};
    Held<icd::DefStatus> defensive_{};
    Held<icd::SnsStatus> sensor_{};
    Held<icd::PwrStatus> power_{};
    Held<icd::HydStatus> hydraulics_{};
    Held<icd::RdrFusedTracks> fused_{};
    Held<icd::DefRwrContacts> contacts_{};

    AlertInputs inputs_{};
    AlertSet alerts_{};
    bool computed_{false};
    icd::CasAlerts status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
};

}  // namespace fmofp::cas

#endif
