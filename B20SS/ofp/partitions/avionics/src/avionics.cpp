#include <fmofp/avionics/avionics.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::avionics {

using icd::BitStatus;
using icd::FitnessStatus;
using icd::LruHealth;
using icd::TerminalState;

namespace {

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

// ---- text: the LRU ids, system keys and names are fixed-size, zero-terminated ASCII -------------------------

char to_lower(char c) noexcept { return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c; }
char to_upper(char c) noexcept { return (c >= 'a' && c <= 'z') ? static_cast<char>(c - 'a' + 'A') : c; }

template <std::size_t N>
std::size_t length(const std::array<char, N>& text) noexcept {
    std::size_t n = 0;
    while (n + 1 < N && text[n] != '\0') {
        ++n;
    }
    return n;
}

// Copies `text` (null reads as empty) into `out`, cut to what fits; the number of characters copied.
template <std::size_t N>
std::size_t assign(std::array<char, N>& out, const char* text, std::size_t at = 0) noexcept {
    std::size_t n = at;
    if (text != nullptr) {
        for (std::size_t i = 0; n + 1 < N && text[i] != '\0'; ++i) {
            out[n] = text[i];
            ++n;
        }
    }
    std::fill(out.begin() + static_cast<std::ptrdiff_t>(n), out.end(), '\0');
    return n - at;
}

// str.strip(): without the white space at either end.
Key stripped(const char* key) noexcept {
    Key out{};
    if (key == nullptr) {
        return out;
    }
    std::size_t start = 0;
    while (start < kKeyChars && key[start] != '\0' && key[start] <= ' ') {
        ++start;
    }
    std::size_t n = assign(out, key + start);
    while (n > 0 && out[n - 1] <= ' ') {
        --n;
        out[n] = '\0';
    }
    return out;
}

template <std::size_t N>
void transform(std::array<char, N>& text, char (*f)(char) noexcept) noexcept {
    std::transform(text.begin(), text.end(), text.begin(), f);
}

// needle == text.lower(), the needle already lower case.
template <std::size_t N>
bool equals_lower(const std::array<char, N>& text, const Key& needle) noexcept {
    const std::size_t n = length(text);
    if (n != length(needle)) {
        return false;
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (to_lower(text[i]) != needle[i]) {
            return false;
        }
    }
    return true;
}

// needle in text.lower(), the needle already lower case (an empty needle is in every text).
template <std::size_t N>
bool contains_lower(const std::array<char, N>& text, const Key& needle) noexcept {
    const std::size_t n = length(text);
    const std::size_t m = length(needle);
    for (std::size_t start = 0; start + m <= n; ++start) {
        std::size_t i = 0;
        while (i < m && to_lower(text[start + i]) == needle[i]) {
            ++i;
        }
        if (i == m) {
            return true;
        }
    }
    return false;
}

Key lowered(const char* key) noexcept {
    Key needle = stripped(key);
    transform(needle, to_lower);
    return needle;
}

// ---- the tables of the Python's configuration ---------------------------------------------------------------

struct CatalogueEntry {
    const char* lru_id;
    const char* name;
    const char* system_key;
    std::uint8_t rt;  // the terminal that carries the system on the bus (ICD terminal table)
};

// _build_catalogue(), in its order. The ground collision avoidance and the performance monitor are parts of
// the flight control terminal.
constexpr std::array<CatalogueEntry, kCatalogueCount> kCatalogue = {{
    {"FCC-1", "Flight Control Computer", "flight_control_computer", icd::FcsStatus::kRt},
    {"FMS-1", "Flight Management System", "flightManagementSystem", icd::FmsStatus::kRt},
    {"NAV-1", "Navigation Service", "nav_service", icd::NavSolution::kRt},
    {"RDR-1", "Radar Management", "radar_management", icd::RdrWxStatus::kRt},
    {"ECU-1", "Engine Control Unit", "engine_control_unit", icd::EngStatus::kRt},
    {"COMMS-1", "Communications Service", "comms_service", icd::ComStatus::kRt},
    {"MSN-1", "Mission Planning Service", "mission_service", icd::MsnStatus::kRt},
    {"DFS-1", "Defensive Systems Service", "defensive_service", icd::DefStatus::kRt},
    {"SNS-1", "Sensor Service", "sensor_service", icd::SnsStatus::kRt},
    {"GCAS-1", "Ground Collision Avoidance", "gcas", icd::FcsStatus::kRt},
    {"PERF-1", "Performance Monitor", "performance_monitor", icd::FcsStatus::kRt},
}};

constexpr char kDeclaredSuffix[] = " (scenario-declared)";

// bitsConfig.xml: the self tests probe one system once per component.
constexpr std::array<BitSystem, kPostResults> kPostProbes = {
    BitSystem::kFlightControlComputer, BitSystem::kFlightControlComputer, BitSystem::kFlightControlComputer,
    BitSystem::kNavigationSystem,      BitSystem::kNavigationSystem,      BitSystem::kNavigationSystem};

struct PeriodicTest {
    std::size_t first;      // its first probe in kPeriodicProbes
    std::size_t count;
    double interval_s;      // <interval> is minutes
};

constexpr std::array<BitSystem, kPeriodicResults> kPeriodicProbes = {
    BitSystem::kFlightControlComputer, BitSystem::kMissionComputer,  // BIT-AVIONICS
    BitSystem::kDatalink, BitSystem::kSatcom, BitSystem::kRadios};   // BIT-COMM
constexpr std::array<PeriodicTest, kPeriodicTests> kPeriodic = {{{0, 2, 90.0 * 60.0}, {2, 3, 60.0 * 60.0}}};

// IFT-FLT-NAV and IFT-WPN-FCR: both sides of each interface.
constexpr std::array<BitSystem, 4> kInterfaceProbes = {BitSystem::kFlightControlComputer, BitSystem::kNavigationSystem,
                                                       BitSystem::kWeaponSystem, BitSystem::kFireControlRadar};

// fmfConfig.xml.
constexpr int kWarningCpu = 80;
constexpr int kWarningMemory = 75;
constexpr int kCriticalCpu = 90;
constexpr int kCriticalMemory = 90;

// swcmConfig.xml as SoftwareConfigManager parsed it: of each load's <loadSpecs> only the first component and
// version were read (README section 2), and both loads' first is fltControlComp.
struct DataLoad {
    std::uint32_t id{0};
    std::size_t component{0};
    SwVersion version{};
};

constexpr std::array<SwVersion, kSwComponents> kInitialVersions = {{{5, 2, 1, true}, {3, 8, 0, false}, {2, 5, 0, false}}};
constexpr std::array<DataLoad, kDataLoads> kLoads = {{{20190601U, 0, {5, 2, 0, false}}, {20191015U, 0, {5, 2, 1, true}}}};

std::uint8_t terminal_of(BitSystem system) noexcept {
    switch (system) {
        case BitSystem::kFlightControlComputer:
            return icd::FcsStatus::kRt;
        case BitSystem::kNavigationSystem:
            return icd::NavSolution::kRt;
        case BitSystem::kMissionComputer:
            return icd::MsnStatus::kRt;
        case BitSystem::kDatalink:
        case BitSystem::kSatcom:
        case BitSystem::kRadios:
            return icd::ComStatus::kRt;
        case BitSystem::kWeaponSystem:
        case BitSystem::kFireControlRadar:
        default:
            return kNoTerminal;
    }
}

bool bit_of(std::uint32_t mask, std::uint8_t rt) noexcept { return rt < 32U && ((mask >> rt) & 1U) != 0U; }

std::uint32_t joined(std::uint16_t high, std::uint16_t low) noexcept {
    return (static_cast<std::uint32_t>(high) << 16U) | low;
}

std::uint8_t saturated(std::size_t value, std::size_t max) noexcept {
    return static_cast<std::uint8_t>(std::min(value, max));
}

void count_result(BitStatus result, InitiatedSummary& summary) noexcept {
    if (result == BitStatus::PASS) {
        ++summary.passed;
    } else if (result == BitStatus::FAIL) {
        ++summary.failed;
    } else {
        ++summary.aborted;
    }
}

// The LRU's status as the Python's poll would have read it from the subsystem.
LruHealth polled_health(const Lru& lru, const BusView& view) noexcept {
    if (!view.valid) {
        return LruHealth::UNKNOWN;  // the poll that raised
    }
    if (!view.started(lru.rt)) {
        return LruHealth::OFFLINE;  // "system not started"
    }
    SystemStatus status;
    const bool has_status = bit_of(view.status, lru.rt);
    status.running = view.running(lru.rt);
    status.empty = status.running && !has_status;  // answering, and nothing to read yet
    status.healthy = !has_status || bit_of(view.healthy, lru.rt);
    if (bit_of(view.failure, lru.rt)) {
        status.health = ReportedHealth::kFault;
    } else if (bit_of(view.degraded, lru.rt)) {
        status.health = ReportedHealth::kDegraded;
    } else if (bit_of(view.normal, lru.rt)) {
        status.health = ReportedHealth::kNominal;
    } else {
        status.health = ReportedHealth::kOther;
    }
    return derive_health(status, lru.has_bit_result, lru.bit_result);
}

}  // namespace

