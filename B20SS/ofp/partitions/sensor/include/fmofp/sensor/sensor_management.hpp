#ifndef FMOFP_SENSOR_SENSOR_MANAGEMENT_HPP
#define FMOFP_SENSOR_SENSOR_MANAGEMENT_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>

// The sensor management terminal's logic (RT 10), ported from
// Systems/sensorManagement: sensorService.py (SensorService: the six sensors'
// on/off states and the health rule, at 5 Hz) and sensorDataFusion.py
// (SensorDataFusion: the radar, LIDAR, infrared and ESM detections normalised
// into contacts, merged within a 5 degree bearing gate, aged out after 8 s).
// The detections were random numbers the Python's sensor managers invented;
// they come from the plant (PLANT_SENSOR_SCAN relayed as SNS_SCAN, PLANT_ESM
// relayed as SNS_ESM). The fused track count SensorService read from the radar
// data fusion is not here: the EICAS counts the fused tracks block it hears.
// Pure: ICD blocks and messages in, an ICD message out.

namespace fmofp::sensor {

constexpr std::uint32_t kUpdatePeriodFrames = 10;   // SensorService.POLL_HZ 5 (and SensorDataFusion.POLL_HZ)
constexpr std::uint32_t kContactTtlFrames = 400;    // CONTACT_TTL_S 8.0
constexpr double kGateDeg = 5.0;                    // _GATE_DEG: contacts within 5 degrees of bearing are one target
constexpr double kCorroborationStep = 0.1;          // confidence += 0.1 on a merge, capped at 1
constexpr double kMainRadarAccuracy = 0.95;         // ActiveSensorManager: Radar("Main Radar", 300000, 0.95, 10e9)
constexpr double kTfrRadarAccuracy = 0.99;          // Radar("Terrain Following Radar", 50000, 0.99, 15e9)
constexpr double kLidarAccuracy = 0.99;             // Lidar("LIDAR", 1000, 0.99, 1000000)
constexpr double kEsmConfidence = 0.7;              // _ingest_passive: an ESM signal's confidence
constexpr double kIrConfidence = 0.6;               // an infrared detection's
constexpr double kAirAboveDeg = 2.0;                // a LIDAR point above 2 degrees of elevation is AIR, else GROUND
constexpr std::uint32_t kScanStaleFrames = 30;      // SNS_SCAN is a 5 Hz set: three periods
constexpr std::uint32_t kEsmStaleFrames = 30;
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kMaxContacts = 192;           // the Python's table was unbounded
constexpr std::size_t kSensorCount = 6;             // sensor_id: MAIN_RADAR, TFR_RADAR, LIDAR, FLIR, MAWS, ESM

// SensorDataFusion.SensorSource and ContactClass.
enum class Source : std::uint8_t { RADAR = 0, LIDAR = 1, IR = 2, ESM = 3, FUSED = 4 };
enum class ContactClass : std::uint8_t { UNKNOWN = 0, AIR = 1, GROUND = 2, SURFACE = 3, EMITTER = 4 };
[[nodiscard]] const char* to_string(Source s) noexcept;
[[nodiscard]] const char* to_string(ContactClass c) noexcept;
// corroborated_by as a bit set of the four raw sources (bit = 1 << Source).
[[nodiscard]] constexpr std::uint8_t source_bit(Source s) noexcept { return static_cast<std::uint8_t>(1U << static_cast<unsigned>(s)); }

// One SensorContact. A field the Python held as None has its flag down.
struct Contact {
    bool used{false};
    std::uint16_t id{0};                       // the number of the Python's id (RAD-0001: origin RADAR, id 1)
    Source origin{Source::RADAR};              // the sensor that made it: the id's prefix
    Source source{Source::RADAR};              // FUSED once two sources corroborate
    ContactClass contact_class{ContactClass::UNKNOWN};
    bool has_range{false};
    double range_m{0.0};
    bool has_bearing{false};
    double bearing_deg{0.0};
    bool has_elevation{false};
    double elevation_deg{0.0};
    bool has_speed{false};
    double speed_ms{0.0};
    bool has_frequency{false};
    double frequency_hz{0.0};
    double signal_dbm{0.0};
    icd::RwrBand band{icd::RwrBand::UNKNOWN};
    double confidence{1.0};
    std::uint32_t last_seen{0};
    std::uint8_t corroborated{0};
};

// _classify_band: the band whose [low, high) holds the frequency, UNKNOWN ('?') outside every band.
[[nodiscard]] icd::RwrBand classify_band(double hz) noexcept;
// _bearing_delta: the smaller angle between two bearings; 360 when either is missing.
[[nodiscard]] double bearing_delta(bool has_a, double a, bool has_b, double b) noexcept;

class SensorManagement {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the sensor scans block that completed this frame (or null), the ESM intercepts
    // received this frame (or null), the frame count. Runs the service's update every kUpdatePeriodFrames.
    void step(const icd::PlantSensorScan* scan, const icd::PlantEsm* esm, std::uint32_t frame) noexcept;

    // SensorService._update with SensorDataFusion.update on the inputs given: the scan set (or none), the ESM
    // set (or none). Public so the oracle tool can drive it directly.
    void update(const icd::PlantSensorScan* scan, const icd::PlantEsm* esm, std::uint32_t frame) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::SnsModeCmd& cmd) noexcept;
    void command(const icd::SnsCmd& cmd, std::uint32_t frame) noexcept;

    // activate_sensor / deactivate_sensor; false for an undefined sensor.
    [[nodiscard]] bool set_active(icd::SensorId sensor, bool on) noexcept;
    [[nodiscard]] bool active(icd::SensorId sensor) const noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::SnsStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] std::size_t contact_count() const noexcept { return count_; }
    [[nodiscard]] const Contact& contact(std::size_t i) const noexcept { return table_[i < kMaxContacts ? i : 0]; }
    [[nodiscard]] std::uint16_t sequence() const noexcept { return seq_; }
    [[nodiscard]] std::uint8_t dropped() const noexcept { return dropped_; }
    [[nodiscard]] icd::SensorHealth health() const noexcept;

private:
    void ingest_scan(const icd::PlantSensorScan& scan, std::uint32_t frame) noexcept;
    void ingest_esm(const icd::PlantEsm& esm, std::uint32_t frame) noexcept;
    void merge_or_add(Contact& fresh, std::uint32_t frame) noexcept;
    void expire(std::uint32_t frame) noexcept;
    [[nodiscard]] std::uint16_t next_id() noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    std::array<Contact, kMaxContacts> table_{};  // in insertion order, compacted on expiry (the Python's dict)
    std::size_t count_{0};
    std::array<bool, kSensorCount> active_{};
    std::uint16_t seq_{0};
    std::uint8_t dropped_{0};
    bool updated_{false};                        // the health is INITIALISING before the first update
    std::uint32_t frame_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::PlantSensorScan scan_{};
    bool have_scan_{false};
    std::uint32_t scan_frame_{0};
    bool scan_consumed_{true};
    icd::PlantEsm esm_{};
    bool have_esm_{false};
    std::uint32_t esm_frame_{0};
    bool esm_consumed_{true};
    icd::SnsStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::sensor

#endif
