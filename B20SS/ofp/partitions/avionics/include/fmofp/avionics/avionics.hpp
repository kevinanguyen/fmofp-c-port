#ifndef FMOFP_AVIONICS_AVIONICS_HPP
#define FMOFP_AVIONICS_AVIONICS_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The avionics terminal's logic (RT 1), ported from four Python modules:
// Systems/avionics/hardwareHealth/LRUstatus.py (LRUStatusMonitor: the health of
// every line replaceable unit, with the scenario engine's forced faults),
// hardwareHealth/builtInTesting.py with Systems/builtInTestSystems/bitControl.py
// (the power-on, periodic and initiated built-in tests of bitsConfig.xml),
// Systems/fmFitness/fmStatus.py (FlightManagementFitness: the threshold rule of
// fmfConfig.xml) and Systems/configurationManagement/swConfigure.py
// (SoftwareConfigManager: the versions and data loads of swcmConfig.xml).
//
// The Python reached into the other subsystems' get_status(); on the bus the
// avionics computer sees a terminal only through the bus controller's report
// (AVN_BUS_HEALTH). Pure: ICD messages in, ICD messages out.

namespace fmofp::avionics {

constexpr std::size_t kCatalogueCount = 11;  // _build_catalogue()'s entries
constexpr std::size_t kMaxDeclared = 4;      // scenario-declared entries (the Python's table was unbounded)
constexpr std::size_t kMaxLrus = kCatalogueCount + kMaxDeclared;
constexpr std::size_t kKeyChars = 24;   // AVN_CMD's key: twelve words of two characters
constexpr std::size_t kNameChars = 48;  // "<key> (scenario-declared)"
constexpr std::uint8_t kNoTerminal = 0xFFU;
constexpr std::uint32_t kBusHealthStaleFrames = 150;  // AVN_BUS_HEALTH is a 1 Hz report: three periods
constexpr std::uint32_t kSelfTestFrames = 10;
// time.time() stood far from zero, so a periodic test that had never run was always due at the first pass:
// the terminal's clock is this plus the frames it has counted.
constexpr double kClockOriginS = 1.0e9;
constexpr double kFrameS = 0.02;

using Key = std::array<char, kKeyChars + 1>;
using Name = std::array<char, kNameChars + 1>;

// What the bus controller reports of every terminal (AVN_BUS_HEALTH), bit n for RT n.
struct BusView {
    bool valid{false};
    std::uint32_t listed{0};
    std::uint32_t responded{0};
    std::uint32_t answering{0};
    std::uint32_t status{0};
    std::uint32_t healthy{0};
    std::uint32_t bit_failed{0};
    std::uint32_t normal{0};
    std::uint32_t degraded{0};
    std::uint32_t failure{0};

    [[nodiscard]] bool running(std::uint8_t rt) const noexcept;  // answering now
    [[nodiscard]] bool started(std::uint8_t rt) const noexcept;  // listed and has answered once
};

[[nodiscard]] BusView view_of(const icd::AvnBusHealth& report) noexcept;

// ---- LRUstatus.py -----------------------------------------------------------------------------------------

// The 'health' string of a subsystem's get_status(), as far as _derive_health read it.
enum class ReportedHealth : std::uint8_t { kOther, kNominal, kDegraded, kFault };

// A subsystem's get_status() dictionary, as far as _derive_health read it.
struct SystemStatus {
    bool empty{true};  // {} or None
    bool running{true};
    bool healthy{true};
    ReportedHealth health{ReportedHealth::kOther};
};

// _derive_health(status, lru): `has_bit_result` and `bit_result` are the LRU's last BIT result.
[[nodiscard]] icd::LruHealth derive_health(const SystemStatus& status, bool has_bit_result,
                                           icd::BitStatus bit_result) noexcept;

struct Lru {
    Key lru_id{};
    Name name{};
    Key system_key{};
    std::uint8_t rt{kNoTerminal};  // the terminal that carries it; none for a scenario-declared entry
    bool declared{false};          // made by force_fault for a key that named no LRU
    icd::LruHealth health{icd::LruHealth::UNKNOWN};
    bool forced{false};
    icd::LruHealth forced_state{icd::LruHealth::UNKNOWN};
    std::uint32_t forced_order{0};  // the forced faults keep the order they were set in
    bool has_bit_result{false};
    icd::BitStatus bit_result{icd::BitStatus::PENDING};
};

class LruMonitor {
public:
    void init() noexcept;

