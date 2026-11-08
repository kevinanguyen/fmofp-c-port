// The defensive systems terminal against DefensiveService: THREAT_DB by the
// fused track's class, the ESM contacts named by band and whole bearing, the
// 10 s expiry, the automatic salvo and its cooldown, the manual dispensers'
// rules (an empty flare dispenser still restarts the cooldown), the ECM modes,
// the table's order and capacity, and the partition's state.
#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <initializer_list>

#include <fmofp/defensive/defensive_systems.hpp>

namespace {

using fmofp::Status;
using fmofp::defensive::bearing_of;
using fmofp::defensive::classify_frequency;
using fmofp::defensive::DefensiveSystems;
using fmofp::defensive::kCooldownFrames;
using fmofp::defensive::kMaxContacts;
using fmofp::defensive::range_nm_of;
using fmofp::defensive::threat_entry;
using namespace fmofp::icd;  // NOLINT: test

RdrFusedTracksTrack track(std::uint16_t id, TargetClass cls, bool hostile, double x, double y, double z) {
    RdrFusedTracksTrack t{};
    t.track_id = id;
    t.classification = cls;
    t.threat = hostile ? Threat::HOSTILE : Threat::UNKNOWN;
    t.x = x;
    t.y = y;
    t.z = z;
    t.from_targeting = true;
    t.confidence = 0.8;
    return t;
}

RdrFusedTracks fused(std::initializer_list<RdrFusedTracksTrack> tracks) {
    RdrFusedTracks f{};
    f.epoch = 1;
    f.targeting_present = true;
    for (const RdrFusedTracksTrack& t : tracks) {
        f.track[f.track_count++] = t;
    }
    return f;
}

struct Sig {
    double mhz;
    double bearing;
    double range;
};

PlantEsm esm(std::uint8_t epoch, std::initializer_list<Sig> signals) {
    PlantEsm e{};
    e.epoch = epoch;
    double* f[] = {&e.frequency_1, &e.frequency_2, &e.frequency_3, &e.frequency_4, &e.frequency_5};
    double* b[] = {&e.bearing_1, &e.bearing_2, &e.bearing_3, &e.bearing_4, &e.bearing_5};
    double* r[] = {&e.range_1, &e.range_2, &e.range_3, &e.range_4, &e.range_5};
    for (const Sig& s : signals) {
        *f[e.count] = s.mhz;
        *b[e.count] = s.bearing;
        *r[e.count] = s.range;
        ++e.count;
    }
    return e;
}

DefCmd inject_cmd(std::uint8_t seq, std::uint8_t id, double bearing, double range, std::uint8_t priority,
                  RwrBand band = RwrBand::X, ThreatType type = ThreatType::SAM) {
    DefCmd c{};
    c.cmd_seq = seq;
    c.command = DefensiveCommand::INJECT_THREAT;
    c.threat_id = id;
    c.bearing = bearing;
    c.range = range;
    c.priority = priority;
    c.band = band;
    c.threat_type = type;
    return c;
}

DefCmd dispense_cmd(std::uint8_t seq, DefensiveCommand what, std::uint8_t count) {
    DefCmd c{};
    c.cmd_seq = seq;
    c.command = what;
    c.count = count;
    return c;
}

TEST(DefensiveSystemsTest, StartsAsTheServiceDidAndFollowsTheEsmFeed) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    EXPECT_EQ(TerminalState::INITIALIZING, ds.state());
    EXPECT_EQ(60U, ds.status().chaff_remaining);
    EXPECT_EQ(30U, ds.status().flares_remaining);
    EXPECT_EQ(EcmMode::STANDBY, ds.status().ecm_mode);
    EXPECT_FALSE(ds.status().jamming_active);
    EXPECT_EQ(0U, ds.status().contact_count);
    EXPECT_TRUE(ds.take_contacts_update()) << "the empty table goes out at start";
    EXPECT_FALSE(ds.take_contacts_update());
    EXPECT_EQ(0U, ds.contacts().contact_count);

    const PlantEsm e = esm(1, {});
    ds.step(nullptr, &e, 1);
    EXPECT_EQ(TerminalState::NORMAL, ds.state());
    EXPECT_TRUE(ds.status().esm_valid);
    EXPECT_FALSE(ds.status().fused_valid);
    ds.step(nullptr, nullptr, 20);
    EXPECT_EQ(TerminalState::NORMAL, ds.state()) << "three periods of 5 Hz";
    ds.step(nullptr, nullptr, 31);
    EXPECT_EQ(TerminalState::DEGRADED, ds.state()) << "the world fell silent";
    ds.step(nullptr, &e, 32);
    EXPECT_EQ(TerminalState::NORMAL, ds.state());
    EXPECT_TRUE(ds.status().healthy);
}

