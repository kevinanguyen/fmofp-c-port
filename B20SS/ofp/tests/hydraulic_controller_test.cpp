// The hydraulics terminal against hydrControl.py: the thresholds (at-or-under,
// where the Python compared a constant for equality), the switch to the backup
// on CRITICAL and by hand, the pass per new reading with its freshness, the
// commands, the outputs.
#include <gtest/gtest.h>

#include <cstdint>

#include <fmofp/hydraulics/hydraulic_controller.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::hydraulics;  // NOLINT: test
using namespace fmofp::icd;         // NOLINT: test

PlantHydraulics reading(std::uint8_t epoch, double primary, double backup) {
    PlantHydraulics p{};
    p.epoch = epoch;
    p.primary_psi = primary;
    p.backup_psi = backup;
    return p;
}

TEST(HydraulicController, InitIsTheConstructor) {
    HydraulicController hyd;
    ASSERT_EQ(Status::kOk, hyd.init());
    EXPECT_EQ(TerminalState::INITIALIZING, hyd.state());
    EXPECT_EQ(HydraulicSystem::PRIMARY, hyd.active_system());
    EXPECT_EQ(PressureStatus::OK, hyd.pressure_status());
    EXPECT_FALSE(hyd.have_reading());
    EXPECT_EQ((3000.0), kNominalPsi);
    EXPECT_EQ((2500.0), kWarningPsi);
    EXPECT_EQ((2000.0), kCriticalPsi);
}

TEST(HydraulicController, TheStatusAtAndAroundTheThresholds) {
    HydraulicController hyd;
    ASSERT_EQ(Status::kOk, hyd.init());
    hyd.monitor(2800.0, 2950.0);  // the Python's constant: OK
    EXPECT_EQ(PressureStatus::OK, hyd.pressure_status());
    hyd.monitor(2501.0, 2950.0);
    EXPECT_EQ(PressureStatus::OK, hyd.pressure_status());
    hyd.monitor(2500.0, 2950.0);
    EXPECT_EQ(PressureStatus::WARNING, hyd.pressure_status());
    hyd.monitor(2001.0, 2950.0);
    EXPECT_EQ(PressureStatus::WARNING, hyd.pressure_status());
    EXPECT_EQ(HydraulicSystem::PRIMARY, hyd.active_system());
    hyd.monitor(2000.0, 2950.0);  // CRITICAL: the backup takes over, for good
    EXPECT_EQ(PressureStatus::CRITICAL, hyd.pressure_status());
    EXPECT_EQ(HydraulicSystem::BACKUP, hyd.active_system());
    EXPECT_EQ(2950.0, hyd.active_psi());
    hyd.monitor(3000.0, 2950.0);  // the primary back up: the backup's pressure is what is judged now
    EXPECT_EQ(PressureStatus::OK, hyd.pressure_status());
    EXPECT_EQ(HydraulicSystem::BACKUP, hyd.active_system());
    hyd.monitor(3000.0, 2400.0);
    EXPECT_EQ(PressureStatus::WARNING, hyd.pressure_status());
}

TEST(HydraulicController, TheBackupByHandAndTheCommandRule) {
    HydraulicController hyd;
    ASSERT_EQ(Status::kOk, hyd.init());
    HydCmd cmd{};
    cmd.cmd_seq = 1;
    cmd.command = HydraulicCommand::ACTIVATE_BACKUP;
    hyd.command(cmd, 5);
    EXPECT_EQ(CmdStatus::ACCEPTED, hyd.status().hyd_cmd_status);
    EXPECT_EQ(HydraulicSystem::BACKUP, hyd.status().active_system);
    hyd.command(cmd, 6);  // the same sequence: ignored
    cmd.cmd_seq = 2;
    hyd.command(cmd, 7);  // again: accepted, already the backup
    EXPECT_EQ(CmdStatus::ACCEPTED, hyd.status().hyd_cmd_status);
    cmd.cmd_seq = 3;
    cmd.command = HydraulicCommand::NONE;
    hyd.command(cmd, 8);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, hyd.status().hyd_cmd_status);
    HydModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::MAINTENANCE;
    hyd.command_mode(mode);
    EXPECT_EQ(TerminalState::MAINTENANCE, hyd.state());
    hyd.reset();
    EXPECT_EQ(HydraulicSystem::PRIMARY, hyd.active_system());
    EXPECT_EQ(TerminalState::INITIALIZING, hyd.state());
}

