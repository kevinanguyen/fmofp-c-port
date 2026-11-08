#ifndef FMOFP_DEFENSIVE_DEFENSIVE_SYSTEMS_HPP
#define FMOFP_DEFENSIVE_DEFENSIVE_SYSTEMS_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>

// The defensive systems terminal's logic (RT 22), ported from
// Systems/defensiveSys/defensiveService.py (DefensiveService): the radar
// warning receiver's contact table, fed by the hostile fused air tracks (heard
// by broadcast) and the ESM intercepts (the plant's PLANT_ESM, relayed as
// DEF_ESM: the Python's passive sensor manager drew them inside the service),
// the chaff and flare inventories with the automatic flare salvo and its
// cooldown, and the ECM mode. The Python's 2 Hz loop is an update every 25
// frames; its seconds are frames. Pure: ICD messages and blocks in, ICD
// messages and a block out.

namespace fmofp::defensive {

constexpr std::uint8_t kChaffMax = 60;              // DefensiveService.CHAFF_MAX
constexpr std::uint8_t kFlareMax = 30;              // FLARE_MAX
constexpr std::uint8_t kSalvoSize = 2;              // SALVO_SIZE
constexpr std::uint32_t kCooldownFrames = 150;      // COOLDOWN_S 3.0 s
constexpr std::uint32_t kTrackTtlFrames = 500;      // TRACK_TTL 10.0 s
constexpr std::uint32_t kUpdatePeriodFrames = 25;   // _update_loop: time.sleep(0.5)
constexpr std::uint32_t kFusedStaleFrames = 75;     // the fused tracks block arrives every 25 frames: three periods
constexpr std::uint32_t kEsmStaleFrames = 30;       // DEF_ESM is 5 Hz: three periods
constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::size_t kMaxContacts = icd::DefRwrContacts::kMaxContact;  // the Python's table was unbounded
constexpr std::size_t kMaxEsmSignals = 5;           // ESMSensor.detect: randint(0, 5)
constexpr std::uint8_t kEsmPriority = 3;            // an ESM intercept's priority
constexpr std::uint8_t kLowestPriority = 4;         // THREAT_DB["UNKNOWN"]["pri"]
constexpr double kMetresPerNm = 1852.0;

// One row of the contact table (RWRContact). `order` is the Python dict's insertion order, which its stable
// sort by priority preserved.
struct Contact {
    bool used{false};
    icd::RwrSource source{icd::RwrSource::FUSION};
    icd::RwrBand band{icd::RwrBand::UNKNOWN};
    std::uint16_t id{0};
    double bearing_deg{0.0};
    double range_nm{0.0};
    icd::ThreatType type{icd::ThreatType::UNK};
    std::uint8_t priority{kLowestPriority};
    bool hostile{false};
    std::uint32_t last_seen{0};
    std::uint32_t order{0};
};

// THREAT_DB by a fused track's classification: FIGHTER and BOMBER are the only classes the table names (its
// SA-10, SA-15 and SA-6 entries match no classification the radars produce); everything else is UNKNOWN.
struct ThreatEntry {
    icd::RwrBand band;
    icd::ThreatType type;
    std::uint8_t priority;
};
[[nodiscard]] ThreatEntry threat_entry(icd::TargetClass classification) noexcept;

// _classify_freq: the band whose [low, high) holds the frequency, UNKNOWN ('?') outside every band.
[[nodiscard]] icd::RwrBand classify_frequency(double hz) noexcept;

// FusedTrack.bearing_deg and range_nm from a position in metres east, north and up of the aircraft.
[[nodiscard]] double bearing_of(double east, double north) noexcept;
[[nodiscard]] double range_nm_of(double east, double north, double up) noexcept;

class DefensiveSystems {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the fused tracks block that completed this frame (or null), the ESM intercepts
    // received this frame (or null), the frame count. Runs the RWR update every kUpdatePeriodFrames.
    void step(const icd::RdrFusedTracks* fused, const icd::PlantEsm* esm, std::uint32_t frame) noexcept;

    // The body of the Python's loop, _update_rwr then _auto_dispense, on the inputs given: the hostile fused
    // tracks (or none), a new ESM detection set (or none). Public so the oracle tool can drive it directly.
    void update_rwr(const icd::RdrFusedTracks* fused, const icd::PlantEsm* esm, std::uint32_t frame) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::DefModeCmd& cmd) noexcept;
    void command(const icd::DefCmd& cmd, std::uint32_t frame) noexcept;

    // The manual controls themselves (dispense_chaff, dispense_flares, set_ecm_mode) and the scenario engine's
    // threat injection; each returns what the Python returned (cartridges released; accepted or not).
    [[nodiscard]] std::uint8_t dispense_chaff(std::uint8_t count) noexcept;
    [[nodiscard]] std::uint8_t dispense_flares(std::uint8_t count, std::uint32_t frame) noexcept;
    [[nodiscard]] bool set_ecm_mode(icd::EcmMode mode) noexcept;
    [[nodiscard]] bool inject_threat(std::uint8_t threat_id, double bearing_deg, double range_nm, icd::RwrBand band,
                                     icd::ThreatType type, std::uint8_t priority, std::uint32_t frame) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::DefStatus& status() const noexcept { return status_; }
    [[nodiscard]] const icd::DefRwrContacts& contacts() const noexcept { return contacts_; }
    // Rebuilds contacts() from the table as the next update would publish it (get_rwr_contacts() read the live
    // table): for the oracle tool, which asks between updates.
    void refresh_contacts() noexcept;
    // True once after each RWR update: the contacts block has a new version to publish.
    [[nodiscard]] bool take_contacts_update() noexcept;
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] std::size_t contact_count() const noexcept;
    [[nodiscard]] std::uint8_t chaff() const noexcept { return chaff_; }
    [[nodiscard]] std::uint8_t flares() const noexcept { return flares_; }

private:
    [[nodiscard]] std::size_t find(icd::RwrSource source, icd::RwrBand band, std::uint16_t id) const noexcept;
    [[nodiscard]] std::size_t add(const Contact& contact) noexcept;
    void ingest_fused(const icd::RdrFusedTracks& fused, std::uint32_t frame) noexcept;
    void ingest_esm(const icd::PlantEsm& esm, std::uint32_t frame) noexcept;
    void expire(std::uint32_t frame) noexcept;
    void auto_dispense(std::uint32_t frame) noexcept;
    [[nodiscard]] std::uint8_t high_priority_count() const noexcept;
    void build_contacts() noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    std::array<Contact, kMaxContacts> table_{};
    std::uint32_t next_order_{0};
    std::uint32_t frame_{0};            // the last frame any entry point saw: what the status is filled for
    std::uint8_t chaff_{kChaffMax};
    std::uint8_t flares_{kFlareMax};
    bool has_dispensed_{false};         // _last_dispense was 0.0 (the epoch) until the first release
    std::uint32_t last_dispense_{0};
    icd::EcmMode ecm_mode_{icd::EcmMode::STANDBY};
    bool jamming_active_{false};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    std::uint8_t auto_salvos_{0};
    std::uint8_t chaff_released_{0};
    std::uint8_t flares_released_{0};
    std::uint8_t dropped_{0};
    std::uint8_t updates_{0};
    bool contacts_update_{false};
    icd::RdrFusedTracks fused_{};
    bool have_fused_{false};
    std::uint32_t fused_frame_{0};
    icd::PlantEsm esm_{};
    bool have_esm_{false};
    std::uint32_t esm_frame_{0};
    bool esm_consumed_{true};
    icd::DefStatus status_{};
    icd::DefRwrContacts contacts_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::defensive

#endif
