// The flight data monitoring terminal against fdmControl.py: the config tables,
// the ring of records, the storage cards' ejection, the record every 25 frames
// while the flight data is fresh, the commands, the outputs.
#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

#include <fmofp/fdm/flight_data_recorder.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::fdm;  // NOLINT: test
using namespace fmofp::icd;  // NOLINT: test

FmsFlightData flight(double altitude, double airspeed) {
    FmsFlightData f{};
    f.altitude_ssm = Ssm::NORMAL;
    f.airspeed_ssm = Ssm::NORMAL;
    f.altitude = altitude;
    f.airspeed = airspeed;
    return f;
}

FdmCmd eject(std::uint8_t seq, std::uint8_t slot) {
    FdmCmd c{};
    c.cmd_seq = seq;
    c.command = FdmCommand::EJECT_STORAGE;
    c.slot = slot;
    return c;
}

TEST(FlightDataRecorder, InitAndTheConfigTables) {
    FlightDataRecorder fdm;
    ASSERT_EQ(Status::kOk, fdm.init());
    EXPECT_EQ(TerminalState::INITIALIZING, fdm.state());
    EXPECT_EQ(0U, fdm.records());
    EXPECT_EQ(0U, fdm.held());
    EXPECT_TRUE(fdm.slot_present(1) && fdm.slot_present(2));
    EXPECT_FALSE(fdm.slot_present(0) || fdm.slot_present(3));
    EXPECT_EQ(2U, kRecorders.size());
    EXPECT_STREQ("Flight Data Recorder (FDR)", kRecorders[0].description);
    EXPECT_EQ(3U, kRecorders[0].parameter_count);
    EXPECT_STREQ("UTC Time", kRecorders[0].parameters[0].name);
    EXPECT_STREQ("sec", kRecorders[0].parameters[0].units);
    EXPECT_STREQ("Airspeed", kRecorders[0].parameters[2].name);
    EXPECT_STREQ("kts", kRecorders[0].parameters[2].units);
    EXPECT_STREQ("Cockpit Voice Recorder (CVR)", kRecorders[1].description);
    EXPECT_EQ(1U, kRecorders[1].parameter_count);
    EXPECT_STREQ("Audio", kRecorders[1].parameters[0].name);
    EXPECT_EQ(16U, kCards[0].capacity_gb);
    EXPECT_STREQ("cvr", kCards[1].contents);
}

TEST(FlightDataRecorder, TheRingKeepsTheLastFiveHundredAndTwelve) {
    FlightDataRecorder fdm;
    ASSERT_EQ(Status::kOk, fdm.init());
    for (std::uint32_t i = 1; i <= 600; ++i) {
        fdm.record(i * 25, 10000.0 + i, 450.0);
    }
    EXPECT_EQ(600U, fdm.records());
    EXPECT_EQ(kRingCapacity, fdm.held());
    EXPECT_EQ(89U * 25U, fdm.record_at(0).frame);  // the oldest held: record 89
    EXPECT_EQ(10089.0, fdm.record_at(0).altitude_ft);
    EXPECT_EQ(600U * 25U, fdm.record_at(fdm.held() - 1).frame);
    EXPECT_EQ(0U, fdm.record_at(kRingCapacity).frame);  // past the end: a default record
    fdm.step(nullptr, 15001);  // the frame fills the status message (no record: not a 25th frame, no flight data)
    EXPECT_EQ(600U, fdm.records());
    EXPECT_EQ(600.0, fdm.status().records);
    EXPECT_EQ(512.0, fdm.status().held);
    EXPECT_EQ(10600.0, fdm.status().last_altitude);
    EXPECT_EQ(15000.0, fdm.status().last_frame);
}

TEST(FlightDataRecorder, EjectingACardOnceAndTheCommandOutcomes) {
    FlightDataRecorder fdm;
    ASSERT_EQ(Status::kOk, fdm.init());
    EXPECT_TRUE(fdm.eject_storage(1));
    EXPECT_FALSE(fdm.eject_storage(1));  // "No storage card in slot 1"
    EXPECT_FALSE(fdm.eject_storage(3));
    EXPECT_FALSE(fdm.slot_present(1));
    EXPECT_TRUE(fdm.slot_present(2));
    fdm.command(eject(1, 2), 10);
    EXPECT_EQ(CmdStatus::ACCEPTED, fdm.status().fdm_cmd_status);
    EXPECT_FALSE(fdm.status().slot_2_present);
    fdm.command(eject(2, 2), 11);
    EXPECT_EQ(CmdStatus::FAILED, fdm.status().fdm_cmd_status);
    fdm.command(eject(3, 3), 12);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, fdm.status().fdm_cmd_status);
    FdmCmd none{};
    none.cmd_seq = 4;
    fdm.command(none, 13);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, fdm.status().fdm_cmd_status);
    // Recording goes on with both cards out, as in the Python.
    fdm.record(100, 9000.0, 440.0);
    EXPECT_EQ(1U, fdm.records());
    fdm.reset();
    EXPECT_TRUE(fdm.slot_present(1) && fdm.slot_present(2));
    EXPECT_EQ(0U, fdm.records());
}