// ---- the bus view -------------------------------------------------------------------------------------------

bool BusView::running(std::uint8_t rt) const noexcept { return bit_of(responded, rt) && bit_of(answering, rt); }
bool BusView::started(std::uint8_t rt) const noexcept { return bit_of(listed, rt) && bit_of(responded, rt); }

BusView view_of(const icd::AvnBusHealth& report) noexcept {
    BusView view;
    view.valid = report.epoch != 0U;
    view.listed = joined(report.listed_mask_hi, report.listed_mask_lo);
    view.responded = joined(report.responded_mask_hi, report.responded_mask_lo);
    view.answering = joined(report.answering_mask_hi, report.answering_mask_lo);
    view.status = joined(report.status_mask_hi, report.status_mask_lo);
    view.healthy = joined(report.healthy_mask_hi, report.healthy_mask_lo);
    view.bit_failed = joined(report.bit_failed_mask_hi, report.bit_failed_mask_lo);
    view.normal = joined(report.normal_mask_hi, report.normal_mask_lo);
    view.degraded = joined(report.degraded_mask_hi, report.degraded_mask_lo);
    view.failure = joined(report.failure_mask_hi, report.failure_mask_lo);
    return view;
}

// ---- LRUstatus.py -------------------------------------------------------------------------------------------