    // _poll_all(): every catalogued LRU from the bus view, the forced state over it. A view that is not valid
    // is the poll that raised: UNKNOWN.
    void poll(const BusView& view) noexcept;

    // resolve_lru_id(key): the table index, or kMaxLrus when nothing matches.
    [[nodiscard]] std::size_t resolve(const char* key) const noexcept;
    // force_fault(key, state): the index the fault was applied to, or kMaxLrus when the key named no LRU and
    // the declared slots were all taken.
    std::size_t force_fault(const char* key, icd::LruHealth state) noexcept;
    // clear_forced_fault(key), key null for all: the number cleared.
    std::size_t clear_forced_fault(const char* key) noexcept;
    // update_bit_result(lru_id, result): false when the id is not in the table.
    bool update_bit_result(const char* lru_id, icd::BitStatus result) noexcept;

    [[nodiscard]] icd::LruHealth overall_health() const noexcept;
    [[nodiscard]] std::size_t fault_count() const noexcept;  // len(get_faults())
    [[nodiscard]] std::size_t forced_count() const noexcept;
    [[nodiscard]] std::size_t count() const noexcept { return count_; }
    [[nodiscard]] const Lru& at(std::size_t index) const noexcept { return lrus_[index < count_ ? index : 0]; }

private:
    [[nodiscard]] std::size_t find_id(const char* lru_id) const noexcept;
    void remove(std::size_t index) noexcept;
    void clear_one(std::size_t index) noexcept;

    std::array<Lru, kMaxLrus> lrus_{};
    std::size_t count_{0};
    std::uint32_t next_order_{1};
};

// ---- builtInTesting.py and bitControl.py ------------------------------------------------------------------

// The system names of bitsConfig.xml.
enum class BitSystem : std::uint8_t {
    kFlightControlComputer,
    kNavigationSystem,
    kMissionComputer,
    kDatalink,
    kSatcom,
    kRadios,
    kWeaponSystem,
    kFireControlRadar,
};

constexpr std::size_t kPostResults = 6;       // POST-FCC and POST-NAV, three components each
constexpr std::size_t kPeriodicTests = 2;     // BIT-AVIONICS, BIT-COMM
constexpr std::size_t kPeriodicResults = 5;   // two systems and three
constexpr std::size_t kInitiatedResults = 15; // six, five, and two interface tests of two sides

// _probe_system(system, component): PASS while the system's terminal is answering, FAIL when it is not, ABORT
// when there is no bus view to judge by. A system with no terminal behind it passes (README section 2).
[[nodiscard]] icd::BitStatus probe_system(BitSystem system, const BusView& view) noexcept;

struct InitiatedSummary {
    std::array<icd::BitStatus, kInitiatedResults> results{};
    std::uint8_t passed{0};
    std::uint8_t failed{0};
    std::uint8_t aborted{0};
};

class BuiltInTest {
public:
    void init() noexcept;

    // PowerOnSelfTest.run(self_tests).
    void run_post(const BusView& view) noexcept;
    // PeriodicBIT.run_due(periodic_tests) at `now_s`: the number of results it returned.
    std::size_t run_due(double now_s, const BusView& view) noexcept;
    // InitiatedBIT.run_all(...): its own results; the power-on results and the periodic schedule are untouched.
    InitiatedSummary run_all(const BusView& view) noexcept;

    [[nodiscard]] bool post_complete() const noexcept { return post_complete_; }
    [[nodiscard]] const std::array<icd::BitStatus, kPostResults>& post_results() const noexcept { return post_; }
    [[nodiscard]] const std::array<icd::BitStatus, kPeriodicResults>& periodic_results() const noexcept {
        return periodic_;
    }
    // len(PeriodicBIT.get_results(test_id)).
    [[nodiscard]] std::uint32_t stored(std::size_t test) const noexcept {
        return stored_[test < kPeriodicTests ? test : 0];
    }
    [[nodiscard]] const InitiatedSummary& last_initiated() const noexcept { return initiated_; }
    [[nodiscard]] std::uint8_t initiated_runs() const noexcept { return initiated_runs_; }

private:
    std::array<icd::BitStatus, kPostResults> post_{};
    bool post_complete_{false};
    std::array<icd::BitStatus, kPeriodicResults> periodic_{};
    std::array<double, kPeriodicTests> last_run_{};
    std::array<std::uint32_t, kPeriodicTests> stored_{};
    InitiatedSummary initiated_{};
    std::uint8_t initiated_runs_{0};
};

// ---- fmStatus.py ------------------------------------------------------------------------------------------

constexpr std::size_t kFitnessComponents = 3;
constexpr int kFitnessCpu = 75;     // run()'s placeholder metrics
constexpr int kFitnessMemory = 80;

class FmFitness {
public:
    void init() noexcept;
    // check_thresholds(component, metrics): the status it logged.
    [[nodiscard]] static icd::FitnessStatus check_thresholds(int cpu, int memory) noexcept;
    // One pass of run(): every component against the placeholder metrics.
    void step() noexcept;
    // handle_redundancy(component): true when the component is the one with a backup.
    bool handle_redundancy(icd::FitnessComponent component) noexcept;

