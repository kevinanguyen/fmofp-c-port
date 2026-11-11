// The sensor management terminal against SensorService and SensorDataFusion:
// the health rule over the six sensors, the detections normalised into
// contacts, the 5 degree bearing gate (merge, corroboration, FUSED, the
// kinematics filled in), the LIDAR points that never merge, the 8 s expiry in
// table order, the id counter, the capacity, the commands and the state.
#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <initializer_list>

#include <fmofp/sensor/sensor_management.hpp>

namespace {

using fmofp::Status;
using fmofp::sensor::bearing_delta;
using fmofp::sensor::classify_band;
using fmofp::sensor::Contact;
using fmofp::sensor::ContactClass;
using fmofp::sensor::kMaxContacts;
using fmofp::sensor::SensorManagement;
using fmofp::sensor::Source;
using fmofp::sensor::source_bit;
using namespace fmofp::icd;  // NOLINT: test

struct Radar {
    SensorId sensor;
    double distance;
    double angle;
    double speed;
};
struct Lidar {
    double distance;
    double azimuth;
    double elevation;
};
struct Ir {
    SensorId sensor;
    double angle;
    double distance;
};

PlantSensorScan scan(std::uint8_t epoch, std::initializer_list<Radar> radars, std::initializer_list<Lidar> points = {},
                     std::initializer_list<Ir> objects = {}) {
    PlantSensorScan s{};
    s.epoch = epoch;
    for (const Radar& r : radars) {
        PlantSensorScanRadar& out = s.radar[s.radar_count++];
        out.sensor = r.sensor;
        out.distance = r.distance;
        out.angle = r.angle;
        out.speed = r.speed;
    }
    for (const Lidar& p : points) {
        PlantSensorScanLidar& out = s.lidar[s.lidar_count++];
        out.distance = p.distance;
        out.azimuth = p.azimuth;
        out.elevation = p.elevation;
    }
    for (const Ir& o : objects) {
        PlantSensorScanInfrared& out = s.infrared[s.infrared_count++];
        out.sensor = o.sensor;
        out.temperature = 300.0;
        out.angle = o.angle;
        out.distance = o.distance;
    }
    return s;
}

PlantEsm esm(std::uint8_t epoch, double mhz, double bearing) {
    PlantEsm e{};
    e.epoch = epoch;
    e.count = 1;
    e.frequency_1 = mhz;
    e.strength_1 = -60.0;
    e.bearing_1 = bearing;
    e.range_1 = 20.0;
    return e;
}

SnsCmd cmd(std::uint8_t seq, SensorCommand command, SensorId sensor) {
    SnsCmd c{};
    c.cmd_seq = seq;
    c.command = command;
    c.sensor = sensor;
    return c;
}

TEST(SensorManagementTest, StartsWithEverySensorOnAndFollowsTheScanFeed) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    EXPECT_EQ(TerminalState::INITIALIZING, sm.state());
    EXPECT_EQ(SensorHealth::INITIALISING, sm.status().health) << "no update yet";
    EXPECT_TRUE(sm.status().main_radar_active && sm.status().tfr_radar_active && sm.status().lidar_active &&
                sm.status().flir_active && sm.status().maws_active && sm.status().esm_active)
        << "SensorService.start: activate_all";
    EXPECT_EQ(0U, sm.status().contact_count);
    const PlantSensorScan s = scan(1, {});
    sm.step(&s, nullptr, 10);
    EXPECT_EQ(TerminalState::NORMAL, sm.state());
    EXPECT_EQ(SensorHealth::NOMINAL, sm.status().health);
    EXPECT_TRUE(sm.status().scan_valid);
    EXPECT_FALSE(sm.status().esm_valid);
    sm.step(nullptr, nullptr, 39);
    EXPECT_EQ(TerminalState::NORMAL, sm.state()) << "three periods of the 5 Hz set";
    sm.step(nullptr, nullptr, 40);
    EXPECT_EQ(TerminalState::DEGRADED, sm.state()) << "the world fell silent";
    sm.step(&s, nullptr, 41);
    EXPECT_EQ(TerminalState::NORMAL, sm.state());
}

