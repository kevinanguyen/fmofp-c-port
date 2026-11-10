// The avionics terminal's logic (RT 1): the LRU health monitor, the built-in
// tests, the fitness rule, the software configuration and the terminal around
// them. The Python's own behaviour is checked beside the tool in
// B20SS/fmofp_bus/tests/test_avionics_oracle.py; these are the C++ module's
// unit tests.
#include <gtest/gtest.h>

#include <cstdint>
#include <string>

#include <fmofp/avionics/avionics.hpp>

namespace {

using namespace fmofp::avionics;  // NOLINT: test
using fmofp::icd::AvionicsCommand;
using fmofp::icd::AvnBusHealth;
using fmofp::icd::AvnCmd;
using fmofp::icd::BitStatus;
using fmofp::icd::CmdStatus;
using fmofp::icd::FitnessComponent;
using fmofp::icd::FitnessStatus;
using fmofp::icd::LruHealth;
using fmofp::icd::TerminalState;

constexpr std::uint32_t bit(unsigned rt) { return std::uint32_t{1} << rt; }

// Every terminal the LRUs and the tests look at: FCS 5, FMS 12, nav 7, radar 9, engine 3, comms 2, mission 6,
// defensive 22, sensors 10.
constexpr std::uint32_t kAll = bit(5) | bit(12) | bit(7) | bit(9) | bit(3) | bit(2) | bit(6) | bit(22) | bit(10);

// A bus on which every terminal answers, healthy and NORMAL.
BusView healthy_view() {
    BusView v;
    v.valid = true;
    v.listed = v.responded = v.answering = v.status = v.healthy = v.normal = kAll;
    return v;
}

AvnBusHealth report_of(const BusView& v, std::uint8_t epoch) {
    AvnBusHealth r{};
    r.epoch = epoch;
    const auto hi = [](std::uint32_t m) { return static_cast<std::uint16_t>(m >> 16U); };
    const auto lo = [](std::uint32_t m) { return static_cast<std::uint16_t>(m & 0xFFFFU); };
    r.listed_mask_hi = hi(v.listed);
    r.listed_mask_lo = lo(v.listed);
    r.responded_mask_hi = hi(v.responded);
    r.responded_mask_lo = lo(v.responded);
    r.answering_mask_hi = hi(v.answering);
    r.answering_mask_lo = lo(v.answering);
    r.status_mask_hi = hi(v.status);
    r.status_mask_lo = lo(v.status);
    r.healthy_mask_hi = hi(v.healthy);
    r.healthy_mask_lo = lo(v.healthy);
    r.normal_mask_hi = hi(v.normal);
    r.normal_mask_lo = lo(v.normal);
    r.degraded_mask_hi = hi(v.degraded);
    r.degraded_mask_lo = lo(v.degraded);
    r.failure_mask_hi = hi(v.failure);
    r.failure_mask_lo = lo(v.failure);
    return r;
}

std::string id_of(const LruMonitor& m, std::size_t index) { return m.at(index).lru_id.data(); }

AvnCmd command(std::uint8_t seq, AvionicsCommand what, const char* key = "", LruHealth health = LruHealth::FAULT) {
    AvnCmd c{};
    c.cmd_seq = seq;
    c.command = what;
    c.health = health;
    set_key(c, key);
    return c;
}

TEST(AvionicsDeriveHealth, FollowsThePythonsOrderOfChecks) {
    SystemStatus s;
    EXPECT_EQ(LruHealth::OFFLINE, derive_health(s, false, BitStatus::PENDING)) << "an empty status";
    s.empty = false;
    EXPECT_EQ(LruHealth::NOMINAL, derive_health(s, false, BitStatus::PENDING));
    s.running = false;
    s.healthy = false;
    EXPECT_EQ(LruHealth::FAULT, derive_health(s, false, BitStatus::PENDING)) << "not running comes first";
    s.running = true;
    s.health = ReportedHealth::kFault;
    EXPECT_EQ(LruHealth::DEGRADED, derive_health(s, false, BitStatus::PENDING))
        << "unhealthy is read before the health string, so an unhealthy FAULT is DEGRADED";
    s.healthy = true;
    EXPECT_EQ(LruHealth::FAULT, derive_health(s, false, BitStatus::PENDING));
    s.health = ReportedHealth::kDegraded;
    EXPECT_EQ(LruHealth::DEGRADED, derive_health(s, false, BitStatus::PENDING));
    s.health = ReportedHealth::kNominal;
    EXPECT_EQ(LruHealth::NOMINAL, derive_health(s, true, BitStatus::FAIL)) << "a stated health outranks the BIT";
    s.health = ReportedHealth::kOther;
    EXPECT_EQ(LruHealth::DEGRADED, derive_health(s, true, BitStatus::FAIL));
    EXPECT_EQ(LruHealth::NOMINAL, derive_health(s, true, BitStatus::ABORT));
}

TEST(AvionicsLruMonitor, PollsTheCatalogueFromTheBusView) {
    LruMonitor m;
    m.init();
    ASSERT_EQ(kCatalogueCount, m.count());
    EXPECT_EQ("FCC-1", id_of(m, 0));
    EXPECT_EQ("PERF-1", id_of(m, 10));
    EXPECT_EQ(LruHealth::UNKNOWN, m.overall_health()) << "before the first poll";

    BusView v = healthy_view();
    m.poll(v);
    EXPECT_EQ(LruHealth::NOMINAL, m.overall_health());
    EXPECT_EQ(0U, m.fault_count());

    v.answering &= ~bit(7);  // navigation stops answering
    v.healthy &= ~bit(9);    // the radar computer reports itself unhealthy
    v.responded &= ~bit(22); // the defensive terminal never started
    v.status &= ~bit(2);     // comms answers, with no TERM_STATUS yet
    m.poll(v);
    EXPECT_EQ(LruHealth::FAULT, m.at(2).health) << "NAV-1";
    EXPECT_EQ(LruHealth::DEGRADED, m.at(3).health) << "RDR-1";
    EXPECT_EQ(LruHealth::OFFLINE, m.at(7).health) << "DFS-1";
    EXPECT_EQ(LruHealth::OFFLINE, m.at(5).health) << "COMMS-1";
    EXPECT_EQ(LruHealth::FAULT, m.overall_health());
    EXPECT_EQ(2U, m.fault_count()) << "FAULT and DEGRADED count; OFFLINE does not";

    // The three LRUs of the flight control terminal move together.
    v = healthy_view();
    v.normal &= ~bit(5);
    v.failure |= bit(5);
    m.poll(v);
    EXPECT_EQ(LruHealth::FAULT, m.at(0).health);
    EXPECT_EQ(LruHealth::FAULT, m.at(9).health);
    EXPECT_EQ(LruHealth::FAULT, m.at(10).health);
    EXPECT_EQ(3U, m.fault_count());

    v.valid = false;
    m.poll(v);
    EXPECT_EQ(LruHealth::UNKNOWN, m.overall_health()) << "no view: nothing can be said";
}

TEST(AvionicsLruMonitor, ResolvesAKeyAsThePythonDid) {
    LruMonitor m;
    m.init();
    EXPECT_EQ(0U, m.resolve("fcc-1"));
    EXPECT_EQ(0U, m.resolve("  FLIGHT_CONTROL_COMPUTER "));
    EXPECT_EQ(1U, m.resolve("flightmanagementsystem"));
    EXPECT_EQ(9U, m.resolve("collision")) << "a part of exactly one name";
    EXPECT_EQ(kMaxLrus, m.resolve("service")) << "a part of five names";
    EXPECT_EQ(kMaxLrus, m.resolve("hydraulic_system_a"));
    EXPECT_EQ(kMaxLrus, m.resolve(""));
    EXPECT_EQ(kMaxLrus, m.resolve(nullptr));
}

TEST(AvionicsLruMonitor, AForcedFaultOutlastsThePollAndClearsToUnknown) {
    LruMonitor m;
    m.init();
    const BusView v = healthy_view();
    m.poll(v);
    EXPECT_EQ(0U, m.force_fault("flight_control_computer", LruHealth::FAULT));
    EXPECT_EQ(LruHealth::FAULT, m.at(0).health) << "at once";
    m.poll(v);
    EXPECT_EQ(LruHealth::FAULT, m.at(0).health) << "the poll does not overwrite it";
    EXPECT_EQ(1U, m.forced_count());
    EXPECT_EQ(LruHealth::FAULT, m.overall_health());

    EXPECT_EQ(1U, m.clear_forced_fault("flight control"));
    EXPECT_EQ(LruHealth::UNKNOWN, m.at(0).health) << "until the next poll";
    m.poll(v);
    EXPECT_EQ(LruHealth::NOMINAL, m.at(0).health);
    EXPECT_EQ(0U, m.clear_forced_fault("flight control")) << "nothing forced any more";
}

TEST(AvionicsLruMonitor, AKeyThatNamesNoLruDeclaresOne) {
    LruMonitor m;
    m.init();
    const std::size_t index = m.force_fault("engine_vibration", LruHealth::DEGRADED);
    ASSERT_EQ(kCatalogueCount, index);
    EXPECT_EQ("ENGINE_VIBRATION", id_of(m, index));
    EXPECT_STREQ("engine_vibration (scenario-declared)", m.at(index).name.data());
    EXPECT_TRUE(m.at(index).declared);
    EXPECT_EQ(12U, m.count());
    m.poll(healthy_view());
    EXPECT_EQ(LruHealth::DEGRADED, m.at(index).health) << "the poll leaves it alone";
    EXPECT_EQ(index, m.force_fault("ENGINE_VIBRATION", LruHealth::FAULT)) << "the same entry, by its id";
    EXPECT_EQ(12U, m.count());

    // Four declared slots; the fifth key is refused.
    EXPECT_EQ(12U, m.force_fault("fuel_transfer", LruHealth::FAULT));
    EXPECT_EQ(13U, m.force_fault("hydraulic_system_a", LruHealth::FAULT));
    EXPECT_EQ(14U, m.force_fault("", LruHealth::FAULT));
    EXPECT_EQ("UNKNOWN", id_of(m, 14)) << "an empty key";
    EXPECT_EQ(kMaxLrus, m.force_fault("one_too_many", LruHealth::FAULT));
    EXPECT_EQ(4U, m.forced_count());

    // Clearing a declared entry removes it; the ones behind it move up.
    EXPECT_EQ(1U, m.clear_forced_fault("fuel_transfer"));
    EXPECT_EQ(14U, m.count());
    EXPECT_EQ("HYDRAULIC_SYSTEM_A", id_of(m, 12));
    // An empty key is a part of every name: it clears the oldest forced fault (the Python's `needle in name`).
    EXPECT_EQ(1U, m.clear_forced_fault(""));
    EXPECT_EQ("HYDRAULIC_SYSTEM_A", id_of(m, 11)) << "ENGINE_VIBRATION, the first one set, is gone";
    EXPECT_EQ(2U, m.clear_forced_fault(nullptr));
    EXPECT_EQ(kCatalogueCount, m.count());
    EXPECT_EQ(0U, m.forced_count());
}

TEST(AvionicsLruMonitor, ABitResultOnlyMattersWhenNothingElseSpeaks) {
    LruMonitor m;
    m.init();
    EXPECT_TRUE(m.update_bit_result("NAV-1", BitStatus::FAIL));
    EXPECT_FALSE(m.update_bit_result("NO-SUCH", BitStatus::FAIL));
    BusView v = healthy_view();
    m.poll(v);
    EXPECT_EQ(LruHealth::NOMINAL, m.at(2).health) << "the terminal says NORMAL";
    v.normal &= ~bit(7);  // a state that is none of NORMAL, DEGRADED, FAILURE (STANDBY, say)
    m.poll(v);
    EXPECT_EQ(LruHealth::DEGRADED, m.at(2).health);
}

TEST(AvionicsBuiltInTest, ProbesAnswerFromTheBusView) {
    BusView v = healthy_view();
    EXPECT_EQ(BitStatus::PASS, probe_system(BitSystem::kFlightControlComputer, v));
    v.answering &= ~bit(5);
    EXPECT_EQ(BitStatus::FAIL, probe_system(BitSystem::kFlightControlComputer, v));
    EXPECT_EQ(BitStatus::PASS, probe_system(BitSystem::kSatcom, v));
    v.valid = false;
    EXPECT_EQ(BitStatus::ABORT, probe_system(BitSystem::kSatcom, v));
    EXPECT_EQ(BitStatus::PASS, probe_system(BitSystem::kWeaponSystem, v)) << "no terminal behind it: always PASS";
}

TEST(AvionicsBuiltInTest, PowerOnPeriodicAndInitiated) {
    BuiltInTest t;
    t.init();
    BusView v = healthy_view();
    v.answering &= ~bit(7);  // navigation is silent
    EXPECT_FALSE(t.post_complete());
    t.run_post(v);
    EXPECT_TRUE(t.post_complete());
    EXPECT_EQ(BitStatus::PASS, t.post_results()[0]);
    EXPECT_EQ(BitStatus::FAIL, t.post_results()[3]);
    EXPECT_EQ(BitStatus::FAIL, t.post_results()[5]);

    // A clock near zero: nothing is due until an interval has passed since "never" (0).
    EXPECT_EQ(0U, t.run_due(1000.0, v));
    EXPECT_EQ(3U, t.run_due(3600.0, v)) << "BIT-COMM, 60 minutes";
    EXPECT_EQ(0U, t.stored(0));
    EXPECT_EQ(3U, t.stored(1));
    EXPECT_EQ(2U, t.run_due(5400.0, v)) << "BIT-AVIONICS, 90 minutes";
    EXPECT_EQ(2U, t.stored(0));
    // Both due in one call: BIT-COMM stores BIT-AVIONICS's two results as well as its own three.
    EXPECT_EQ(5U, t.run_due(5400.0 + 5400.0, v));
    EXPECT_EQ(4U, t.stored(0));
    EXPECT_EQ(8U, t.stored(1));
    EXPECT_EQ(BitStatus::PASS, t.periodic_results()[4]);

    const InitiatedSummary all = t.run_all(v);
    EXPECT_EQ(11U, all.passed);
    EXPECT_EQ(4U, all.failed) << "POST-NAV's three components and IFT-FLT-NAV's navigation side";
    EXPECT_EQ(0U, all.aborted);
    EXPECT_EQ(BitStatus::FAIL, all.results[12]) << "IFT-FLT-NAV, navigationSystem";
    EXPECT_EQ(1U, t.initiated_runs());
    EXPECT_EQ(8U, t.stored(1)) << "an initiated run stores nothing under the periodic tests";
}

TEST(AvionicsFmFitness, EqualityNotAThreshold) {
    EXPECT_EQ(FitnessStatus::OK, FmFitness::check_thresholds(75, 80)) << "the placeholder metrics";
    EXPECT_EQ(FitnessStatus::WARNING, FmFitness::check_thresholds(80, 0));
    EXPECT_EQ(FitnessStatus::WARNING, FmFitness::check_thresholds(0, 75));
    EXPECT_EQ(FitnessStatus::CRITICAL, FmFitness::check_thresholds(90, 75));
    EXPECT_EQ(FitnessStatus::OK, FmFitness::check_thresholds(99, 99)) << "above every threshold reads OK";
    FmFitness f;
    f.init();
    f.step();
    EXPECT_EQ(FitnessStatus::OK, f.status(0));
    EXPECT_FALSE(f.handle_redundancy(FitnessComponent::NAVIGATION_FITNESS));
    EXPECT_FALSE(f.backup_active());
    EXPECT_TRUE(f.handle_redundancy(FitnessComponent::FLIGHT_CONTROL_FITNESS));
    EXPECT_TRUE(f.backup_active());
}

TEST(AvionicsSoftwareConfig, ADataLoadSetsTheFirstComponentOfItsSpecs) {
    SoftwareConfig s;
    s.init();
    EXPECT_EQ(5U, s.version(0).major);
    EXPECT_TRUE(s.version(0).has_patch);
    EXPECT_FALSE(s.perform_update(20200101));
    EXPECT_EQ(0U, s.loads_applied());
    EXPECT_TRUE(s.perform_update(20190601));
    EXPECT_FALSE(s.version(0).has_patch) << "5.2";
    EXPECT_EQ(8U, s.version(1).minor) << "missionComputer 3.8, untouched";
    EXPECT_TRUE(s.perform_update(20191015));
    EXPECT_EQ(1U, s.version(0).patch);
    EXPECT_EQ(20191015U, s.last_load());
    EXPECT_EQ(2U, s.loads_applied());
}

TEST(AvionicsKey, RoundTripsThroughTheCommandWords) {
    AvnCmd c{};
    set_key(c, "flight_control_computer");
    EXPECT_EQ(0x666CU, c.key_0) << "'f' high, 'l' low";
    EXPECT_STREQ("flight_control_computer", key_of(c).data());
    set_key(c, "exactly_twenty_four_char_and_more");
    EXPECT_STREQ("exactly_twenty_four_char", key_of(c).data());
    set_key(c, "");
    EXPECT_STREQ("", key_of(c).data());
}

TEST(AvionicsTerminal, RunsTheOneHertzPassOncePerReport) {
    Avionics a;
    ASSERT_EQ(fmofp::Status::kOk, a.init());
    EXPECT_EQ(TerminalState::INITIALIZING, a.state());
    a.step(nullptr, 1);
    EXPECT_EQ(TerminalState::INITIALIZING, a.state());
    EXPECT_FALSE(a.status().bus_health_valid);
    EXPECT_EQ(LruHealth::UNKNOWN, a.status().overall_health);

    AvnBusHealth empty{};
    a.step(&empty, 2);
    EXPECT_FALSE(a.status().bus_health_valid) << "epoch 0 is no report";

    const AvnBusHealth report = report_of(healthy_view(), 1);
    a.step(&report, 3);
    EXPECT_EQ(TerminalState::NORMAL, a.state());
    EXPECT_TRUE(a.status().bus_health_valid);
    EXPECT_TRUE(a.status().post_complete);
    EXPECT_EQ(BitStatus::PASS, a.status().post_fcc_cpu);
    EXPECT_EQ(BitStatus::PASS, a.status().post_nav_gps_receiver);
    EXPECT_EQ(LruHealth::NOMINAL, a.status().overall_health);
    EXPECT_EQ(11U, a.status().lru_count);
    EXPECT_EQ(BitStatus::PASS, a.status().pbit_radios) << "the first pass finds every periodic test due";
    EXPECT_EQ(2U, a.status().pbit_avionics_stored);
    EXPECT_EQ(5U, a.status().pbit_comm_stored);
    EXPECT_EQ(FitnessStatus::OK, a.status().fitness_avionics);
    EXPECT_EQ(5U, a.status().sw_flight_control_major);
    EXPECT_TRUE(a.status().sw_flight_control_has_patch);

    // The same epoch again is the same report: no second pass.
    a.step(&report, 4);
    EXPECT_EQ(5U, a.status().pbit_comm_stored);
    // The power-on test is not run again by a later report, whatever it says.
    BusView worse = healthy_view();
    worse.answering &= ~bit(5);
    const AvnBusHealth second = report_of(worse, 2);
    a.step(&second, 53);
    EXPECT_EQ(BitStatus::PASS, a.status().post_fcc_cpu);
    EXPECT_EQ(LruHealth::FAULT, a.status().overall_health);
    EXPECT_EQ(3U, a.status().fault_count) << "FCC-1, GCAS-1, PERF-1";
    EXPECT_EQ(0x0601U, a.status().lru_fault_mask) << "slots 0, 9 and 10";

    // No report for three periods: DEGRADED, and nothing is known of the LRUs.
    a.step(nullptr, 53 + kBusHealthStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, a.state());
    EXPECT_FALSE(a.status().bus_health_valid);
    EXPECT_EQ(LruHealth::UNKNOWN, a.status().overall_health);
    const AvnBusHealth third = report_of(healthy_view(), 3);
    a.step(&third, 400);
    EXPECT_EQ(TerminalState::NORMAL, a.state());
    EXPECT_EQ(LruHealth::NOMINAL, a.status().overall_health);
}

TEST(AvionicsTerminal, CommandsAreAppliedOncePerSequence) {
    Avionics a;
    ASSERT_EQ(fmofp::Status::kOk, a.init());
    const AvnBusHealth report = report_of(healthy_view(), 1);
    a.step(&report, 1);

    a.command(command(1, AvionicsCommand::FORCE_FAULT, "flight_control_computer"), 2);
    EXPECT_EQ(CmdStatus::ACCEPTED, a.status().avionics_cmd_status);
    EXPECT_EQ(1U, a.status().forced_count);
    EXPECT_EQ(0x0001U, a.status().lru_forced_mask);
    EXPECT_EQ(0x0001U, a.status().lru_fault_mask);
    EXPECT_EQ(LruHealth::FAULT, a.status().overall_health);

    a.command(command(2, AvionicsCommand::FORCE_FAULT, "engine_vibration", LruHealth::DEGRADED), 3);
    EXPECT_EQ(12U, a.status().lru_count);
    EXPECT_EQ(0x0800U, a.status().lru_degraded_mask) << "slot 11, the first declared entry";
    a.command(command(2, AvionicsCommand::CLEAR_ALL_FAULTS), 4);
    EXPECT_EQ(2U, a.status().forced_count) << "a repeated sequence number is not a new command";

    a.command(command(3, AvionicsCommand::CLEAR_FAULT, "no_such_system"), 5);
    EXPECT_EQ(CmdStatus::FAILED, a.status().avionics_cmd_status);
    a.command(command(4, AvionicsCommand::CLEAR_FAULT, "engine_vibration"), 6);
    EXPECT_EQ(CmdStatus::ACCEPTED, a.status().avionics_cmd_status);
    EXPECT_EQ(11U, a.status().lru_count);
    a.command(command(5, AvionicsCommand::CLEAR_ALL_FAULTS), 7);
    EXPECT_EQ(0U, a.status().forced_count);
    EXPECT_EQ(LruHealth::UNKNOWN, a.status().overall_health) << "FCC-1 is UNKNOWN until the next report";

    a.command(command(6, AvionicsCommand::RUN_INITIATED_BIT), 8);
    EXPECT_EQ(1U, a.status().ibit_runs);
    EXPECT_EQ(15U, a.status().ibit_pass);

    AvnCmd load = command(7, AvionicsCommand::APPLY_DATA_LOAD);
    load.data_load = 20190601.0;
    a.command(load, 9);
    EXPECT_EQ(CmdStatus::ACCEPTED, a.status().avionics_cmd_status);
    EXPECT_FALSE(a.status().sw_flight_control_has_patch);
    EXPECT_DOUBLE_EQ(20190601.0, a.status().last_data_load);
    load.cmd_seq = 8;
    load.data_load = 12345.0;
    a.command(load, 10);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, a.status().avionics_cmd_status);
    EXPECT_EQ(1U, a.status().data_loads_applied);