LruHealth derive_health(const SystemStatus& status, bool has_bit_result, BitStatus bit_result) noexcept {
    if (status.empty) {
        return LruHealth::OFFLINE;
    }
    if (!status.running) {
        return LruHealth::FAULT;
    }
    if (!status.healthy) {
        return LruHealth::DEGRADED;  // before the health string: an unhealthy FAULT reads DEGRADED
    }
    if (status.health == ReportedHealth::kFault) {
        return LruHealth::FAULT;
    }
    if (status.health == ReportedHealth::kDegraded) {
        return LruHealth::DEGRADED;
    }
    if (status.health == ReportedHealth::kNominal) {
        return LruHealth::NOMINAL;
    }
    if (has_bit_result && bit_result == BitStatus::FAIL) {
        return LruHealth::DEGRADED;
    }
    return LruHealth::NOMINAL;
}

void LruMonitor::init() noexcept {
    lrus_.fill(Lru{});
    count_ = 0;
    next_order_ = 1;
    for (const CatalogueEntry& entry : kCatalogue) {
        Lru& lru = lrus_[count_];
        (void)assign(lru.lru_id, entry.lru_id);
        (void)assign(lru.name, entry.name);
        (void)assign(lru.system_key, entry.system_key);
        lru.rt = entry.rt;
        ++count_;
    }
}