TEST(SensorManagementTest, TheHealthRuleOverTheTwoSuites) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    sm.update(nullptr, nullptr, 10);
    EXPECT_EQ(SensorHealth::NOMINAL, sm.status().health);
    EXPECT_TRUE(sm.set_active(SensorId::LIDAR, false));
    EXPECT_EQ(SensorHealth::DEGRADED, sm.status().health) << "the passive suite is whole";
    EXPECT_TRUE(sm.set_active(SensorId::FLIR, false));
    EXPECT_EQ(SensorHealth::FAULT, sm.status().health) << "neither suite is whole";
    EXPECT_TRUE(sm.set_active(SensorId::LIDAR, true));
    EXPECT_EQ(SensorHealth::DEGRADED, sm.status().health);
    EXPECT_TRUE(sm.set_active(SensorId::FLIR, true));
    EXPECT_EQ(SensorHealth::NOMINAL, sm.status().health);
    EXPECT_FALSE(sm.set_active(static_cast<SensorId>(6), false)) << "no seventh sensor";
    EXPECT_FALSE(sm.status().lidar_active == false);
}

TEST(SensorManagementTest, RadarDetectionsBecomeContactsAndMergeWithinTheBearingGate) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    const PlantSensorScan s = scan(1, {{SensorId::MAIN_RADAR, 120000.0, 10.0, 250.0},
                                       {SensorId::MAIN_RADAR, 80000.0, 13.0, 100.0},   // within 5 degrees of the first
                                       {SensorId::TFR_RADAR, 20000.0, 200.0, 50.0}});
    sm.update(&s, nullptr, 10);
    ASSERT_EQ(2U, sm.contact_count());
    EXPECT_EQ(3U, sm.sequence()) << "every detection takes a number, merged or not";
    const Contact& first = sm.contact(0);
    EXPECT_EQ((1U), first.id);
    EXPECT_EQ(Source::RADAR, first.origin);
    EXPECT_EQ(Source::RADAR, first.source) << "one source corroborating itself is not FUSED";
    EXPECT_EQ(ContactClass::UNKNOWN, first.contact_class) << "a radar detection has no elevation";
    EXPECT_DOUBLE_EQ(120000.0, first.range_m) << "the first reading's range stays";
    EXPECT_DOUBLE_EQ(10.0, first.bearing_deg);
    EXPECT_DOUBLE_EQ(250.0, first.speed_ms);
    EXPECT_FALSE(first.has_elevation);
    EXPECT_FALSE(first.has_frequency);
    EXPECT_NEAR(1.0, first.confidence, 1e-12) << "0.95 + 0.1 capped at 1";
    EXPECT_EQ(source_bit(Source::RADAR), first.corroborated);
    EXPECT_EQ(10U, first.last_seen);
    const Contact& second = sm.contact(1);
    EXPECT_EQ(3U, second.id);
    EXPECT_DOUBLE_EQ(0.99, second.confidence);
    EXPECT_DOUBLE_EQ(200.0, second.bearing_deg);
    // An ESM signal within the gate of the second contact corroborates it (one source so far: not FUSED) and
    // fills in its frequency, strength and band.
    const PlantEsm e = esm(1, 9500.0, 203.5);
    sm.update(nullptr, &e, 20);
    ASSERT_EQ(2U, sm.contact_count());
    const Contact& seen_by_esm = sm.contact(1);
    EXPECT_EQ(Source::RADAR, seen_by_esm.source) << "corroborated_by is ['ESM']: one name is not two";
    EXPECT_EQ(source_bit(Source::ESM), seen_by_esm.corroborated);
    EXPECT_TRUE(seen_by_esm.has_frequency);
    EXPECT_DOUBLE_EQ(9.5e9, seen_by_esm.frequency_hz);
    EXPECT_EQ(RwrBand::X, seen_by_esm.band);
    EXPECT_DOUBLE_EQ(-60.0, seen_by_esm.signal_dbm);
    EXPECT_EQ(20U, seen_by_esm.last_seen);
    EXPECT_NEAR(1.0, seen_by_esm.confidence, 1e-12) << "0.99 + 0.1 capped at 1";
    EXPECT_EQ(4U, sm.sequence());
    // The radar sees it again: a second name in corroborated_by, so FUSED, with the id's prefix unchanged.
    const PlantSensorScan again = scan(2, {{SensorId::TFR_RADAR, 21000.0, 201.0, 55.0}});
    sm.update(&again, nullptr, 30);
    ASSERT_EQ(2U, sm.contact_count());
    const Contact& fused = sm.contact(1);
    EXPECT_EQ(Source::FUSED, fused.source);
    EXPECT_EQ(Source::RADAR, fused.origin) << "the id keeps its prefix";
    EXPECT_EQ(static_cast<std::uint8_t>(source_bit(Source::RADAR) | source_bit(Source::ESM)), fused.corroborated);
    EXPECT_DOUBLE_EQ(20000.0, fused.range_m) << "a range already there is not replaced";
    EXPECT_EQ(30U, fused.last_seen);
    EXPECT_EQ(5U, sm.sequence());
}

