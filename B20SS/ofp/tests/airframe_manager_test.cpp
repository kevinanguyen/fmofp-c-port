// The airframe terminal against airframeControl.py: the gear state machine
// (idempotent, commanded only), the FMS's gear command applied when it changes,
// the readings reported pass by pass with their freshness, the commands, the
// config table, the outputs.
#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>

#include <fmofp/airframe/airframe_manager.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::airframe;  // NOLINT: test
using namespace fmofp::icd;       // NOLINT: test

PlantAirframe reading(std::uint8_t epoch, double wing, double fuselage, double temp) {
    PlantAirframe a{};
    a.epoch = epoch;
    a.wing_root_strain = wing;
    a.fuselage_strain = fuselage;
    a.leading_edge_temp = temp;
    return a;
}

FmsControlStatus fms_gear(GearPosition gear) {
    FmsControlStatus f{};
    f.gear = gear;
    return f;
}

TEST(AirframeManager, InitAndTheConfigTable) {
    AirframeManager afr;
    ASSERT_EQ(Status::kOk, afr.init());
    EXPECT_EQ(TerminalState::INITIALIZING, afr.state());
    EXPECT_EQ(GearState::UNKNOWN, afr.gear_state());
    EXPECT_FALSE(afr.have_reading());
    EXPECT_EQ(3U, kSensors.size());
    EXPECT_EQ(1, kSensors[0].id);
    EXPECT_STREQ("strain", kSensors[0].type);
    EXPECT_STREQ("Wing root", kSensors[0].location);
    EXPECT_STREQ("Fuselage", kSensors[1].location);
    EXPECT_STREQ("temperature", kSensors[2].type);
    EXPECT_STREQ("LeadingEdges", kSensors[2].location);
}

TEST(AirframeManager, TheGearRecordsTheCommandedState) {
    AirframeManager afr;
    ASSERT_EQ(Status::kOk, afr.init());
    EXPECT_EQ(GearState::DEPLOYED, afr.control_landing_gear(GearCommand::DEPLOY));
    EXPECT_EQ(GearState::DEPLOYED, afr.control_landing_gear(GearCommand::DEPLOY));  // already: no action
    EXPECT_EQ(GearState::RETRACTED, afr.control_landing_gear(GearCommand::RETRACT));
    EXPECT_EQ(GearState::RETRACTED, afr.gear_state());
}

TEST(AirframeManager, TheFmsGearCommandDrivesTheGearWhenItChanges) {
    AirframeManager afr;
    ASSERT_EQ(Status::kOk, afr.init());
    const FmsControlStatus up = fms_gear(GearPosition::UP);
    afr.step(nullptr, &up, 1);  // the FMS's first status: gear UP, as before any command
    EXPECT_EQ(GearState::RETRACTED, afr.gear_state());
    const FmsControlStatus down = fms_gear(GearPosition::DOWN);
    afr.step(nullptr, &down, 2);
    EXPECT_EQ(GearState::DEPLOYED, afr.gear_state());
    AfrCmd cmd{};
    cmd.cmd_seq = 1;
    cmd.command = AirframeCommand::GEAR_RETRACT;
    afr.command(cmd, 3);  // by hand ...
    EXPECT_EQ(GearState::RETRACTED, afr.status().gear_state);
    afr.step(nullptr, &down, 4);  // ... stands while the FMS keeps saying the same DOWN
    EXPECT_EQ(GearState::RETRACTED, afr.gear_state());
    afr.step(nullptr, &up, 5);
    afr.step(nullptr, &down, 6);  // a change again: the FMS moves it
    EXPECT_EQ(GearState::DEPLOYED, afr.gear_state());
    const FmsControlStatus transit = fms_gear(GearPosition::IN_TRANSIT);
    afr.step(nullptr, &transit, 7);  // commands nothing
    EXPECT_EQ(GearState::DEPLOYED, afr.gear_state());
    cmd.cmd_seq = 2;
    cmd.command = AirframeCommand::NONE;
    afr.command(cmd, 8);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, afr.status().afr_cmd_status);
    EXPECT_EQ(GearState::DEPLOYED, afr.gear_state());
}

TEST(AirframeManager, ReadingsArePassedOnPassByPassWithTheirFreshness) {
    AirframeManager afr;
    ASSERT_EQ(Status::kOk, afr.init());
    const PlantAirframe first = reading(1, 185.0, 112.0, -5.25);
    afr.step(&first, nullptr, 1);
    EXPECT_EQ(TerminalState::NORMAL, afr.state());
    EXPECT_TRUE(afr.status().sensors_valid);
    EXPECT_EQ(1U, afr.passes());
    EXPECT_EQ(185.0, afr.status().wing_root_strain);
    EXPECT_EQ(112.0, afr.status().fuselage_strain);
    EXPECT_EQ(-5.25, afr.status().leading_edge_temp);
    afr.step(&first, nullptr, 2);  // the same epoch: no pass
    EXPECT_EQ(1U, afr.passes());
    const PlantAirframe second = reading(2, 190.0, 115.0, -5.0);
    afr.step(&second, nullptr, 3);
    EXPECT_EQ(2U, afr.passes());
    for (std::uint32_t frame = 4; frame < 3 + kSensorStaleFrames; ++frame) {
        afr.step(nullptr, nullptr, frame);
    }
    EXPECT_EQ(TerminalState::NORMAL, afr.state());
    afr.step(nullptr, nullptr, 3 + kSensorStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, afr.state());
    EXPECT_FALSE(afr.status().sensors_valid);
    AfrStatus::Words words{};
    ASSERT_EQ(Status::kOk, afr.status().encode(words));
    AfrStatus back{};
    ASSERT_EQ(Status::kOk, AfrStatus::decode(words, back));
    EXPECT_EQ(190.0, back.wing_root_strain);
    EXPECT_NEAR(-5.0, back.leading_edge_temp, 0.005);
    EXPECT_EQ(GearState::UNKNOWN, back.gear_state);
    EXPECT_EQ(TerminalState::DEGRADED, back.state);
}

TEST(AirframeManager, ModeCommandSelfTestAndReset) {
    AirframeManager afr;
    ASSERT_EQ(Status::kOk, afr.init());
    AfrModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::INITIALIZING;  // not commandable
    afr.command_mode(mode);
    EXPECT_TRUE(afr.status().cmd_rejected);
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::TEST;
    afr.command_mode(mode);
    EXPECT_EQ(TerminalState::TEST, afr.state());
    afr.start_self_test();
    EXPECT_TRUE(afr.bit().in_progress);
    for (std::uint32_t frame = 1; frame <= kSelfTestFrames + 1; ++frame) {
        afr.step(nullptr, nullptr, frame);
    }
    EXPECT_FALSE(afr.bit().in_progress);
    (void)afr.control_landing_gear(GearCommand::DEPLOY);
    afr.reset();
    EXPECT_EQ(GearState::UNKNOWN, afr.gear_state());
    EXPECT_EQ(TerminalState::INITIALIZING, afr.state());
}

}  // namespace