void LruMonitor::poll(const BusView& view) noexcept {
    for (std::size_t i = 0; i < count_; ++i) {
        Lru& lru = lrus_[i];
        if (lru.rt == kNoTerminal) {
            continue;  // no accessor: the poll leaves a scenario-declared entry alone
        }
        lru.health = lru.forced ? lru.forced_state : polled_health(lru, view);
    }
}

std::size_t LruMonitor::resolve(const char* key) const noexcept {
    const Key needle = lowered(key);
    if (needle[0] == '\0') {
        return kMaxLrus;
    }
    const auto end = lrus_.begin() + static_cast<std::ptrdiff_t>(count_);
    const auto exact = std::find_if(lrus_.begin(), end, [&needle](const Lru& unit) {
        return equals_lower(unit.lru_id, needle) || equals_lower(unit.system_key, needle);
    });
    if (exact != end) {
        return static_cast<std::size_t>(exact - lrus_.begin());
    }
    // A part of exactly one name.
    std::size_t hit = kMaxLrus;
    std::size_t hits = 0;
    for (std::size_t i = 0; i < count_; ++i) {
        if (contains_lower(lrus_[i].name, needle)) {
            hit = i;
            ++hits;
        }
    }
    return hits == 1 ? hit : kMaxLrus;
}

std::size_t LruMonitor::find_id(const char* lru_id) const noexcept {
    Key wanted{};
    (void)assign(wanted, lru_id);
    const auto end = lrus_.begin() + static_cast<std::ptrdiff_t>(count_);
    const auto found = std::find_if(lrus_.begin(), end, [&wanted](const Lru& unit) { return unit.lru_id == wanted; });
    return found == end ? kMaxLrus : static_cast<std::size_t>(found - lrus_.begin());
}

std::size_t LruMonitor::force_fault(const char* key, LruHealth state) noexcept {
    std::size_t index = resolve(key);
    if (index == kMaxLrus) {
        // A key that names no LRU declares one, so a scenario's "engine_vibration" still shows as a fault.
        Key id = stripped(key);
        transform(id, to_upper);
        if (id[0] == '\0') {
            (void)assign(id, "UNKNOWN");
        }
        index = find_id(id.data());
        if (index == kMaxLrus) {
            if (count_ >= kMaxLrus) {
                return kMaxLrus;
            }
            index = count_;
            Lru& made = lrus_[index];
            made = Lru{};
            made.lru_id = id;
            const std::size_t n = assign(made.name, key);
            (void)assign(made.name, kDeclaredSuffix, n);
            (void)assign(made.system_key, key);
            made.declared = true;
            ++count_;
        }
    }
    Lru& lru = lrus_[index];
    if (!lru.forced) {
        lru.forced_order = next_order_;
        ++next_order_;
    }
    lru.forced = true;
    lru.forced_state = state;
    lru.health = state;  // at once, not at the next poll
    return index;
}

void LruMonitor::remove(std::size_t index) noexcept {
    for (std::size_t i = index; i + 1 < count_; ++i) {
        lrus_[i] = lrus_[i + 1];
    }
    --count_;
    lrus_[count_] = Lru{};
}

void LruMonitor::clear_one(std::size_t index) noexcept {
    Lru& lru = lrus_[index];
    lru.forced = false;
    if (lru.declared) {
        remove(index);  // a declared entry goes with its fault
    } else {
        lru.health = LruHealth::UNKNOWN;  // until the next poll derives it again
    }
}

