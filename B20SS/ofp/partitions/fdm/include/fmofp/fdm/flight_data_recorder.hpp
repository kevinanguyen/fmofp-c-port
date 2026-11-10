#ifndef FMOFP_FDM_FLIGHT_DATA_RECORDER_HPP
#define FMOFP_FDM_FLIGHT_DATA_RECORDER_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The flight data monitoring terminal's logic (RT 23), ported from
// Systems/flightDataMonitoring/fdmControl.py: FlightDataMonitoring's 2 Hz
// recording loop over fdmsConfig.xml's two recorders and two storage cards. The
// Python's collect_data logged the number 123 for every parameter; here the
// flight data recorder takes its three parameters (the time, the altitude, the
// airspeed) from the FMS flight data heard by broadcast into a ring of records,
// and the cockpit voice recorder has nothing to record on the bus. eject_storage
// marks a card out (the Python only logged it) and, as in the Python, stops
// nothing. Pure: ICD messages in, ICD messages out.

namespace fmofp::fdm {

constexpr std::size_t kRingCapacity = 512;
constexpr std::uint32_t kRecordFrames = 25;           // the loop's 2 Hz: a record every 25 frames
constexpr std::uint32_t kFlightDataStaleFrames = 15;  // BCAST_FMS_FLIGHT_DATA is 10 Hz: three periods
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kRecorderCount = 2;
constexpr std::size_t kSlotCount = 2;
constexpr std::size_t kMaxParameters = 3;
constexpr double kMaxRecordCount = 65535.0;           // FDM_STATUS.records saturates

// fdmsConfig.xml's recorders and storage cards.
struct Parameter {
    const char* name;
    const char* units;
};
struct RecorderInfo {
    std::uint8_t id;
    const char* description;
    const char* type;
    std::size_t parameter_count;
    std::array<Parameter, kMaxParameters> parameters;
};
struct StorageCard {
    std::uint8_t slot;
    const char* description;
    unsigned capacity_gb;
    const char* contents;
};
constexpr std::array<RecorderInfo, kRecorderCount> kRecorders{{
    {1, "Flight Data Recorder (FDR)", "solid-state", 3,
     {{{"UTC Time", "sec"}, {"Altitude", "ft"}, {"Airspeed", "kts"}}}},
    {2, "Cockpit Voice Recorder (CVR)", "solid-state", 1, {{{"Audio", "PCM"}, {nullptr, nullptr}, {nullptr, nullptr}}}},
}};
constexpr std::array<StorageCard, kSlotCount> kCards{{{1, "FDR PCMCIA Card", 16, "fdr"}, {2, "CVR PCMCIA Card", 8, "cvr"}}};

// One flight data recorder record: the three parameters of fdmsConfig.xml.
struct Record {
    std::uint32_t frame{0};  // the terminal's frame count, as the time
    double altitude_ft{0.0};
    double airspeed_kt{0.0};
};

class FlightDataRecorder {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the FMS flight data heard this frame, or null. Every kRecordFrames frames with fresh
    // flight data a record is taken; the rest is the state bookkeeping.
    void step(const icd::FmsFlightData* flight_data, std::uint32_t frame) noexcept;

    // One record into the ring (the oldest goes when it is full). Public for the oracle tool.
    void record(std::uint32_t frame, double altitude_ft, double airspeed_kt) noexcept;
    // eject_storage(slot): true when the slot held a card (now out); false when it did not.
    bool eject_storage(std::uint8_t slot) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::FdmModeCmd& cmd) noexcept;
    void command(const icd::FdmCmd& cmd, std::uint32_t frame) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::FdmStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] std::uint32_t records() const noexcept { return records_; }
    [[nodiscard]] std::size_t held() const noexcept { return held_; }
    // The i-th held record, 0 the oldest; a default record for an index past the end.
    [[nodiscard]] Record record_at(std::size_t index) const noexcept;
    [[nodiscard]] bool slot_present(std::uint8_t slot) const noexcept;
    [[nodiscard]] static bool valid_slot(std::uint8_t slot) noexcept { return slot >= 1 && slot <= kSlotCount; }

private:
    [[nodiscard]] bool flight_data_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    std::array<Record, kRingCapacity> ring_{};
    std::size_t next_{0};  // where the next record goes
    std::size_t held_{0};
    std::uint32_t records_{0};
    std::array<bool, kSlotCount> slot_present_{{true, true}};
    icd::FmsFlightData flight_data_{};
    bool have_flight_data_{false};
    std::uint32_t flight_data_frame_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::FdmStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::fdm

#endif
