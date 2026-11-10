// The flight surfaces terminal against flightSurfaceService.py: Surface.step's
// rate limit and clamp, the sync from the sensed roll, pitch and angle of attack
// (the ailerons opposed, the elevators, the slats' threshold), the manual
// controls' detents and clamps, the frame with its freshness and state, the
// command sequence rule, the outputs.
#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>

#include <fmofp/surfaces/flight_surfaces.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::surfaces;  // NOLINT: test
using namespace fmofp::icd;       // NOLINT: test

PlantSensors sensed(double roll, double pitch, double aoa) {
    PlantSensors s{};
    s.roll_ssm = Ssm::NORMAL;
    s.pitch_ssm = Ssm::NORMAL;
    s.aoa_ssm = Ssm::NORMAL;
    s.roll = roll;
    s.pitch = pitch;
    s.angle_of_attack = aoa;
    return s;
}

FsfCmd command(std::uint8_t seq, SurfaceCommand what, double value = 0.0, TrimAxis axis = TrimAxis::PITCH) {
    FsfCmd c{};
    c.cmd_seq = seq;
    c.command = what;
    c.value = value;
    c.axis = axis;
    return c;
}

double cmd_of(const FlightSurfaces& fs, SurfaceId id) { return fs.surface(id).cmd; }
double pos_of(const FlightSurfaces& fs, SurfaceId id) { return fs.surface(id).position; }

TEST(Surface, StepsTowardTheCommandAtItsRateAndStopsOnIt) {
    Surface s;
    s.rate_deg_s = 60.0;
    s.limit_lo = -25.0;
    s.limit_hi = 25.0;
    s.cmd = 10.0;
    for (int i = 1; i <= 8; ++i) {
        s.step(0.02);
        EXPECT_NEAR(1.2 * i, s.position, 1e-12);
    }
    s.step(0.02);  // the last 0.4, not a full 1.2
    EXPECT_DOUBLE_EQ(10.0, s.position);
    s.step(0.02);
    EXPECT_DOUBLE_EQ(10.0, s.position);
    s.cmd = -3.0;
    s.step(0.02);
    EXPECT_DOUBLE_EQ(8.8, s.position);
    s.step(0.05);  // the Python's dt was the measured time: a longer step moves further
    EXPECT_DOUBLE_EQ(5.8, s.position);
}

TEST(Surface, StaysWithinItsLimits) {
    Surface s;
    s.rate_deg_s = 60.0;
    s.limit_lo = -25.0;
    s.limit_hi = 25.0;
    s.cmd = 100.0;
    for (int i = 0; i < 100; ++i) {
        s.step(0.02);
        EXPECT_LE(s.position, 25.0);
    }
    EXPECT_DOUBLE_EQ(25.0, s.position);
    s.cmd = -100.0;
    for (int i = 0; i < 100; ++i) {
        s.step(0.02);
        EXPECT_GE(s.position, -25.0);
    }
    EXPECT_DOUBLE_EQ(-25.0, s.position);
    Surface flap;
    flap.rate_deg_s = 5.0;
    flap.limit_lo = 0.0;
    flap.limit_hi = 30.0;
    flap.cmd = -5.0;  // below the lower limit: the surface rests on it
    flap.step(0.02);
    EXPECT_DOUBLE_EQ(0.0, flap.position);
}