std::size_t LruMonitor::clear_forced_fault(const char* key) noexcept {
    if (key == nullptr) {
        std::size_t cleared = 0;
        for (std::size_t i = count_; i > 0; --i) {
            if (lrus_[i - 1].forced) {
                clear_one(i - 1);
                ++cleared;
            }
        }
        return cleared;
    }
    // The first forced fault, in the order they were set, whose id, system key or name matches.
    const Key needle = lowered(key);
    std::size_t match = kMaxLrus;
    for (std::size_t i = 0; i < count_; ++i) {
        const Lru& lru = lrus_[i];
        if (!lru.forced || (match != kMaxLrus && lru.forced_order > lrus_[match].forced_order)) {
            continue;
        }
        if (equals_lower(lru.lru_id, needle) || equals_lower(lru.system_key, needle) ||
            contains_lower(lru.name, needle)) {
            match = i;
        }
    }
    if (match == kMaxLrus) {
        return 0;
    }
    clear_one(match);
    return 1;
}

bool LruMonitor::update_bit_result(const char* lru_id, BitStatus result) noexcept {
    const std::size_t index = find_id(lru_id);
    if (index == kMaxLrus) {
        return false;
    }
    lrus_[index].has_bit_result = true;
    lrus_[index].bit_result = result;
    return true;
}

LruHealth LruMonitor::overall_health() const noexcept {
    const auto any = [this](LruHealth wanted) {
        return std::any_of(lrus_.begin(), lrus_.begin() + static_cast<std::ptrdiff_t>(count_),
                           [wanted](const Lru& lru) { return lru.health == wanted; });
    };
    if (any(LruHealth::FAULT)) {
        return LruHealth::FAULT;
    }
    if (any(LruHealth::DEGRADED) || any(LruHealth::OFFLINE)) {
        return LruHealth::DEGRADED;
    }
    if (any(LruHealth::UNKNOWN)) {
        return LruHealth::UNKNOWN;
    }
    return LruHealth::NOMINAL;
}

std::size_t LruMonitor::fault_count() const noexcept {
    return static_cast<std::size_t>(
        std::count_if(lrus_.begin(), lrus_.begin() + static_cast<std::ptrdiff_t>(count_), [](const Lru& lru) {
            return lru.health == LruHealth::FAULT || lru.health == LruHealth::DEGRADED;
        }));
}

std::size_t LruMonitor::forced_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(lrus_.begin(), lrus_.begin() + static_cast<std::ptrdiff_t>(count_),
                                                  [](const Lru& lru) { return lru.forced; }));
}

// ---- builtInTesting.py and bitControl.py --------------------------------------------------------------------

BitStatus probe_system(BitSystem system, const BusView& view) noexcept {
    const std::uint8_t rt = terminal_of(system);
    if (rt == kNoTerminal) {
        return BitStatus::PASS;  // the Python's simulated probe, without its one-in-a-hundred fault
    }
    if (!view.valid) {
        return BitStatus::ABORT;
    }
    return view.running(rt) ? BitStatus::PASS : BitStatus::FAIL;
}

void BuiltInTest::init() noexcept {
    post_.fill(BitStatus::PENDING);
    post_complete_ = false;
    periodic_.fill(BitStatus::PENDING);
    last_run_.fill(0.0);  // self._last_run.get(test_id, 0)
    stored_.fill(0);
    initiated_ = InitiatedSummary{};
    initiated_.results.fill(BitStatus::PENDING);
    initiated_runs_ = 0;
}

void BuiltInTest::run_post(const BusView& view) noexcept {
    for (std::size_t i = 0; i < kPostResults; ++i) {
        post_[i] = probe_system(kPostProbes[i], view);
    }
    post_complete_ = true;
}

std::size_t BuiltInTest::run_due(double now_s, const BusView& view) noexcept {
    std::size_t new_results = 0;
    for (std::size_t t = 0; t < kPeriodicTests; ++t) {
        const PeriodicTest& test = kPeriodic[t];
        if (now_s - last_run_[t] < test.interval_s) {
            continue;
        }
        for (std::size_t i = 0; i < test.count; ++i) {
            periodic_[test.first + i] = probe_system(kPeriodicProbes[test.first + i], view);
            ++new_results;
        }
        // extend(new_results): everything this call has produced so far, the earlier tests' results included.
        stored_[t] += static_cast<std::uint32_t>(new_results);
        last_run_[t] = now_s;
    }
    return new_results;
}

