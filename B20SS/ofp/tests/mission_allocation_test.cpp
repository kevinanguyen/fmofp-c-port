// Unit 37: the radars following the mission phase, and the mission briefing.
#include <cstring>
#include <string>

#include <fmofp/mission/mission_computer.hpp>
#include <fmofp/radar/aewc_radar.hpp>
#include <fmofp/radar/mission_allocation.hpp>
#include <fmofp/radar/sar_radar.hpp>
#include <fmofp/radar/targeting_radar.hpp>
#include <fmofp/radar/terrain_following.hpp>
#include <fmofp/radar/weather_radar.hpp>
#include <gtest/gtest.h>

namespace {

namespace icd = fmofp::icd;
namespace radar = fmofp::radar;
namespace mission = fmofp::mission;
using fmofp::Status;
using icd::CmdStatus;
using icd::MissionPhase;
using icd::TerminalState;
using radar::RadarConfiguration;

icd::MsnStatus status_in(MissionPhase phase, TerminalState state = TerminalState::NORMAL) {
    icd::MsnStatus s{};
    s.state = state;
    s.phase = phase;
    return s;
}

TEST(MissionAllocation, ThePhasesMapOntoThePythonsThreeConfigurations) {
    EXPECT_EQ(RadarConfiguration::kNone, radar::configuration_for(MissionPhase::PLANNING));
    EXPECT_EQ(RadarConfiguration::kEnRoute, radar::configuration_for(MissionPhase::INGRESS));
    EXPECT_EQ(RadarConfiguration::kEnRoute, radar::configuration_for(MissionPhase::OBJECTIVE));
    EXPECT_EQ(RadarConfiguration::kEnRoute, radar::configuration_for(MissionPhase::EGRESS));
    EXPECT_EQ(RadarConfiguration::kAirport, radar::configuration_for(MissionPhase::COMPLETE));
    const radar::RadarAllocation enroute = radar::allocation_for(RadarConfiguration::kEnRoute);
    EXPECT_EQ(icd::WeatherMode::SURVEILLANCE, enroute.weather);
    EXPECT_EQ(icd::TfrMode::TERRAIN_FOLLOWING, enroute.tfr);
    EXPECT_EQ(icd::TargetingMode::TARGET_SEARCH, enroute.targeting);
    EXPECT_EQ(icd::SarMode::STRIPMAP, enroute.sar);
    EXPECT_EQ(icd::AewcMode::AEWC_SEARCH, enroute.aewc);
    const radar::RadarAllocation airport = radar::allocation_for(RadarConfiguration::kAirport);
    EXPECT_EQ(icd::WeatherMode::SURVEILLANCE, airport.weather);
    EXPECT_EQ(icd::TfrMode::TERRAIN_FOLLOWING, airport.tfr);
    EXPECT_EQ(icd::TargetingMode::NONE, airport.targeting);
    EXPECT_EQ(icd::SarMode::NONE, airport.sar);
    EXPECT_EQ(icd::AewcMode::NONE, airport.aewc);
}

TEST(MissionAllocation, TheAllocatorReconfiguresOnlyWhenTheConfigurationChanges) {
    radar::MissionAllocator a;
    RadarConfiguration out = RadarConfiguration::kNone;
    EXPECT_FALSE(a.observe(status_in(MissionPhase::INGRESS, TerminalState::INITIALIZING), out))
        << "a mission computer not yet NORMAL is not followed";
    EXPECT_FALSE(a.observe(status_in(MissionPhase::PLANNING), out));
    EXPECT_TRUE(a.observe(status_in(MissionPhase::INGRESS), out));
    EXPECT_EQ(RadarConfiguration::kEnRoute, out);
    EXPECT_FALSE(a.observe(status_in(MissionPhase::INGRESS), out)) << "the same phase again";
    EXPECT_FALSE(a.observe(status_in(MissionPhase::OBJECTIVE), out)) << "the same configuration";
    EXPECT_TRUE(a.observe(status_in(MissionPhase::COMPLETE), out));
    EXPECT_EQ(RadarConfiguration::kAirport, out);
    EXPECT_FALSE(a.observe(status_in(MissionPhase::PLANNING), out)) << "PLANNING configures nothing";
    EXPECT_TRUE(a.observe(status_in(MissionPhase::INGRESS), out)) << "but a later INGRESS is a change again";
    EXPECT_EQ(3U, a.allocations());
    a.reset();
    EXPECT_EQ(0U, a.allocations());
    EXPECT_EQ(RadarConfiguration::kNone, a.current());
}

TEST(MissionAllocation, EachRadarTakesItsModeAndKeepsItsSettingsAndCommandNumber) {
    static radar::WeatherRadar weather;
    static radar::TerrainFollowing tfr;
    static radar::TargetingRadar targeting;
    static radar::AewcRadar aewc;
    static radar::SarRadar sar;
    ASSERT_EQ(Status::kOk, weather.init());
    ASSERT_EQ(Status::kOk, tfr.init());
    ASSERT_EQ(Status::kOk, targeting.init());
    ASSERT_EQ(Status::kOk, aewc.init());
    ASSERT_EQ(Status::kOk, sar.init());
    icd::RdrTfrModeCmd clearance{};
    clearance.cmd_seq = 7;
    clearance.requested_state = TerminalState::STANDBY;
    clearance.set_clearance = 1500.0;
    tfr.command_mode(clearance);
    ASSERT_EQ(1500.0, tfr.set_clearance_ft());

    weather.allocate(icd::WeatherMode::SURVEILLANCE);
    tfr.allocate(icd::TfrMode::TERRAIN_FOLLOWING);
    targeting.allocate(icd::TargetingMode::TARGET_SEARCH);
    aewc.allocate(icd::AewcMode::AEWC_SEARCH);
    sar.allocate(icd::SarMode::STRIPMAP);
    EXPECT_EQ(icd::WeatherMode::SURVEILLANCE, weather.mode());
    EXPECT_EQ(icd::TfrMode::TERRAIN_FOLLOWING, tfr.mode());
    EXPECT_EQ(icd::TargetingMode::TARGET_SEARCH, targeting.mode());
    EXPECT_EQ(icd::AewcMode::AEWC_SEARCH, aewc.mode());
    EXPECT_EQ(icd::SarMode::STRIPMAP, sar.mode());
    EXPECT_EQ(TerminalState::NORMAL, targeting.state());
    EXPECT_EQ(1500.0, tfr.set_clearance_ft()) << "the operator's clearance is kept";
    EXPECT_EQ(7U, tfr.status().last_cmd_seq) << "an allocation is no numbered command";

    targeting.allocate(icd::TargetingMode::NONE);
    sar.allocate(icd::SarMode::NONE);
    EXPECT_EQ(TerminalState::STANDBY, targeting.state());
    EXPECT_EQ(icd::TargetingMode::NONE, targeting.mode());
    EXPECT_EQ(TerminalState::STANDBY, sar.state());

    // A numbered command after an allocation is still taken (the allocation used no number).
    icd::RdrTgtModeCmd tgt{};
    tgt.cmd_seq = 1;
    tgt.requested_state = TerminalState::NORMAL;
    tgt.requested_mode = icd::TargetingMode::TARGET_TRACK;
    targeting.command_mode(tgt);
    EXPECT_EQ(icd::TargetingMode::TARGET_TRACK, targeting.mode());
}

icd::MsnBriefCmd brief(icd::BriefingCommand command, std::uint8_t seq, const char* text, const char* key = "") {
    icd::MsnBriefCmd c{};
    c.command = command;
    c.cmd_seq = seq;
    std::array<std::uint16_t, mission::kBriefingTextWords> t{};
    std::array<std::uint16_t, mission::kBriefingKeyWords> k{};
    for (std::size_t i = 0; i < std::strlen(text) && i < mission::kBriefingTextChars; ++i) {
        const auto ch = static_cast<std::uint16_t>(static_cast<unsigned char>(text[i]));
        t[i / 2] = static_cast<std::uint16_t>(t[i / 2] | (i % 2 == 0 ? static_cast<std::uint16_t>(ch << 8U) : ch));
    }
    for (std::size_t i = 0; i < std::strlen(key) && i < mission::kBriefingKeyChars; ++i) {
        const auto ch = static_cast<std::uint16_t>(static_cast<unsigned char>(key[i]));
        k[i / 2] = static_cast<std::uint16_t>(k[i / 2] | (i % 2 == 0 ? static_cast<std::uint16_t>(ch << 8U) : ch));
    }
    c.text_0 = t[0]; c.text_1 = t[1]; c.text_2 = t[2]; c.text_3 = t[3]; c.text_4 = t[4]; c.text_5 = t[5];
    c.text_6 = t[6]; c.text_7 = t[7]; c.text_8 = t[8]; c.text_9 = t[9]; c.text_10 = t[10]; c.text_11 = t[11];
    c.key_0 = k[0]; c.key_1 = k[1]; c.key_2 = k[2]; c.key_3 = k[3];
    return c;
}

std::string text_of(const mission::BriefingText& t) { return std::string(t.chars.data(), t.length); }

TEST(MissionBriefing, ObjectivesAndRulesAreListsAndIntelligenceADictionary) {
    mission::MissionComputer mc;
    ASSERT_EQ(Status::kOk, mc.init());
    using BC = icd::BriefingCommand;
    mc.command_briefing(brief(BC::ADD_OBJECTIVE, 1, "Destroy the bridge"));
    mc.command_briefing(brief(BC::ADD_OBJECTIVE, 2, "Return to base"));
    mc.command_briefing(brief(BC::ADD_ROE, 3, "Weapons hold"));
    mc.command_briefing(brief(BC::UPDATE_INTELLIGENCE, 4, "SA-6 at the ridge", "threat"));
    mc.command_briefing(brief(BC::UPDATE_INTELLIGENCE, 5, "SA-11 moved north", "threat"));
    mc.command_briefing(brief(BC::UPDATE_INTELLIGENCE, 6, "clear", "weather"));
    const mission::Briefing& b = mc.briefing();
    ASSERT_EQ(2U, b.objective_count());
    EXPECT_EQ("Destroy the bridge", text_of(b.objective(0)));
    EXPECT_EQ("Return to base", text_of(b.objective(1)));
    EXPECT_EQ(1U, b.roe_count());
    ASSERT_EQ(2U, b.intelligence_count()) << "a known key's value replaced, as dict.update does";
    EXPECT_EQ("SA-11 moved north", text_of(b.intelligence(0).value));
    EXPECT_EQ(std::string("weather"), std::string(b.intelligence(1).key.data(), b.intelligence(1).key_length));
    EXPECT_EQ(2U, mc.status().objective_count);
    EXPECT_EQ(1U, mc.status().roe_count);
    EXPECT_EQ(2U, mc.status().intelligence_count);
    EXPECT_EQ(CmdStatus::ACCEPTED, mc.status().brief_cmd_status);
    EXPECT_EQ(6U, mc.status().last_brief_cmd_seq);

    mc.command_briefing(brief(BC::ADD_OBJECTIVE, 6, "ignored: the same number"));
    EXPECT_EQ(2U, b.objective_count());
    mc.command_briefing(brief(BC::ADD_ROE, 7, ""));
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, mc.status().brief_cmd_status);
    mc.command_briefing(brief(BC::UPDATE_INTELLIGENCE, 8, "no key"));
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, mc.status().brief_cmd_status);
    mc.command_briefing(brief(BC::CLEAR_OBJECTIVES, 9, ""));
    EXPECT_EQ(0U, mc.status().objective_count);
    for (std::uint8_t i = 0; i < mission::kBriefingEntries; ++i) {
        mc.command_briefing(brief(BC::ADD_OBJECTIVE, static_cast<std::uint8_t>(10 + i), "objective"));
    }
    EXPECT_EQ(mission::kBriefingEntries, b.objective_count());
    mc.command_briefing(brief(BC::ADD_OBJECTIVE, 30, "one too many"));
    EXPECT_EQ(CmdStatus::FAILED, mc.status().brief_cmd_status);
    mc.command_briefing(brief(BC::ADD_OBJECTIVE, 31, "abcdefghijklmnopqrstuvwxyz"));
    EXPECT_EQ(CmdStatus::FAILED, mc.status().brief_cmd_status);
    mc.command_briefing(brief(BC::CLEAR_ROE, 32, ""));
    mc.command_briefing(brief(BC::CLEAR_INTELLIGENCE, 33, ""));
    EXPECT_EQ(0U, mc.status().roe_count);
    EXPECT_EQ(0U, mc.status().intelligence_count);
    mc.command_briefing(brief(BC::ADD_ROE, 34, "abcdefghijklmnopqrstuvwxyz"));
    EXPECT_EQ("abcdefghijklmnopqrstuvwx", text_of(b.roe(0))) << "24 characters: the message holds no more";
    mc.reset();
    EXPECT_EQ(0U, mc.briefing().roe_count());
}

}  // namespace