TEST(HydraulicController, AFrameRunsOnePassPerNewReadingAndFollowsTheFreshness) {
    HydraulicController hyd;
    ASSERT_EQ(Status::kOk, hyd.init());
    const PlantHydraulics first = reading(1, 2450.0, 2950.0);
    hyd.step(&first, 1);
    EXPECT_EQ(TerminalState::NORMAL, hyd.state());
    EXPECT_TRUE(hyd.status().pressures_valid);
    EXPECT_EQ(PressureStatus::WARNING, hyd.status().pressure_status);
    EXPECT_EQ(2450.0, hyd.status().primary_psi);
    const PlantHydraulics second = reading(2, 1900.0, 2950.0);
    hyd.step(&second, 2);
    EXPECT_EQ(PressureStatus::CRITICAL, hyd.status().pressure_status);
    EXPECT_EQ(HydraulicSystem::BACKUP, hyd.status().active_system);
    for (std::uint32_t frame = 3; frame < 2 + kPressureStaleFrames; ++frame) {
        hyd.step(nullptr, frame);
    }
    EXPECT_EQ(TerminalState::NORMAL, hyd.state());
    hyd.step(nullptr, 2 + kPressureStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, hyd.state());
    EXPECT_FALSE(hyd.status().pressures_valid);
    EXPECT_EQ(PressureStatus::CRITICAL, hyd.status().pressure_status);  // the last judgement stands
    HydStatus::Words words{};
    ASSERT_EQ(Status::kOk, hyd.status().encode(words));
    HydStatus back{};
    ASSERT_EQ(Status::kOk, HydStatus::decode(words, back));
    EXPECT_EQ((1900.0), back.primary_psi);
    EXPECT_EQ((2950.0), back.backup_psi);
    EXPECT_EQ(HydraulicSystem::BACKUP, back.active_system);
    EXPECT_EQ(TerminalState::DEGRADED, back.state);
}

// The terminal's own housekeeping (added with unit 30's coverage floor): a mode command that may not be asked
// for, a repeated one, the self test, the way back from DEGRADED.
TEST(HydraulicController, ModeCommandsTheSelfTestAndRecovery) {
    HydraulicController hyd;
    ASSERT_EQ(Status::kOk, hyd.init());
    const PlantHydraulics first = reading(1, 2900.0, 2950.0);
    hyd.step(&first, 1);
    ASSERT_EQ(TerminalState::NORMAL, hyd.state());

    HydModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::FAILURE;
    hyd.command_mode(mode);
    EXPECT_TRUE(hyd.status().cmd_rejected);
    EXPECT_EQ(TerminalState::NORMAL, hyd.state());
    mode.requested_state = TerminalState::STANDBY;  // the same sequence number: not a new command
    hyd.command_mode(mode);
    EXPECT_EQ(TerminalState::NORMAL, hyd.state());
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::NORMAL;
    hyd.command_mode(mode);
    EXPECT_FALSE(hyd.status().cmd_rejected);
    EXPECT_EQ(2U, hyd.status().last_cmd_seq);

    hyd.start_self_test();
    EXPECT_TRUE(hyd.bit().in_progress);
    hyd.step(nullptr, 2);
    EXPECT_TRUE(hyd.bit().in_progress);
    hyd.step(nullptr, 2 + kSelfTestFrames);
    EXPECT_FALSE(hyd.bit().in_progress);

    hyd.step(nullptr, 1 + kPressureStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, hyd.state());
    const PlantHydraulics again = reading(2, 2900.0, 2950.0);
    hyd.step(&again, 2 + kPressureStaleFrames);
    EXPECT_EQ(TerminalState::NORMAL, hyd.state());
    EXPECT_TRUE(hyd.status().pressures_valid);
}

}  // namespace