TEST(DefensiveSystemsTest, HostileFusedTracksBecomeContactsByThreatDb) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    const RdrFusedTracks f = fused({track(7, TargetClass::FIGHTER, true, 18520.0, 18520.0, 0.0),
                                    track(3, TargetClass::BOMBER, true, 0.0, -9260.0, 0.0),
                                    track(9, TargetClass::HIGH_ALT, true, 1000.0, 0.0, 0.0),
                                    track(4, TargetClass::FIGHTER, false, 500.0, 500.0, 0.0)});
    ds.update_rwr(&f, nullptr, 25);
    const DefRwrContacts& c = ds.contacts();
    ASSERT_EQ(3U, c.contact_count) << "get_threat_tracks(): hostile tracks only";
    EXPECT_EQ(3U, ds.status().contact_count);
    EXPECT_EQ(0U, ds.status().high_priority_count) << "no classification maps to a priority-1 entry";
    // By priority: the fighter (X/AIR/2), the bomber (S/AIR/3), the unknown entry (?/UNK/4).
    EXPECT_EQ(7U, c.contact[0].id);
    EXPECT_EQ(RwrSource::FUSION, c.contact[0].source);
    EXPECT_DOUBLE_EQ(45.0, c.contact[0].bearing);
    EXPECT_NEAR(std::sqrt(2.0) * 10.0, c.contact[0].range, 1e-9);
    EXPECT_EQ(RwrBand::X, c.contact[0].band);
    EXPECT_EQ(ThreatType::AIR, c.contact[0].threat_type);
    EXPECT_EQ(2U, c.contact[0].priority);
    EXPECT_TRUE(c.contact[0].hostile);
    EXPECT_EQ(3U, c.contact[1].id);
    EXPECT_DOUBLE_EQ(180.0, c.contact[1].bearing);
    EXPECT_DOUBLE_EQ(5.0, c.contact[1].range);
    EXPECT_EQ(RwrBand::S, c.contact[1].band);
    EXPECT_EQ(3U, c.contact[1].priority);
    EXPECT_EQ(9U, c.contact[2].id);
    EXPECT_DOUBLE_EQ(90.0, c.contact[2].bearing);
    EXPECT_EQ(RwrBand::UNKNOWN, c.contact[2].band);
    EXPECT_EQ(ThreatType::UNK, c.contact[2].threat_type);
    EXPECT_EQ(4U, c.contact[2].priority);
    EXPECT_EQ(1U, c.update);
    EXPECT_EQ(0U, c.dropped);
    // The same track next update: the contact is replaced in place, not duplicated.
    const RdrFusedTracks moved = fused({track(7, TargetClass::BOMBER, true, -18520.0, 0.0, 0.0)});
    ds.update_rwr(&moved, nullptr, 50);
    ASSERT_EQ(3U, ds.contacts().contact_count);
    const DefRwrContactsContact& moved_contact = ds.contacts().contact[0];
    EXPECT_EQ(7U, moved_contact.id);
    EXPECT_DOUBLE_EQ(270.0, moved_contact.bearing);
    EXPECT_EQ(RwrBand::S, moved_contact.band) << "THREAT_DB follows the new classification";
    EXPECT_EQ(3U, moved_contact.priority);
}