    AvnCmd redundancy = command(9, AvionicsCommand::HANDLE_REDUNDANCY);
    redundancy.component = FitnessComponent::FLIGHT_CONTROL_FITNESS;
    a.command(redundancy, 11);
    EXPECT_TRUE(a.status().backup_active);
    a.command(command(10, AvionicsCommand::NONE), 12);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, a.status().avionics_cmd_status);

    // The fifth key that names no LRU is refused and counted.
    std::uint8_t seq = 11;
    for (const char* key : {"a_one", "a_two", "a_three", "a_four", "a_five"}) {
        a.command(command(seq, AvionicsCommand::FORCE_FAULT, key), 13);
        ++seq;
    }
    EXPECT_EQ(CmdStatus::FAILED, a.status().avionics_cmd_status);
    EXPECT_EQ(1U, a.status().refused_count);
    EXPECT_EQ(15U, a.status().lru_count);
}

TEST(AvionicsTerminal, ModeCommandsAndTheStatusOnTheWire) {
    Avionics a;
    ASSERT_EQ(fmofp::Status::kOk, a.init());
    const AvnBusHealth report = report_of(healthy_view(), 1);
    a.step(&report, 1);
    fmofp::icd::AvnModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::FAILURE;
    a.command_mode(mode);
    EXPECT_TRUE(a.status().cmd_rejected);
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::MAINTENANCE;
    a.command_mode(mode);
    EXPECT_FALSE(a.status().cmd_rejected);
    EXPECT_EQ(TerminalState::MAINTENANCE, a.state());
    EXPECT_EQ(2U, a.status().last_cmd_seq);

    a.start_self_test();
    EXPECT_TRUE(a.bit().in_progress);
    a.step(nullptr, 2);
    a.step(nullptr, 2 + kSelfTestFrames);
    EXPECT_FALSE(a.bit().in_progress);

    fmofp::icd::AvnStatus::Words words{};
    ASSERT_EQ(fmofp::Status::kOk, a.status().encode(words));
    fmofp::icd::AvnStatus back{};
    ASSERT_EQ(fmofp::Status::kOk, fmofp::icd::AvnStatus::decode(words, back));
    EXPECT_EQ(LruHealth::NOMINAL, back.overall_health);
    EXPECT_EQ(BitStatus::PASS, back.post_nav_sensors);
    EXPECT_EQ(8U, back.sw_mission_minor);

    a.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, a.state());
    EXPECT_FALSE(a.status().post_complete);
}

}  // namespace