InitiatedSummary BuiltInTest::run_all(const BusView& view) noexcept {
    InitiatedSummary summary;
    std::size_t n = 0;
    const auto run = [&summary, &n, &view](BitSystem system) {
        const BitStatus result = probe_system(system, view);
        summary.results[n] = result;
        ++n;
        count_result(result, summary);
    };
    std::for_each(kPostProbes.begin(), kPostProbes.end(), run);
    std::for_each(kPeriodicProbes.begin(), kPeriodicProbes.end(), run);  // whatever their intervals
    std::for_each(kInterfaceProbes.begin(), kInterfaceProbes.end(), run);
    initiated_ = summary;
    if (initiated_runs_ < 15U) {
        ++initiated_runs_;
    }
    return summary;
}

// ---- fmStatus.py --------------------------------------------------------------------------------------------

void FmFitness::init() noexcept {
    status_.fill(FitnessStatus::OK);
    backup_active_ = false;
}

FitnessStatus FmFitness::check_thresholds(int cpu, int memory) noexcept {
    // Equality, as the Python wrote it: a reading above a threshold is OK (README section 2).
    if (cpu == kCriticalCpu || memory == kCriticalMemory) {
        return FitnessStatus::CRITICAL;
    }
    if (cpu == kWarningCpu || memory == kWarningMemory) {
        return FitnessStatus::WARNING;
    }
    return FitnessStatus::OK;
}

void FmFitness::step() noexcept { status_.fill(check_thresholds(kFitnessCpu, kFitnessMemory)); }

bool FmFitness::handle_redundancy(icd::FitnessComponent component) noexcept {
    if (component != icd::FitnessComponent::FLIGHT_CONTROL_FITNESS) {
        return false;
    }
    backup_active_ = true;  // "Activating backup aviationBackupComputer"
    return true;
}

// ---- swConfigure.py -----------------------------------------------------------------------------------------

void SoftwareConfig::init() noexcept {
    versions_ = kInitialVersions;
    last_load_ = 0;
    loads_applied_ = 0;
}

bool SoftwareConfig::perform_update(std::uint32_t load_id) noexcept {
    const auto load =
        std::find_if(kLoads.begin(), kLoads.end(), [load_id](const DataLoad& l) { return l.id == load_id; });
    if (load == kLoads.end()) {
        return false;
    }
    versions_[load->component] = load->version;
    last_load_ = load_id;
    if (loads_applied_ < 255U) {
        ++loads_applied_;
    }
    return true;
}

// ---- the terminal -------------------------------------------------------------------------------------------

Key key_of(const icd::AvnCmd& cmd) noexcept {
    const std::array<std::uint16_t, kKeyChars / 2> words = {cmd.key_0, cmd.key_1, cmd.key_2, cmd.key_3,
                                                            cmd.key_4, cmd.key_5, cmd.key_6, cmd.key_7,
                                                            cmd.key_8, cmd.key_9, cmd.key_10, cmd.key_11};
    Key key{};
    std::size_t n = 0;
    for (const std::uint16_t word : words) {
        for (const unsigned code : {static_cast<unsigned>(word >> 8U), static_cast<unsigned>(word & 0xFFU)}) {
            if (code == 0U) {
                return key;
            }
            key[n] = (code >= 0x20U && code <= 0x7EU) ? static_cast<char>(code) : '?';
            ++n;
        }
    }
    return key;
}

void set_key(icd::AvnCmd& cmd, const char* key) noexcept {
    Key text{};
    (void)assign(text, key);
    std::array<std::uint16_t, kKeyChars / 2> words{};
    for (std::size_t i = 0; i < words.size(); ++i) {
        const unsigned first = static_cast<unsigned char>(text[2 * i]);
        const unsigned second = static_cast<unsigned char>(text[2 * i + 1]);
        words[i] = static_cast<std::uint16_t>((first << 8U) | second);
    }
    cmd.key_0 = words[0];
    cmd.key_1 = words[1];
    cmd.key_2 = words[2];
    cmd.key_3 = words[3];
    cmd.key_4 = words[4];
    cmd.key_5 = words[5];
    cmd.key_6 = words[6];
    cmd.key_7 = words[7];
    cmd.key_8 = words[8];
    cmd.key_9 = words[9];
    cmd.key_10 = words[10];
    cmd.key_11 = words[11];
}