TEST(SensorManagementTest, LidarPointsNeverMergeAndInfraredBearingsAreRelative) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    const PlantSensorScan s = scan(1, {{SensorId::MAIN_RADAR, 50000.0, 330.0, 300.0}},
                                   {{500.0, 330.0, 5.0}, {600.0, 331.0, 1.0}},
                                   {{SensorId::FLIR, -30.0, 4000.0}, {SensorId::MAWS, 120.0, 8000.0}});
    sm.update(&s, nullptr, 10);
    ASSERT_EQ(4U, sm.contact_count());
    // The radar contact first; the FLIR object at -30 degrees is 330 the other way round and merges into it
    // (corroborated by IR alone: one name, not yet FUSED).
    const Contact& radar = sm.contact(0);
    EXPECT_EQ(Source::RADAR, radar.source);
    EXPECT_EQ(source_bit(Source::IR), radar.corroborated);
    EXPECT_NEAR(1.0, radar.confidence, 1e-12);
    EXPECT_DOUBLE_EQ(50000.0, radar.range_m) << "the FLIR's distance does not replace a range already there";
    // Both LIDAR points are their own contacts: no bearing, so no gate either way.
    const Contact& air = sm.contact(1);
    EXPECT_EQ(Source::LIDAR, air.source);
    EXPECT_FALSE(air.has_bearing);
    EXPECT_EQ(ContactClass::AIR, air.contact_class);
    EXPECT_TRUE(air.has_elevation);
    EXPECT_DOUBLE_EQ(5.0, air.elevation_deg);
    EXPECT_TRUE(air.has_speed) << "det.get('speed', 0.0)";
    EXPECT_DOUBLE_EQ(0.0, air.speed_ms);
    EXPECT_DOUBLE_EQ(0.99, air.confidence);
    const Contact& ground = sm.contact(2);
    EXPECT_EQ(ContactClass::GROUND, ground.contact_class) << "1 degree of elevation is not above 2";
    // The MAWS object at 120 degrees is a contact of its own.
    const Contact& ir = sm.contact(3);
    EXPECT_EQ(Source::IR, ir.source);
    EXPECT_EQ(ContactClass::AIR, ir.contact_class);
    EXPECT_DOUBLE_EQ(120.0, ir.bearing_deg);
    EXPECT_DOUBLE_EQ(8000.0, ir.range_m);
    EXPECT_FALSE(ir.has_speed);
    EXPECT_DOUBLE_EQ(0.6, ir.confidence);
    EXPECT_EQ(5U, sm.sequence());
}

