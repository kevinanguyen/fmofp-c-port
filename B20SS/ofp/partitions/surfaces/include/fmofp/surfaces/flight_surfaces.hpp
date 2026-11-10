#ifndef FMOFP_SURFACES_FLIGHT_SURFACES_HPP
#define FMOFP_SURFACES_FLIGHT_SURFACES_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The flight surfaces terminal's logic (RT 21), ported from
// Systems/flightSurfaces/flightSurfaceService.py: the ten control surfaces
// (Surface: a position moved toward its command at a slew rate within its
// limits), the service's 50 Hz loop (_sync_from_fcc: the ailerons from the
// sensed roll, the elevators from the sensed pitch, the slats from the angle of
// attack; _step_all: every surface one step) and its manual controls
// (set_flaps, set_speedbrake, set_rudder, set_trim). The flight state the Python
// read from the flight control computer's data dictionary is the sensed flight
// state the plant publishes (PLANT_SENSORS relayed as FSF_SENSORS). The loop's
// SQLite snapshot of every pass is not carried. Pure: ICD messages in, ICD
// messages out.

namespace fmofp::surfaces {

constexpr double kDt = 0.02;                      // the loop's 50 Hz period: one minor frame (the Python measured it)
constexpr std::uint32_t kSensorStaleFrames = 3;   // FSF_SENSORS is 50 Hz: three periods (ICD README section 4)
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kSurfaceCount = 10;
constexpr std::size_t kTrimAxes = 3;              // pitch, roll, yaw
constexpr std::array<double, 4> kFlapDetents{0.0, 5.0, 15.0, 30.0};  // FLAP_DETENTS
constexpr double kAileronGain = 0.5;              // aileron_cmd = max(-25, min(25, -roll * 0.5))
constexpr double kAileronLimitDeg = 25.0;
constexpr double kElevatorGain = 0.8;             // elev_cmd = max(-30, min(30, -pitch * 0.8))
constexpr double kElevatorLimitDeg = 30.0;
constexpr double kSlatAoaDeg = 8.0;               // slat_cmd = 20.0 if aoa > 8.0 else 0.0
constexpr double kSlatExtendedDeg = 20.0;
constexpr double kSpeedbrakeDegPerPct = 0.6;      // set_speedbrake: max(0, min(60, pct * 0.6))
constexpr double kSpeedbrakeLimitDeg = 60.0;
constexpr double kRudderLimitDeg = 30.0;          // set_rudder: max(-30, min(30, deg))
constexpr double kTrimLimitDeg = 10.0;            // set_trim: max(-10, min(10, deg))

// The ten surfaces, in the order of the Python's _all list and of FSF_POSITIONS.
enum class SurfaceId : std::uint8_t {
    AILERON_L = 0,
    AILERON_R,
    ELEVATOR_L,
    ELEVATOR_R,
    RUDDER,
    FLAP_L,
    FLAP_R,
    SLAT_L,
    SLAT_R,
    SPEEDBRAKE
};

// flightSurfaceService.Surface: one control surface.
struct Surface {
    double position{0.0};     // degrees, positive = trailing-edge down / right
    double cmd{0.0};          // commanded position
    double rate_deg_s{30.0};  // slew rate
    double limit_lo{-30.0};
    double limit_hi{30.0};
    bool healthy{true};

    // Surface.step: toward cmd by at most rate_deg_s x dt, then clamped to the limits.
    void step(double dt) noexcept;
};

class FlightSurfaces {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: `sensors` is the FSF_SENSORS received this frame, or null. One pass of the loop:
    // _sync_from_fcc on a fresh copy whose roll, pitch and angle of attack are NORMAL (the Python synced from the
    // flight control computer's current data every pass), _step_all(kDt), the state bookkeeping.
    void step(const icd::PlantSensors* sensors, std::uint32_t frame) noexcept;

    // The loop's two halves, public so the oracle tool can drive them with the Python's own inputs.
    void sync_from_fcc(double roll_deg, double pitch_deg, double aoa_deg) noexcept;  // _sync_from_fcc's body
    void step_all(double dt) noexcept;                                               // _step_all

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::FsfModeCmd& cmd) noexcept;
    void command(const icd::FsfCmd& cmd, std::uint32_t frame) noexcept;

    // The manual controls FSF_CMD carries (public for the oracle tool), as the Python wrote them.
    void set_flaps(double detent_deg) noexcept;             // the nearest of 0, 5, 15, 30; a tie goes to the lower
    void set_speedbrake(double pct) noexcept;               // max(0, min(60, pct * 0.6)) degrees
    void set_rudder(double deg) noexcept;                   // max(-30, min(30, deg))
    bool set_trim(icd::TrimAxis axis, double deg) noexcept;  // max(-10, min(10, deg)); false for an unknown axis

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::FsfStatus& status() const noexcept { return status_; }
    [[nodiscard]] const icd::FsfPositions& positions() const noexcept { return positions_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] const Surface& surface(SurfaceId id) const noexcept { return surfaces_[index_of(id)]; }
    [[nodiscard]] double flap_cmd() const noexcept { return flap_cmd_; }
    [[nodiscard]] double trim(icd::TrimAxis axis) const noexcept;  // 0 for an unknown axis
    [[nodiscard]] bool slats_extended() const noexcept { return slats_extended_; }
    [[nodiscard]] bool all_healthy() const noexcept;

    static constexpr std::size_t index_of(SurfaceId id) noexcept { return static_cast<std::size_t>(id); }

private:
    [[nodiscard]] bool sensors_fresh(std::uint32_t frame) const noexcept;
    void fill_outputs(std::uint32_t frame) noexcept;

    std::array<Surface, kSurfaceCount> surfaces_{};
    std::array<double, kTrimAxes> trim_{};  // pitch, roll, yaw
    double flap_cmd_{0.0};
    bool slats_extended_{false};
    bool have_sensors_{false};
    std::uint32_t sensor_frame_{0};
    std::uint32_t frame_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::FsfStatus status_{};
    icd::FsfPositions positions_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::surfaces

#endif