Status Avionics::init() noexcept {
    lrus_.init();
    tests_.init();
    fitness_.init();
    software_.init();
    view_ = BusView{};
    epoch_ = 0;
    have_report_ = false;
    report_frame_ = 0;
    refused_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::AvnStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_status(0);
    return Status::kOk;
}

void Avionics::reset() noexcept { (void)init(); }

void Avionics::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

bool Avionics::view_fresh(std::uint32_t frame) const noexcept {
    return have_report_ && frame >= report_frame_ && frame - report_frame_ < kBusHealthStaleFrames;
}

void Avionics::step(const icd::AvnBusHealth* report, std::uint32_t frame) noexcept {
    if (report != nullptr && report->epoch != 0U) {
        const bool new_report = !have_report_ || report->epoch != epoch_;
        epoch_ = report->epoch;
        have_report_ = true;
        report_frame_ = frame;
        if (new_report) {
            update(view_of(*report), frame);  // the 1 Hz body, once per report
        }
    }
    const bool fresh = view_fresh(frame);
    if (!fresh && view_.valid) {
        // The controller has gone quiet: nothing can be said of the LRUs any more.
        view_.valid = false;
        lrus_.poll(view_);
    }

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    if (status_.state == TerminalState::INITIALIZING && fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status(frame);
}

void Avionics::update(const BusView& view, std::uint32_t frame) noexcept {
    view_ = view;
    have_report_ = true;
    report_frame_ = frame;
    lrus_.poll(view_);
    if (!tests_.post_complete()) {
        tests_.run_post(view_);  // power on: the first picture of the bus
    }
    (void)tests_.run_due(kClockOriginS + static_cast<double>(frame) * kFrameS, view_);
    fitness_.step();
    fill_status(frame);
}

void Avionics::command_mode(const icd::AvnModeCmd& cmd) noexcept {
    if (!mode_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    status_.last_cmd_seq = cmd.cmd_seq;
    if (!commandable(cmd.requested_state)) {
        status_.cmd_rejected = true;
        return;
    }
    status_.cmd_rejected = false;
    status_.state = cmd.requested_state;
    status_.mode_transition = false;
}

void Avionics::command(const icd::AvnCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    cmd_status_ = icd::CmdStatus::ACCEPTED;
    const Key key = key_of(cmd);
    switch (cmd.command) {
        case icd::AvionicsCommand::RUN_INITIATED_BIT:
            (void)tests_.run_all(view_);
            break;
        case icd::AvionicsCommand::FORCE_FAULT:
            if (lrus_.force_fault(key.data(), cmd.health) == kMaxLrus) {
                cmd_status_ = icd::CmdStatus::FAILED;  // no declared slot left
                if (refused_ < 255U) {
                    ++refused_;
                }
            }
            break;
        case icd::AvionicsCommand::CLEAR_FAULT:
            if (lrus_.clear_forced_fault(key.data()) == 0) {
                cmd_status_ = icd::CmdStatus::FAILED;  // no forced fault by that name
            }
            break;
        case icd::AvionicsCommand::CLEAR_ALL_FAULTS:
            (void)lrus_.clear_forced_fault(nullptr);
            break;
        case icd::AvionicsCommand::APPLY_DATA_LOAD:
            if (!(cmd.data_load >= 0.0 && cmd.data_load <= 99999999.0) ||
                !software_.perform_update(static_cast<std::uint32_t>(std::llround(cmd.data_load)))) {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;  // "Invalid data load ID"
            }
            break;
        case icd::AvionicsCommand::HANDLE_REDUNDANCY:
            (void)fitness_.handle_redundancy(cmd.component);  // nothing happens for a component without a backup
            break;
        case icd::AvionicsCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status(frame);
}

void Avionics::fill_status(std::uint32_t frame) noexcept {
    status_.overall_health = lrus_.overall_health();
    status_.avionics_cmd_status = cmd_status_;
    status_.bus_health_valid = view_fresh(frame);
    status_.post_complete = tests_.post_complete();
    status_.backup_active = fitness_.backup_active();
    status_.healthy = !bit_.failed;
    status_.lru_count = saturated(lrus_.count(), 255);
    status_.fault_count = saturated(lrus_.fault_count(), 255);
    status_.forced_count = saturated(lrus_.forced_count(), 255);
    status_.refused_count = refused_;

    const std::array<BitStatus, kPostResults>& post = tests_.post_results();
    status_.post_fcc_cpu = post[0];
    status_.post_fcc_memory = post[1];
    status_.post_fcc_databus = post[2];
    status_.post_nav_cpu = post[3];
    status_.post_nav_sensors = post[4];
    status_.post_nav_gps_receiver = post[5];
    const std::array<BitStatus, kPeriodicResults>& periodic = tests_.periodic_results();
    status_.pbit_flight_control = periodic[0];
    status_.pbit_mission = periodic[1];
    status_.pbit_datalink = periodic[2];
    status_.pbit_satcom = periodic[3];
    status_.pbit_radios = periodic[4];
    status_.pbit_avionics_stored = saturated(tests_.stored(0), 255);
    status_.pbit_comm_stored = saturated(tests_.stored(1), 255);
    status_.ibit_runs = tests_.initiated_runs();
    status_.ibit_pass = tests_.last_initiated().passed;
    status_.ibit_fail = tests_.last_initiated().failed;
    status_.ibit_abort = tests_.last_initiated().aborted;

    status_.fitness_flight_control = fitness_.status(0);
    status_.fitness_navigation = fitness_.status(1);
    status_.fitness_avionics = fitness_.status(2);

    const SwVersion& fcc = software_.version(0);
    status_.sw_flight_control_major = fcc.major;
    status_.sw_flight_control_minor = fcc.minor;
    status_.sw_flight_control_patch = fcc.patch;
    status_.sw_flight_control_has_patch = fcc.has_patch;
    const SwVersion& mission = software_.version(1);
    status_.sw_mission_major = mission.major;
    status_.sw_mission_minor = mission.minor;
    status_.sw_mission_patch = mission.patch;
    status_.sw_mission_has_patch = mission.has_patch;
    const SwVersion& comms = software_.version(2);
    status_.sw_comms_major = comms.major;
    status_.sw_comms_minor = comms.minor;
    status_.sw_comms_patch = comms.patch;
    status_.sw_comms_has_patch = comms.has_patch;
    status_.last_data_load = static_cast<double>(software_.last_load());
    status_.data_loads_applied = software_.loads_applied();

    std::uint16_t fault_mask = 0;
    std::uint16_t degraded_mask = 0;
    std::uint16_t forced_mask = 0;
    for (std::size_t i = 0; i < lrus_.count(); ++i) {
        const Lru& lru = lrus_.at(i);
        const std::uint16_t slot = static_cast<std::uint16_t>(1U << i);
        if (lru.health == LruHealth::FAULT) {
            fault_mask = static_cast<std::uint16_t>(fault_mask | slot);
        } else if (lru.health == LruHealth::DEGRADED) {
            degraded_mask = static_cast<std::uint16_t>(degraded_mask | slot);
        } else {
            // NOMINAL, OFFLINE and UNKNOWN set neither.
        }
        if (lru.forced) {
            forced_mask = static_cast<std::uint16_t>(forced_mask | slot);
        }
    }
    status_.lru_fault_mask = fault_mask;
    status_.lru_degraded_mask = degraded_mask;
    status_.lru_forced_mask = forced_mask;
}

}  // namespace fmofp::avionics