TEST(DefensiveSystemsTest, EsmSignalsAreNamedByBandAndWholeBearingAndKeepTheirFirstRange) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    const PlantEsm e = esm(1, {{9500.0, 123.7, 42.0},
                               {9600.0, 123.2, 17.0},  // X band, whole bearing 123 again: the same contact
                               {2000.0, 10.5, 30.0},   // the lower bound of S is in
                               {39999.9, 350.2, 55.0},
                               {400.0, 1.0, 20.0}});   // below L: the Python's '?'
    ds.update_rwr(nullptr, &e, 25);
    const DefRwrContacts& c = ds.contacts();
    ASSERT_EQ(4U, c.contact_count);
    EXPECT_EQ(RwrSource::ESM, c.contact[0].source);
    EXPECT_EQ(123U, c.contact[0].id);
    EXPECT_DOUBLE_EQ(123.7, c.contact[0].bearing);
    EXPECT_DOUBLE_EQ(42.0, c.contact[0].range) << "the first signal's range stays";
    EXPECT_EQ(RwrBand::X, c.contact[0].band);
    EXPECT_EQ(ThreatType::UNK, c.contact[0].threat_type);
    EXPECT_EQ(3U, c.contact[0].priority);
    EXPECT_TRUE(c.contact[0].hostile);
    EXPECT_EQ(RwrBand::S, c.contact[1].band);
    EXPECT_EQ(10U, c.contact[1].id);
    EXPECT_EQ(RwrBand::KA, c.contact[2].band);
    EXPECT_EQ(350U, c.contact[2].id);
    EXPECT_EQ(RwrBand::UNKNOWN, c.contact[3].band);
    EXPECT_EQ(1U, c.contact[3].id);
    // The same band and whole bearing in a later set refreshes the contact; a new whole bearing is a new one.
    const PlantEsm again = esm(2, {{9000.0, 123.1, 5.0}, {9000.0, 124.0, 6.0}});
    ds.update_rwr(nullptr, &again, 50);
    ASSERT_EQ(5U, ds.contacts().contact_count);
    EXPECT_DOUBLE_EQ(42.0, ds.contacts().contact[0].range);
    EXPECT_EQ(124U, ds.contacts().contact[4].id);
}

TEST(DefensiveSystemsTest, ContactsExpireTenSecondsAfterTheyWereLastSeen) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    const PlantEsm e = esm(1, {{9500.0, 100.0, 20.0}});
    const RdrFusedTracks f = fused({track(1, TargetClass::FIGHTER, true, 10000.0, 0.0, 0.0)});
    ds.update_rwr(&f, &e, 25);
    EXPECT_EQ(2U, ds.contacts().contact_count);
    ds.update_rwr(&f, nullptr, 525);
    EXPECT_EQ(2U, ds.contacts().contact_count) << "500 frames since the intercept: not yet over TRACK_TTL";
    ds.update_rwr(&f, nullptr, 550);
    ASSERT_EQ(1U, ds.contacts().contact_count) << "the intercept is gone; the track was seen again";
    EXPECT_EQ(RwrSource::FUSION, ds.contacts().contact[0].source);
    ds.update_rwr(nullptr, nullptr, 1050);
    EXPECT_EQ(1U, ds.contacts().contact_count) << "500 frames after the track was last seen";
    ds.update_rwr(nullptr, nullptr, 1075);
    EXPECT_EQ(0U, ds.contacts().contact_count);
}

TEST(DefensiveSystemsTest, AutoDispenseFiresOnAPriorityOneHostileWithACooldown) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    ds.command(inject_cmd(1, 1, 30.0, 25.0, 1), 1);
    EXPECT_EQ(CmdStatus::ACCEPTED, ds.status().defensive_cmd_status);
    EXPECT_EQ(1U, ds.status().high_priority_count);
    EXPECT_EQ(0U, ds.status().cooldown_frames) << "never dispensed: _last_dispense was the epoch";
    ds.update_rwr(nullptr, nullptr, 25);
    EXPECT_EQ(28U, ds.status().flares_remaining) << "a salvo of two";
    EXPECT_EQ(1U, ds.status().auto_salvos);
    EXPECT_EQ(2U, ds.status().flares_released);
    EXPECT_EQ(kCooldownFrames, ds.status().cooldown_frames);
    ds.update_rwr(nullptr, nullptr, 50);
    EXPECT_EQ(28U, ds.status().flares_remaining) << "cooling";
    EXPECT_EQ(125U, ds.status().cooldown_frames);
    ds.update_rwr(nullptr, nullptr, 175);
    EXPECT_EQ(28U, ds.status().flares_remaining) << "exactly the cooldown is not over it";
    ds.update_rwr(nullptr, nullptr, 176);
    EXPECT_EQ(26U, ds.status().flares_remaining);
    EXPECT_EQ(2U, ds.status().auto_salvos);
    // An empty dispenser changes nothing, not even the cooldown.
    EXPECT_EQ(26U, ds.dispense_flares(30, 400));
    EXPECT_EQ(0U, ds.status().flares_remaining);
    ds.command(inject_cmd(2, 1, 30.0, 25.0, 1), 590);  // the contact of frame 1 would have expired at 525
    ds.update_rwr(nullptr, nullptr, 600);
    EXPECT_EQ(2U, ds.status().auto_salvos);
    EXPECT_EQ(0U, ds.status().cooldown_frames) << "200 frames since the manual release";
    EXPECT_EQ(30U, ds.status().flares_released);
    EXPECT_EQ(1U, ds.contacts().high_priority_count);
}