    [[nodiscard]] icd::FitnessStatus status(std::size_t component) const noexcept {
        return status_[component < kFitnessComponents ? component : 0];
    }
    [[nodiscard]] bool backup_active() const noexcept { return backup_active_; }

private:
    std::array<icd::FitnessStatus, kFitnessComponents> status_{};
    bool backup_active_{false};
};

// ---- swConfigure.py ---------------------------------------------------------------------------------------

constexpr std::size_t kSwComponents = 3;  // fltControlComp, missionComputer, commsSoftware
constexpr std::size_t kDataLoads = 2;     // 20190601, 20191015

struct SwVersion {
    std::uint8_t major{0};
    std::uint8_t minor{0};
    std::uint8_t patch{0};
    bool has_patch{false};
};

class SoftwareConfig {
public:
    void init() noexcept;
    // perform_update(load_id): false for an id that is not an approved data load.
    bool perform_update(std::uint32_t load_id) noexcept;

    [[nodiscard]] const SwVersion& version(std::size_t component) const noexcept {
        return versions_[component < kSwComponents ? component : 0];
    }
    [[nodiscard]] std::uint32_t last_load() const noexcept { return last_load_; }
    [[nodiscard]] std::uint8_t loads_applied() const noexcept { return loads_applied_; }

private:
    std::array<SwVersion, kSwComponents> versions_{};
    std::uint32_t last_load_{0};
    std::uint8_t loads_applied_{0};
};

// ---- the terminal -----------------------------------------------------------------------------------------

// The key of an AVN_CMD as text.
[[nodiscard]] Key key_of(const icd::AvnCmd& cmd) noexcept;
// A key into an AVN_CMD's twelve words (for the tools and tests that build one).
void set_key(icd::AvnCmd& cmd, const char* key) noexcept;

class Avionics {
public:
    [[nodiscard]] Status init() noexcept;

    // The partition's frame: the bus health report received this frame (or null), the frame count. A report
    // with a new epoch runs the 1 Hz pass; an epoch of 0 is no report.
    void step(const icd::AvnBusHealth* report, std::uint32_t frame) noexcept;

    // The 1 Hz pass on one bus view: the LRU poll, the power-on self test the first time, the periodic tests
    // that are due, the fitness check. Public so the tools and tests can drive it directly.
    void update(const BusView& view, std::uint32_t frame) noexcept;

    // Commands, each applied only when its cmd_seq is new (ICD README section 5).
    void command_mode(const icd::AvnModeCmd& cmd) noexcept;
    void command(const icd::AvnCmd& cmd, std::uint32_t frame) noexcept;

    void reset() noexcept;
    void start_self_test() noexcept;

    [[nodiscard]] const icd::AvnStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] LruMonitor& lrus() noexcept { return lrus_; }
    [[nodiscard]] const LruMonitor& lrus() const noexcept { return lrus_; }
    [[nodiscard]] BuiltInTest& tests() noexcept { return tests_; }
    [[nodiscard]] const BuiltInTest& tests() const noexcept { return tests_; }
    [[nodiscard]] FmFitness& fitness() noexcept { return fitness_; }
    [[nodiscard]] const FmFitness& fitness() const noexcept { return fitness_; }
    [[nodiscard]] SoftwareConfig& software() noexcept { return software_; }
    [[nodiscard]] const SoftwareConfig& software() const noexcept { return software_; }
    [[nodiscard]] const BusView& bus_view() const noexcept { return view_; }

private:
    [[nodiscard]] bool view_fresh(std::uint32_t frame) const noexcept;
    void fill_status(std::uint32_t frame) noexcept;

    LruMonitor lrus_;
    BuiltInTest tests_;
    FmFitness fitness_;
    SoftwareConfig software_;
    BusView view_{};
    std::uint8_t epoch_{0};
    bool have_report_{false};
    std::uint32_t report_frame_{0};
    std::uint8_t refused_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::AvnStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::avionics

#endif