TEST(FlightSurfaces, InitIsTheServicesConstructor) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    EXPECT_EQ(TerminalState::INITIALIZING, fs.state());
    const Surface& ail = fs.surface(SurfaceId::AILERON_L);
    EXPECT_EQ((60.0), ail.rate_deg_s);
    EXPECT_EQ((-25.0), ail.limit_lo);
    EXPECT_EQ((25.0), ail.limit_hi);
    EXPECT_EQ(50.0, fs.surface(SurfaceId::ELEVATOR_R).rate_deg_s);
    EXPECT_EQ(30.0, fs.surface(SurfaceId::ELEVATOR_R).limit_hi);
    EXPECT_EQ(40.0, fs.surface(SurfaceId::RUDDER).rate_deg_s);
    EXPECT_EQ(5.0, fs.surface(SurfaceId::FLAP_L).rate_deg_s);
    EXPECT_EQ(0.0, fs.surface(SurfaceId::FLAP_R).limit_lo);
    EXPECT_EQ(30.0, fs.surface(SurfaceId::FLAP_R).limit_hi);
    EXPECT_EQ(20.0, fs.surface(SurfaceId::SLAT_L).limit_hi);
    EXPECT_EQ(5.0, fs.surface(SurfaceId::SLAT_R).rate_deg_s);
    EXPECT_EQ(30.0, fs.surface(SurfaceId::SPEEDBRAKE).rate_deg_s);
    EXPECT_EQ(60.0, fs.surface(SurfaceId::SPEEDBRAKE).limit_hi);
    for (std::size_t i = 0; i < kSurfaceCount; ++i) {
        const Surface& s = fs.surface(static_cast<SurfaceId>(i));
        EXPECT_EQ(0.0, s.position);
        EXPECT_EQ(0.0, s.cmd);
        EXPECT_TRUE(s.healthy);
    }
    EXPECT_EQ(0.0, fs.flap_cmd());
    EXPECT_EQ(0.0, fs.trim(TrimAxis::YAW));
    EXPECT_TRUE(fs.all_healthy());
    EXPECT_TRUE(fs.status().healthy);
    EXPECT_FALSE(fs.status().sensors_valid);
    EXPECT_EQ(CmdStatus::NONE, fs.status().surface_cmd_status);
    EXPECT_EQ(Ssm::NORMAL, fs.positions().aileron_l_ssm);
    EXPECT_EQ(Ssm::NORMAL, fs.positions().speedbrake_ssm);
}

TEST(FlightSurfaces, AileronsOpposeTheRollAndElevatorsThePitch) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.sync_from_fcc(20.0, 5.0, 2.0);
    EXPECT_DOUBLE_EQ(10.0, cmd_of(fs, SurfaceId::AILERON_L));   // -(-20 * 0.5)
    EXPECT_DOUBLE_EQ(-10.0, cmd_of(fs, SurfaceId::AILERON_R));  // -20 * 0.5
    EXPECT_DOUBLE_EQ(-4.0, cmd_of(fs, SurfaceId::ELEVATOR_L));  // -5 * 0.8
    EXPECT_DOUBLE_EQ(-4.0, cmd_of(fs, SurfaceId::ELEVATOR_R));
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::RUDDER));  // the sync never touches the rudder
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::SLAT_L));
    // The clamps: a roll beyond 50 degrees and a pitch beyond 37.5 saturate the commands.
    fs.sync_from_fcc(80.0, -60.0, 2.0);
    EXPECT_DOUBLE_EQ(25.0, cmd_of(fs, SurfaceId::AILERON_L));
    EXPECT_DOUBLE_EQ(-25.0, cmd_of(fs, SurfaceId::AILERON_R));
    EXPECT_DOUBLE_EQ(30.0, cmd_of(fs, SurfaceId::ELEVATOR_L));
    fs.sync_from_fcc(-80.0, 60.0, 2.0);
    EXPECT_DOUBLE_EQ(-25.0, cmd_of(fs, SurfaceId::AILERON_L));
    EXPECT_DOUBLE_EQ(25.0, cmd_of(fs, SurfaceId::AILERON_R));
    EXPECT_DOUBLE_EQ(-30.0, cmd_of(fs, SurfaceId::ELEVATOR_R));
}

TEST(FlightSurfaces, SlatsExtendAboveEightDegreesOfAngleOfAttack) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.sync_from_fcc(0.0, 0.0, 8.0);  // not above: in
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::SLAT_L));
    EXPECT_FALSE(fs.slats_extended());
    fs.sync_from_fcc(0.0, 0.0, 8.01);
    EXPECT_DOUBLE_EQ(20.0, cmd_of(fs, SurfaceId::SLAT_L));
    EXPECT_DOUBLE_EQ(20.0, cmd_of(fs, SurfaceId::SLAT_R));
    EXPECT_TRUE(fs.slats_extended());
    fs.sync_from_fcc(0.0, 0.0, 7.9);  // no hysteresis
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::SLAT_R));
    EXPECT_FALSE(fs.slats_extended());
}