TEST(SensorManagementTest, ContactsExpireEightSecondsAfterTheyWereLastSeenInTableOrder) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    const PlantSensorScan first = scan(1, {{SensorId::MAIN_RADAR, 1000.0, 10.0, 1.0}}, {{100.0, 0.0, 0.0}});
    sm.update(&first, nullptr, 10);
    const PlantSensorScan second = scan(2, {{SensorId::MAIN_RADAR, 1000.0, 100.0, 1.0}});
    sm.update(&second, nullptr, 20);
    ASSERT_EQ(3U, sm.contact_count());
    const PlantSensorScan refresh = scan(3, {{SensorId::MAIN_RADAR, 1000.0, 11.0, 1.0}});  // the first contact again
    sm.update(&refresh, nullptr, 410);
    EXPECT_EQ(3U, sm.contact_count()) << "400 frames since the LIDAR point: not over the TTL";
    sm.update(nullptr, nullptr, 420);
    ASSERT_EQ(2U, sm.contact_count()) << "the LIDAR point of frame 10 is gone";
    EXPECT_EQ(Source::RADAR, sm.contact(0).origin);
    EXPECT_EQ(1U, sm.contact(0).id);
    EXPECT_EQ(410U, sm.contact(0).last_seen);
    EXPECT_EQ(3U, sm.contact(1).id) << "the contact of frame 20 keeps its place behind the first";
    sm.update(nullptr, nullptr, 430);
    EXPECT_EQ(1U, sm.contact_count()) << "frame 20's contact, 410 frames old";
    EXPECT_EQ(1U, sm.contact(0).id);
}

TEST(SensorManagementTest, ASensorSwitchedOffContributesNothing) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    EXPECT_TRUE(sm.set_active(SensorId::TFR_RADAR, false));
    EXPECT_TRUE(sm.set_active(SensorId::ESM, false));
    const PlantSensorScan s = scan(1, {{SensorId::MAIN_RADAR, 1000.0, 10.0, 1.0}, {SensorId::TFR_RADAR, 1000.0, 100.0, 1.0}},
                                   {}, {{SensorId::MAWS, 200.0, 5000.0}});
    const PlantEsm e = esm(1, 3000.0, 300.0);
    sm.update(&s, &e, 10);
    ASSERT_EQ(2U, sm.contact_count());
    EXPECT_EQ(Source::RADAR, sm.contact(0).origin);
    EXPECT_DOUBLE_EQ(10.0, sm.contact(0).bearing_deg);
    EXPECT_EQ(Source::IR, sm.contact(1).origin);
    EXPECT_EQ(2U, sm.sequence()) << "a skipped detection takes no number";
    EXPECT_EQ(SensorHealth::FAULT, sm.status().health);
}

TEST(SensorManagementTest, TheTableHoldsItsCapacityAndCountsWhatItRefuses) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    // LIDAR points never merge: five per set, forty sets fill the table.
    PlantSensorScan s = scan(1, {}, {{1.0, 0.0, 5.0}, {2.0, 0.0, 5.0}, {3.0, 0.0, 5.0}, {4.0, 0.0, 5.0}, {5.0, 0.0, 5.0}});
    for (std::uint32_t n = 1; n <= 40; ++n) {
        s.epoch = static_cast<std::uint8_t>(n);
        sm.update(&s, nullptr, 10 * n);
    }
    EXPECT_EQ(kMaxContacts, sm.contact_count());
    EXPECT_EQ(8U, sm.dropped());
    EXPECT_EQ(192U, sm.status().contact_count);
    EXPECT_EQ(200U, sm.sequence());
}

TEST(SensorManagementTest, CommandsAndTheirOutcomes) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    sm.command(cmd(1, SensorCommand::DEACTIVATE, SensorId::MAWS), 5);
    EXPECT_EQ(CmdStatus::ACCEPTED, sm.status().sensor_cmd_status);
    EXPECT_FALSE(sm.status().maws_active);
    EXPECT_FALSE(sm.active(SensorId::MAWS));
    sm.command(cmd(1, SensorCommand::ACTIVATE, SensorId::MAWS), 6);
    EXPECT_FALSE(sm.status().maws_active) << "the same cmd_seq is the same command";
    sm.command(cmd(2, SensorCommand::ACTIVATE, SensorId::MAWS), 7);
    EXPECT_TRUE(sm.status().maws_active);
    sm.command(cmd(3, SensorCommand::NONE, SensorId::MAWS), 8);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, sm.status().sensor_cmd_status);
    sm.command(cmd(4, SensorCommand::DEACTIVATE, static_cast<SensorId>(7)), 9);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, sm.status().sensor_cmd_status) << "no such sensor";
    SnsModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::STANDBY;
    sm.command_mode(mode);
    EXPECT_EQ(TerminalState::STANDBY, sm.state());
    EXPECT_FALSE(sm.status().cmd_rejected);
}

