// The environmental control terminal against ecsControl.py and its
// sub-components: the three threshold checks, the oxygen generator's climb and
// cap, the climate's copy of the reading, the manual controls, the pass per new
// reading with its freshness and state, the commands, the outputs.
#include <gtest/gtest.h>

#include <cstdint>

#include <fmofp/ecs/ecs_control.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::ecs;   // NOLINT: test
using namespace fmofp::icd;   // NOLINT: test

PlantCabin reading(std::uint8_t epoch, double temperature, double pressure, double air_quality) {
    PlantCabin c{};
    c.epoch = epoch;
    c.temperature = temperature;
    c.pressure = pressure;
    c.air_quality = air_quality;
    return c;
}

EcsCmd command(std::uint8_t seq, EcsCommand what, double value = 0.0) {
    EcsCmd c{};
    c.cmd_seq = seq;
    c.command = what;
    c.value = value;
    return c;
}

TEST(EcsControl, InitIsTheConstructor) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    EXPECT_EQ(TerminalState::INITIALIZING, ecs.state());
    EXPECT_FALSE(ecs.have_reading());
    EXPECT_EQ(21.0, ecs.oxygen_level());
    EXPECT_EQ(1.0, ecs.oxygen_rate());
    EXPECT_EQ(22.0, ecs.climate_temperature());
    EXPECT_EQ(50.0, ecs.humidity());
    EXPECT_EQ(0U, ecs.passes());
    EXPECT_FALSE(ecs.status().sensors_valid);
    EXPECT_FALSE(ecs.temperature_adjusting() || ecs.pressure_adjusting() || ecs.purification_active());
    EXPECT_EQ(CmdStatus::NONE, ecs.status().ecs_cmd_status);
    EXPECT_TRUE(ecs.status().healthy);
}

TEST(EcsControl, TheThreeChecksAtTheirThresholds) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    ecs.monitor(22.4, 101.7, 95.0);  // within 0.5 C, within 0.5 kPa, not under 95
    EXPECT_FALSE(ecs.temperature_adjusting());
    EXPECT_FALSE(ecs.pressure_adjusting());
    EXPECT_FALSE(ecs.purification_active());
    ecs.monitor(22.6, 100.7, 94.9);
    EXPECT_TRUE(ecs.temperature_adjusting());
    EXPECT_TRUE(ecs.pressure_adjusting());
    EXPECT_TRUE(ecs.purification_active());
    ecs.monitor(21.4, 101.3, 98.0);
    EXPECT_TRUE(ecs.temperature_adjusting());
    EXPECT_FALSE(ecs.pressure_adjusting());
    EXPECT_FALSE(ecs.purification_active());
    EXPECT_EQ(3U, ecs.passes());
}

TEST(EcsControl, OxygenClimbsATenthAPassAndCapsAtTwentyThree) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    for (int i = 1; i <= 19; ++i) {
        ecs.monitor(22.0, 101.3, 98.0);
        EXPECT_NEAR(21.0 + 0.1 * i, ecs.oxygen_level(), 1e-9) << i;
        EXPECT_LT(ecs.oxygen_level(), 23.0);
    }
    ecs.monitor(22.0, 101.3, 98.0);  // the twentieth: 23 to within the doubles' rounding, capped if over
    EXPECT_NEAR(23.0, ecs.oxygen_level(), 1e-9);
    ecs.monitor(22.0, 101.3, 98.0);  // the twenty-first is over 23 either way: capped
    EXPECT_EQ(23.0, ecs.oxygen_level());
    ecs.monitor(22.0, 101.3, 98.0);
    EXPECT_EQ(23.0, ecs.oxygen_level());
    ecs.set_oxygen_rate(1.5);  // adjust_generation_rate: reported, without effect on the climb
    ecs.monitor(22.0, 101.3, 98.0);
    EXPECT_EQ(23.0, ecs.oxygen_level());
    EXPECT_EQ(1.5, ecs.oxygen_rate());
}

TEST(EcsControl, TheClimateCopiesEachReadingAndTheControlsStand) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    ecs.monitor(23.7, 101.3, 98.0);
    EXPECT_EQ(23.7, ecs.climate_temperature());
    ecs.set_climate_temperature(30.0);  // ClimateControl.adjust_temperature by hand ...
    EXPECT_EQ(30.0, ecs.climate_temperature());
    ecs.monitor(23.9, 101.3, 98.0);     // ... until the next pass with a reading
    EXPECT_EQ(23.9, ecs.climate_temperature());
    ecs.set_humidity(45.5);
    EXPECT_EQ(45.5, ecs.humidity());
    ecs.monitor(24.0, 101.3, 98.0);
    EXPECT_EQ(45.5, ecs.humidity());  // nothing in a pass touches the humidity
}