TEST(FlightSurfaces, FlapDetentsWithTiesToTheLower) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    const struct {
        double asked;
        double detent;
    } cases[] = {{15.0, 15.0}, {10.0, 5.0}, {22.0, 15.0}, {23.0, 30.0}, {22.5, 15.0}, {2.5, 0.0}, {-3.0, 0.0},
                 {100.0, 30.0}, {7.4, 5.0}, {7.6, 5.0}, {12.0, 15.0}};
    for (const auto& c : cases) {
        fs.set_flaps(c.asked);
        EXPECT_EQ(c.detent, fs.flap_cmd()) << c.asked;
        EXPECT_EQ(c.detent, cmd_of(fs, SurfaceId::FLAP_L)) << c.asked;
        EXPECT_EQ(c.detent, cmd_of(fs, SurfaceId::FLAP_R)) << c.asked;
    }
}

TEST(FlightSurfaces, SpeedbrakeRudderAndTrimClamp) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.set_speedbrake(50.0);
    EXPECT_DOUBLE_EQ(30.0, cmd_of(fs, SurfaceId::SPEEDBRAKE));
    fs.set_speedbrake(150.0);
    EXPECT_DOUBLE_EQ(60.0, cmd_of(fs, SurfaceId::SPEEDBRAKE));
    fs.set_speedbrake(-10.0);
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::SPEEDBRAKE));
    fs.set_rudder(12.5);
    EXPECT_DOUBLE_EQ(12.5, cmd_of(fs, SurfaceId::RUDDER));
    fs.set_rudder(45.0);
    EXPECT_DOUBLE_EQ(30.0, cmd_of(fs, SurfaceId::RUDDER));
    fs.set_rudder(-45.0);
    EXPECT_DOUBLE_EQ(-30.0, cmd_of(fs, SurfaceId::RUDDER));
    EXPECT_TRUE(fs.set_trim(TrimAxis::PITCH, 12.0));
    EXPECT_DOUBLE_EQ(10.0, fs.trim(TrimAxis::PITCH));
    EXPECT_TRUE(fs.set_trim(TrimAxis::YAW, -12.0));
    EXPECT_DOUBLE_EQ(-10.0, fs.trim(TrimAxis::YAW));
    EXPECT_TRUE(fs.set_trim(TrimAxis::ROLL, 3.25));
    EXPECT_DOUBLE_EQ(3.25, fs.trim(TrimAxis::ROLL));
    EXPECT_FALSE(fs.set_trim(static_cast<TrimAxis>(3), 1.0));  // set_trim('bogus', 1.0): ignored
    EXPECT_DOUBLE_EQ(0.0, fs.trim(static_cast<TrimAxis>(3)));
    // The trim moves no surface: every command is what it was.
    EXPECT_DOUBLE_EQ(-30.0, cmd_of(fs, SurfaceId::RUDDER));
    EXPECT_DOUBLE_EQ(0.0, cmd_of(fs, SurfaceId::ELEVATOR_L));
}

TEST(FlightSurfaces, AFrameSyncsAndStepsOnce) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    const PlantSensors s = sensed(20.0, 5.0, 10.0);
    fs.step(&s, 1);
    EXPECT_EQ(TerminalState::NORMAL, fs.state());
    EXPECT_TRUE(fs.status().sensors_valid);
    EXPECT_DOUBLE_EQ(1.2, pos_of(fs, SurfaceId::AILERON_L));   // 60 deg/s x 0.02 s toward +10
    EXPECT_DOUBLE_EQ(-1.2, pos_of(fs, SurfaceId::AILERON_R));
    EXPECT_DOUBLE_EQ(-1.0, pos_of(fs, SurfaceId::ELEVATOR_L));  // 50 x 0.02 toward -4
    EXPECT_DOUBLE_EQ(0.1, pos_of(fs, SurfaceId::SLAT_L));       // 5 x 0.02 toward 20
    EXPECT_TRUE(fs.status().slats_extended);
    for (std::uint32_t frame = 2; frame <= 9; ++frame) {
        fs.step(&s, frame);
    }
    EXPECT_DOUBLE_EQ(10.0, pos_of(fs, SurfaceId::AILERON_L));
    EXPECT_DOUBLE_EQ(-4.0, pos_of(fs, SurfaceId::ELEVATOR_R));
    EXPECT_NEAR(0.9, pos_of(fs, SurfaceId::SLAT_R), 1e-12);
    EXPECT_DOUBLE_EQ(10.0, fs.positions().aileron_l);
    EXPECT_DOUBLE_EQ(-10.0, fs.positions().aileron_r);
    EXPECT_DOUBLE_EQ(-4.0, fs.positions().elevator_l);
    EXPECT_NEAR(0.9, fs.positions().slat_l, 1e-12);
    EXPECT_EQ(Ssm::NORMAL, fs.positions().slat_l_ssm);
}