TEST(FlightDataRecorder, AFrameRecordsEveryTwentyFiveWhileTheFlightDataIsFresh) {
    FlightDataRecorder fdm;
    ASSERT_EQ(Status::kOk, fdm.init());
    fdm.step(nullptr, 25);
    EXPECT_EQ(0U, fdm.records());  // nothing to record yet
    EXPECT_EQ(TerminalState::INITIALIZING, fdm.state());
    const FmsFlightData f = flight(12345.0, 420.5);
    for (std::uint32_t frame = 26; frame <= 100; ++frame) {
        if (frame % 5 == 0) {
            fdm.step(&f, frame);  // the 10 Hz broadcast
        } else {
            fdm.step(nullptr, frame);
        }
    }
    EXPECT_EQ(TerminalState::NORMAL, fdm.state());
    EXPECT_TRUE(fdm.status().flight_data_valid);
    EXPECT_EQ(3U, fdm.records());  // frames 50, 75, 100
    EXPECT_EQ(50U, fdm.record_at(0).frame);
    EXPECT_EQ(100U, fdm.record_at(fdm.held() - 1).frame);
    EXPECT_EQ(12345.0, fdm.status().last_altitude);
    EXPECT_EQ(420.5, fdm.status().last_airspeed);
    EXPECT_EQ(100.0, fdm.status().last_frame);
    for (std::uint32_t frame = 101; frame <= 200; ++frame) {
        fdm.step(nullptr, frame);  // the broadcast stops: no more records, DEGRADED after 15 frames
    }
    EXPECT_EQ(3U, fdm.records());
    EXPECT_EQ(TerminalState::DEGRADED, fdm.state());
    EXPECT_FALSE(fdm.status().flight_data_valid);
    FdmStatus::Words words{};
    ASSERT_EQ(Status::kOk, fdm.status().encode(words));
    FdmStatus back{};
    ASSERT_EQ(Status::kOk, FdmStatus::decode(words, back));
    EXPECT_EQ(3.0, back.records);
    EXPECT_EQ(12345.0, back.last_altitude);
    EXPECT_NEAR(420.5, back.last_airspeed, 0.05);
    EXPECT_EQ(100.0, back.last_frame);
    EXPECT_TRUE(back.slot_1_present && back.slot_2_present);
}

// The terminal's own housekeeping, as every partition has it (added with unit 30's coverage floor): the mode
// command, the self test, the way back from DEGRADED, a repeated command, a record that is not a number.
TEST(FlightDataRecorder, ModeCommandsTheSelfTestAndRecovery) {
    FlightDataRecorder fdm;
    ASSERT_EQ(Status::kOk, fdm.init());
    const FmsFlightData f = flight(9000.0, 300.0);
    fdm.step(&f, 1);
    ASSERT_EQ(TerminalState::NORMAL, fdm.state());

    FdmModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::FAILURE;  // not a state a command may ask for
    fdm.command_mode(mode);
    EXPECT_TRUE(fdm.status().cmd_rejected);
    EXPECT_EQ(1U, fdm.status().last_cmd_seq);
    EXPECT_EQ(TerminalState::NORMAL, fdm.state());
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::MAINTENANCE;
    fdm.command_mode(mode);
    EXPECT_FALSE(fdm.status().cmd_rejected);
    EXPECT_EQ(TerminalState::MAINTENANCE, fdm.state());
    mode.requested_state = TerminalState::STANDBY;  // the same sequence number again: not a new command
    fdm.command_mode(mode);
    EXPECT_EQ(TerminalState::MAINTENANCE, fdm.state());
    mode.cmd_seq = 3;
    mode.requested_state = TerminalState::NORMAL;
    fdm.command_mode(mode);
    ASSERT_EQ(TerminalState::NORMAL, fdm.state());

    fdm.start_self_test();
    EXPECT_TRUE(fdm.bit().in_progress);
    fdm.step(&f, 2);
    EXPECT_TRUE(fdm.bit().in_progress);
    fdm.step(&f, 2 + kSelfTestFrames);
    EXPECT_FALSE(fdm.bit().in_progress);
    EXPECT_FALSE(fdm.bit().failed);

    // The flight data stops and comes back: DEGRADED, then NORMAL again.
    const std::uint32_t quiet = 2 + kSelfTestFrames + kFlightDataStaleFrames;
    fdm.step(nullptr, quiet);
    EXPECT_EQ(TerminalState::DEGRADED, fdm.state());
    fdm.step(&f, quiet + 1);
    EXPECT_EQ(TerminalState::NORMAL, fdm.state());

    // A repeated eject is one command; a record that is not a number is not kept.
    fdm.command(eject(7, 1), quiet + 2);
    EXPECT_FALSE(fdm.slot_present(1));
    const std::uint32_t before = fdm.records();
    fdm.command(eject(7, 2), quiet + 3);
    EXPECT_TRUE(fdm.slot_present(2)) << "sequence 7 was already taken";
    fdm.record(quiet + 4, std::numeric_limits<double>::quiet_NaN(), 300.0);
    fdm.record(quiet + 4, 9000.0, std::numeric_limits<double>::infinity());
    EXPECT_EQ(before, fdm.records());

    fdm.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, fdm.state());
    EXPECT_TRUE(fdm.slot_present(1));
    EXPECT_EQ(0U, fdm.records());
}

}  // namespace