TEST(EcsControl, AFrameRunsOnePassPerNewReadingAndFollowsTheFreshness) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    ecs.step(nullptr, 1);
    EXPECT_EQ(TerminalState::INITIALIZING, ecs.state());
    const PlantCabin first = reading(1, 22.8, 101.3, 98.0);
    ecs.step(&first, 2);
    EXPECT_EQ(TerminalState::NORMAL, ecs.state());
    EXPECT_TRUE(ecs.status().sensors_valid);
    EXPECT_EQ(1U, ecs.passes());
    EXPECT_TRUE(ecs.status().temperature_adjusting);
    EXPECT_NEAR(21.1, ecs.oxygen_level(), 1e-9);
    ecs.step(&first, 3);  // the same epoch again: no second pass
    EXPECT_EQ(1U, ecs.passes());
    const PlantCabin second = reading(2, 22.1, 101.3, 98.0);
    ecs.step(&second, 4);
    EXPECT_EQ(2U, ecs.passes());
    EXPECT_FALSE(ecs.status().temperature_adjusting);
    EXPECT_EQ(22.1, ecs.status().temperature);
    PlantCabin none{};  // epoch 0: no reading
    ecs.step(&none, 5);
    EXPECT_EQ(2U, ecs.passes());
    for (std::uint32_t frame = 6; frame < 4 + kCabinStaleFrames; ++frame) {
        ecs.step(nullptr, frame);
        EXPECT_EQ(TerminalState::NORMAL, ecs.state()) << frame;
    }
    ecs.step(nullptr, 4 + kCabinStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, ecs.state());
    EXPECT_FALSE(ecs.status().sensors_valid);
    EXPECT_EQ(22.1, ecs.status().temperature);  // the last reading stands
    const PlantCabin third = reading(3, 22.0, 101.3, 98.0);
    ecs.step(&third, 4 + kCabinStaleFrames + 1);
    EXPECT_EQ(TerminalState::NORMAL, ecs.state());
}

TEST(EcsControl, CommandsFollowTheSequenceRuleAndReportTheirOutcome) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    ecs.command(command(1, EcsCommand::SET_OXYGEN_RATE, 2.5), 10);
    EXPECT_EQ(CmdStatus::ACCEPTED, ecs.status().ecs_cmd_status);
    EXPECT_EQ(2.5, ecs.status().oxygen_rate);
    ecs.command(command(1, EcsCommand::SET_OXYGEN_RATE, 9.0), 11);  // the same sequence: ignored
    EXPECT_EQ(2.5, ecs.oxygen_rate());
    ecs.command(command(2, EcsCommand::SET_HUMIDITY, 40.0), 12);
    EXPECT_EQ(40.0, ecs.status().humidity);
    ecs.command(command(3, EcsCommand::SET_CLIMATE_TEMPERATURE, 19.5), 13);
    EXPECT_EQ(19.5, ecs.status().climate_temperature);
    ecs.command(command(4, EcsCommand::NONE), 14);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, ecs.status().ecs_cmd_status);
    EXPECT_EQ(40.0, ecs.humidity());
    EcsModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::STANDBY;
    ecs.command_mode(mode);
    EXPECT_EQ(TerminalState::STANDBY, ecs.state());
    ecs.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, ecs.state());
    EXPECT_EQ(1.0, ecs.oxygen_rate());
}

TEST(EcsControl, OutputsEncode) {
    EcsControl ecs;
    ASSERT_EQ(Status::kOk, ecs.init());
    const PlantCabin c = reading(7, 23.25, 100.5, 93.5);
    ecs.step(&c, 1);
    EcsStatus::Words words{};
    ASSERT_EQ(Status::kOk, ecs.status().encode(words));
    EcsStatus back{};
    ASSERT_EQ(Status::kOk, EcsStatus::decode(words, back));
    EXPECT_EQ(TerminalState::NORMAL, back.state);
    EXPECT_NEAR(23.25, back.temperature, 0.005);
    EXPECT_NEAR(100.5, back.pressure, 0.005);
    EXPECT_NEAR(93.5, back.air_quality, 0.005);
    EXPECT_NEAR(23.25, back.climate_temperature, 0.005);
    EXPECT_NEAR(50.0, back.humidity, 0.005);
    EXPECT_NEAR(21.1, back.oxygen_level, 0.005);
    EXPECT_NEAR(1.0, back.oxygen_rate, 0.005);
    EXPECT_EQ(1.0, back.passes);
    EXPECT_TRUE(back.sensors_valid && back.temperature_adjusting && back.pressure_adjusting && back.purification_active);
}

}  // namespace