TEST(DefensiveSystemsTest, ManualDispensingFollowsTheServicesRules) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    EXPECT_EQ(5U, ds.dispense_chaff(5));
    EXPECT_EQ(55U, ds.chaff());
    EXPECT_EQ(1U, ds.dispense_chaff(0)) << "the Python's default count";
    EXPECT_EQ(54U, ds.dispense_chaff(100)) << "as many as remain";
    EXPECT_EQ(0U, ds.dispense_chaff(1));
    EXPECT_EQ(0U, ds.chaff());

    EXPECT_EQ(3U, ds.dispense_flares(3, 10)) << "never dispensed: no cooldown";
    EXPECT_EQ(27U, ds.flares());
    EXPECT_EQ(0U, ds.dispense_flares(1, 100)) << "90 frames into the cooldown";
    EXPECT_EQ(27U, ds.flares());
    EXPECT_EQ(1U, ds.dispense_flares(1, 160)) << "150 frames is not under the cooldown";
    EXPECT_EQ(26U, ds.dispense_flares(30, 400));
    // The quirk kept: a request with nothing left releases nothing and still restarts the cooldown.
    ds.command(dispense_cmd(1, DefensiveCommand::DISPENSE_FLARES, 1), 600);
    EXPECT_EQ(CmdStatus::FAILED, ds.status().defensive_cmd_status);
    EXPECT_EQ(kCooldownFrames, ds.status().cooldown_frames);
    EXPECT_EQ(30U, ds.status().flares_released);
    ds.command(dispense_cmd(2, DefensiveCommand::DISPENSE_CHAFF, 2), 601);
    EXPECT_EQ(CmdStatus::FAILED, ds.status().defensive_cmd_status) << "no chaff left";
    EXPECT_EQ(60U, ds.status().chaff_released);
}

TEST(DefensiveSystemsTest, EcmModesAndCommandOutcomes) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    DefCmd ecm{};
    ecm.cmd_seq = 1;
    ecm.command = DefensiveCommand::SET_ECM_MODE;
    ecm.ecm_mode = EcmMode::ACTIVE;
    ds.command(ecm, 5);
    EXPECT_EQ(CmdStatus::ACCEPTED, ds.status().defensive_cmd_status);
    EXPECT_EQ(EcmMode::ACTIVE, ds.status().ecm_mode);
    EXPECT_TRUE(ds.status().jamming_active);
    ecm.cmd_seq = 2;
    ecm.ecm_mode = EcmMode::PASSIVE;
    ds.command(ecm, 6);
    EXPECT_EQ(EcmMode::PASSIVE, ds.status().ecm_mode);
    EXPECT_FALSE(ds.status().jamming_active) << "jamming only in ACTIVE";
    ecm.cmd_seq = 3;
    ecm.ecm_mode = static_cast<EcmMode>(3);
    ds.command(ecm, 7);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, ds.status().defensive_cmd_status);
    EXPECT_EQ(EcmMode::PASSIVE, ds.status().ecm_mode) << "set_ecm_mode ignored an unknown mode";

    ds.command(dispense_cmd(4, DefensiveCommand::DISPENSE_CHAFF, 3), 8);
    EXPECT_EQ(57U, ds.status().chaff_remaining);
    ds.command(dispense_cmd(4, DefensiveCommand::DISPENSE_CHAFF, 3), 9);
    EXPECT_EQ(57U, ds.status().chaff_remaining) << "the same cmd_seq is the same command";
    ds.command(inject_cmd(5, 1, 30.0, 25.0, 0), 10);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, ds.status().defensive_cmd_status) << "priority 1-4";
    EXPECT_EQ(0U, ds.status().contact_count);
    ds.command(inject_cmd(6, 2, 30.0, 25.0, 4, RwrBand::KU, ThreatType::UNK), 11);
    EXPECT_EQ(CmdStatus::ACCEPTED, ds.status().defensive_cmd_status);
    EXPECT_EQ(1U, ds.status().contact_count);
    EXPECT_EQ(0U, ds.status().high_priority_count);
    DefCmd none{};
    none.cmd_seq = 7;
    ds.command(none, 12);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, ds.status().defensive_cmd_status);
}