TEST(FlightSurfaces, StateFollowsTheSensorsAndTheSurfacesKeepMoving) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.step(nullptr, 1);
    EXPECT_EQ(TerminalState::INITIALIZING, fs.state());
    const PlantSensors s = sensed(20.0, 0.0, 10.0);
    fs.step(&s, 2);
    EXPECT_EQ(TerminalState::NORMAL, fs.state());
    fs.step(nullptr, 3);
    fs.step(nullptr, 4);
    EXPECT_EQ(TerminalState::NORMAL, fs.state());  // two frames old: still fresh
    EXPECT_TRUE(fs.status().sensors_valid);
    fs.step(nullptr, 5);
    EXPECT_EQ(TerminalState::DEGRADED, fs.state());  // three frames: stale
    EXPECT_FALSE(fs.status().sensors_valid);
    // The last commands stand and the surfaces still move toward them (the Python's loop kept stepping on the
    // flight control computer's last data).
    EXPECT_DOUBLE_EQ(10.0, cmd_of(fs, SurfaceId::AILERON_L));
    EXPECT_NEAR(1.2 * 4, pos_of(fs, SurfaceId::AILERON_L), 1e-12);
    EXPECT_NEAR(0.1 * 4, pos_of(fs, SurfaceId::SLAT_L), 1e-12);
    fs.step(&s, 6);
    EXPECT_EQ(TerminalState::NORMAL, fs.state());
    // A copy whose roll is not NORMAL is no data: no sync, and stale after three frames.
    PlantSensors bad = sensed(-40.0, 0.0, 10.0);
    bad.roll_ssm = Ssm::FAILURE_WARNING;
    fs.step(&bad, 7);
    EXPECT_DOUBLE_EQ(10.0, cmd_of(fs, SurfaceId::AILERON_L));
    fs.step(&bad, 8);
    fs.step(&bad, 9);
    EXPECT_EQ(TerminalState::DEGRADED, fs.state());
}

TEST(FlightSurfaces, CommandsFollowTheSequenceRuleAndReportTheirOutcome) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.command(command(1, SurfaceCommand::SET_FLAPS, 15.0), 10);
    EXPECT_EQ(CmdStatus::ACCEPTED, fs.status().surface_cmd_status);
    EXPECT_EQ(15.0, fs.status().flap_cmd);
    fs.command(command(1, SurfaceCommand::SET_FLAPS, 30.0), 11);  // the same sequence: ignored
    EXPECT_EQ(15.0, fs.flap_cmd());
    fs.command(command(0, SurfaceCommand::SET_FLAPS, 30.0), 12);  // 0 is no command
    EXPECT_EQ(15.0, fs.flap_cmd());
    fs.command(command(2, SurfaceCommand::SET_SPEEDBRAKE, 50.0), 13);
    EXPECT_DOUBLE_EQ(30.0, cmd_of(fs, SurfaceId::SPEEDBRAKE));
    fs.command(command(3, SurfaceCommand::SET_RUDDER, -12.5), 14);
    EXPECT_DOUBLE_EQ(-12.5, cmd_of(fs, SurfaceId::RUDDER));
    fs.command(command(4, SurfaceCommand::SET_TRIM, 4.0, TrimAxis::YAW), 15);
    EXPECT_EQ(CmdStatus::ACCEPTED, fs.status().surface_cmd_status);
    EXPECT_DOUBLE_EQ(4.0, fs.status().trim_yaw);
    EXPECT_DOUBLE_EQ(0.0, fs.status().trim_pitch);
    fs.command(command(5, SurfaceCommand::SET_TRIM, 12.0, TrimAxis::PITCH), 16);
    EXPECT_DOUBLE_EQ(10.0, fs.status().trim_pitch);
    fs.command(command(6, SurfaceCommand::NONE), 17);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, fs.status().surface_cmd_status);
    EXPECT_EQ(15.0, fs.flap_cmd());  // nothing else changed
    fs.command(command(7, SurfaceCommand::SET_FLAPS, 10.0), 18);
    EXPECT_EQ(CmdStatus::ACCEPTED, fs.status().surface_cmd_status);
    EXPECT_EQ(5.0, fs.status().flap_cmd);
    // The flaps travel at 5 deg/s toward the detent, frame by frame.
    const PlantSensors s = sensed(0.0, 0.0, 2.0);
    for (std::uint32_t frame = 19; frame < 19 + 20; ++frame) {
        fs.step(&s, frame);
    }
    EXPECT_NEAR(2.0, fs.positions().flap_l, 1e-12);
    EXPECT_NEAR(2.0, fs.positions().flap_r, 1e-12);
}