TEST(SensorManagementTest, TheGateAndTheBandTableMatchTheFusion) {
    EXPECT_DOUBLE_EQ(360.0, bearing_delta(false, 0.0, true, 10.0)) << "a missing bearing never gates";
    EXPECT_DOUBLE_EQ(3.0, bearing_delta(true, 10.0, true, 13.0));
    EXPECT_DOUBLE_EQ(0.0, bearing_delta(true, -30.0, true, 330.0));
    EXPECT_DOUBLE_EQ(2.0, bearing_delta(true, 359.0, true, 1.0));
    EXPECT_DOUBLE_EQ(180.0, bearing_delta(true, 0.0, true, 180.0));
    EXPECT_EQ(RwrBand::L, classify_band(0.5e9));
    EXPECT_EQ(RwrBand::S, classify_band(2e9));
    EXPECT_EQ(RwrBand::KA, classify_band(39.9e9));
    EXPECT_EQ(RwrBand::UNKNOWN, classify_band(40e9));
    EXPECT_EQ(RwrBand::UNKNOWN, classify_band(std::nan("")));
}

// The ESM intercepts and the terminal's own housekeeping (added with unit 30's coverage floor): a set of five
// signals becomes five contacts, each of the plant's five slots read; the self test; a mode command that may
// not be asked for; the names the tool prints.
TEST(SensorManagementTest, AnEsmSetOfFiveTheSelfTestAndTheModeCommand) {
    SensorManagement sm;
    ASSERT_EQ(Status::kOk, sm.init());
    PlantEsm esm{};
    esm.epoch = 1;
    esm.count = 5;
    esm.frequency_1 = 1.0e9;
    esm.bearing_1 = 10.0;
    esm.frequency_2 = 3.0e9;
    esm.bearing_2 = 60.0;
    esm.frequency_3 = 9.0e9;
    esm.bearing_3 = 120.0;
    esm.frequency_4 = 15.0e9;
    esm.bearing_4 = 200.0;
    esm.frequency_5 = 35.0e9;
    esm.bearing_5 = 300.0;
    sm.step(nullptr, &esm, 10);
    EXPECT_TRUE(sm.status().esm_valid);
    EXPECT_EQ(5U, sm.status().contact_count) << "five bearings more than the gate apart: five contacts";
    sm.step(nullptr, &esm, 20);
    EXPECT_EQ(5U, sm.status().contact_count) << "the same epoch is the same set";

    sm.start_self_test();
    EXPECT_TRUE(sm.bit().in_progress);
    sm.step(nullptr, nullptr, 21);
    EXPECT_TRUE(sm.bit().in_progress);
    sm.step(nullptr, nullptr, 21 + fmofp::sensor::kSelfTestFrames);
    EXPECT_FALSE(sm.bit().in_progress);

    SnsModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::FAILURE;
    sm.command_mode(mode);
    EXPECT_TRUE(sm.status().cmd_rejected);
    mode.requested_state = TerminalState::STANDBY;  // the same sequence number: not a new command
    sm.command_mode(mode);
    EXPECT_NE(TerminalState::STANDBY, sm.state());

    EXPECT_STREQ("ESM", fmofp::sensor::to_string(Source::ESM));
    EXPECT_STREQ("RADAR", fmofp::sensor::to_string(Source::RADAR));
    EXPECT_STREQ("LIDAR", fmofp::sensor::to_string(Source::LIDAR));
    EXPECT_STREQ("IR", fmofp::sensor::to_string(Source::IR));
    EXPECT_STREQ("FUSED", fmofp::sensor::to_string(Source::FUSED));
    EXPECT_STREQ("EMITTER", fmofp::sensor::to_string(ContactClass::EMITTER));
    EXPECT_STREQ("AIR", fmofp::sensor::to_string(ContactClass::AIR));
    EXPECT_STREQ("GROUND", fmofp::sensor::to_string(ContactClass::GROUND));
    EXPECT_STREQ("SURFACE", fmofp::sensor::to_string(ContactClass::SURFACE));
    EXPECT_STREQ("UNKNOWN", fmofp::sensor::to_string(ContactClass::UNKNOWN));

    sm.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, sm.state());
    EXPECT_EQ(0U, sm.status().contact_count);
}

}  // namespace