TEST(DefensiveSystemsTest, TheTableHoldsSixtyFourContactsAndCountsWhatItRefuses) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    for (std::size_t i = 0; i < kMaxContacts; ++i) {
        EXPECT_TRUE(ds.inject_threat(static_cast<std::uint8_t>(i), 1.0 * static_cast<double>(i), 20.0, RwrBand::X,
                                     ThreatType::SAM, 2, 1));
    }
    EXPECT_EQ(kMaxContacts, ds.contact_count());
    EXPECT_FALSE(ds.inject_threat(200, 5.0, 20.0, RwrBand::X, ThreatType::SAM, 2, 1));
    EXPECT_TRUE(ds.inject_threat(3, 9.0, 21.0, RwrBand::X, ThreatType::SAM, 2, 1)) << "an existing id is replaced";
    ds.update_rwr(nullptr, nullptr, 25);
    EXPECT_EQ(64U, ds.contacts().contact_count);
    EXPECT_EQ(1U, ds.contacts().dropped);
    EXPECT_EQ(64U, ds.status().contact_count);
}

TEST(DefensiveSystemsTest, ContactsAreSortedByPriorityThenAge) {
    DefensiveSystems ds;
    ASSERT_EQ(Status::kOk, ds.init());
    EXPECT_TRUE(ds.inject_threat(1, 10.0, 20.0, RwrBand::X, ThreatType::SAM, 3, 1));
    EXPECT_TRUE(ds.inject_threat(2, 20.0, 20.0, RwrBand::X, ThreatType::SAM, 1, 2));
    EXPECT_TRUE(ds.inject_threat(3, 30.0, 20.0, RwrBand::X, ThreatType::SAM, 3, 3));
    const RdrFusedTracks f = fused({track(9, TargetClass::FIGHTER, true, 0.0, 10000.0, 0.0)});
    ds.update_rwr(&f, nullptr, 25);
    const DefRwrContacts& c = ds.contacts();
    ASSERT_EQ(4U, c.contact_count);
    EXPECT_EQ(2U, c.contact[0].id);
    EXPECT_EQ(RwrSource::SCENARIO, c.contact[0].source);
    EXPECT_EQ(9U, c.contact[1].id);
    EXPECT_EQ(RwrSource::FUSION, c.contact[1].source);
    EXPECT_EQ(1U, c.contact[2].id) << "the older of the two priority-3 contacts first";
    EXPECT_EQ(3U, c.contact[3].id);
    EXPECT_EQ(1U, c.high_priority_count);
}

TEST(DefensiveSystemsTest, TheBandTableAndTheGeometryMatchTheService) {
    EXPECT_EQ(RwrBand::UNKNOWN, classify_frequency(0.4e9));
    EXPECT_EQ(RwrBand::L, classify_frequency(0.5e9));
    EXPECT_EQ(RwrBand::L, classify_frequency(1.9e9));
    EXPECT_EQ(RwrBand::S, classify_frequency(2e9));
    EXPECT_EQ(RwrBand::C, classify_frequency(4e9));
    EXPECT_EQ(RwrBand::X, classify_frequency(8e9));
    EXPECT_EQ(RwrBand::X, classify_frequency(11.999e9));
    EXPECT_EQ(RwrBand::KU, classify_frequency(12e9));
    EXPECT_EQ(RwrBand::K, classify_frequency(18e9));
    EXPECT_EQ(RwrBand::KA, classify_frequency(27e9));
    EXPECT_EQ(RwrBand::UNKNOWN, classify_frequency(40e9)) << "the upper bound is out";
    EXPECT_EQ(RwrBand::UNKNOWN, classify_frequency(std::nan("")));
    EXPECT_EQ(RwrBand::X, threat_entry(TargetClass::FIGHTER).band);
    EXPECT_EQ(2U, threat_entry(TargetClass::FIGHTER).priority);
    EXPECT_EQ(ThreatType::AIR, threat_entry(TargetClass::BOMBER).type);
    EXPECT_EQ(3U, threat_entry(TargetClass::BOMBER).priority);
    EXPECT_EQ(4U, threat_entry(TargetClass::STEALTH).priority) << "every other class is THREAT_DB's UNKNOWN";
    EXPECT_EQ(RwrBand::UNKNOWN, threat_entry(TargetClass::MISSILE).band);
    EXPECT_DOUBLE_EQ(45.0, bearing_of(1.0, 1.0));
    EXPECT_DOUBLE_EQ(270.0, bearing_of(-1.0, 0.0));
    EXPECT_DOUBLE_EQ(180.0, bearing_of(0.0, -1.0));
    EXPECT_DOUBLE_EQ(0.0, bearing_of(0.0, 1.0));
    EXPECT_DOUBLE_EQ(1.0, range_nm_of(1852.0, 0.0, 0.0));
    EXPECT_DOUBLE_EQ(3.0, range_nm_of(0.0, 1852.0 * 3.0, 0.0));
}

}  // namespace