TEST(FlightSurfaces, ModeCommandSelfTestAndReset) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    FsfModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::STANDBY;
    fs.command_mode(mode);
    EXPECT_EQ(TerminalState::STANDBY, fs.state());
    EXPECT_FALSE(fs.status().cmd_rejected);
    EXPECT_EQ(1, fs.status().last_cmd_seq);
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::INITIALIZING;  // not a commandable state
    fs.command_mode(mode);
    EXPECT_TRUE(fs.status().cmd_rejected);
    EXPECT_EQ(TerminalState::STANDBY, fs.state());
    fs.start_self_test();
    EXPECT_TRUE(fs.bit().in_progress);
    const PlantSensors s = sensed(0.0, 0.0, 2.0);
    for (std::uint32_t frame = 1; frame <= kSelfTestFrames + 1; ++frame) {
        fs.step(&s, frame);
    }
    EXPECT_FALSE(fs.bit().in_progress);
    EXPECT_FALSE(fs.bit().failed);
    fs.set_flaps(30.0);
    fs.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, fs.state());
    EXPECT_EQ(0.0, fs.flap_cmd());
    EXPECT_EQ(0.0, pos_of(fs, SurfaceId::AILERON_L));
    EXPECT_EQ(CmdStatus::NONE, fs.status().surface_cmd_status);
}

TEST(FlightSurfaces, OutputsEncode) {
    FlightSurfaces fs;
    ASSERT_EQ(Status::kOk, fs.init());
    fs.set_flaps(15.0);
    fs.set_speedbrake(100.0);
    const PlantSensors s = sensed(-30.0, 10.0, 12.0);
    for (std::uint32_t frame = 1; frame <= 300; ++frame) {
        fs.step(&s, frame);
    }
    FsfPositions::Words words{};
    ASSERT_EQ(Status::kOk, fs.positions().encode(words));
    FsfPositions back{};
    ASSERT_EQ(Status::kOk, FsfPositions::decode(words, back));
    EXPECT_NEAR(-15.0, back.aileron_l, 0.005);
    EXPECT_NEAR(15.0, back.aileron_r, 0.005);
    EXPECT_NEAR(-8.0, back.elevator_l, 0.005);
    EXPECT_NEAR(15.0, back.flap_l, 0.005);
    EXPECT_NEAR(20.0, back.slat_r, 0.005);
    EXPECT_NEAR(60.0, back.speedbrake, 0.005);
    EXPECT_EQ(Ssm::NORMAL, back.rudder_ssm);
    FsfStatus::Words status_words{};
    ASSERT_EQ(Status::kOk, fs.status().encode(status_words));
    FsfStatus st{};
    ASSERT_EQ(Status::kOk, FsfStatus::decode(status_words, st));
    EXPECT_EQ(TerminalState::NORMAL, st.state);
    EXPECT_EQ(15.0, st.flap_cmd);
    EXPECT_TRUE(st.sensors_valid);
    EXPECT_TRUE(st.slats_extended);
    EXPECT_TRUE(st.healthy);
}

}  // namespace
