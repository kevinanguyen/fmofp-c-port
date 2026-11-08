// The power management terminal against PowerManagementSystem and its component
// classes: the batteries' charge and discharge arithmetic (and the depleted
// mid-draw case), the engine and APU starts, the emergency battery's critical
// load, the mission equipment batteries, the fan controller and heat rejection,
// the coolant loop's thermal mass and status thresholds, the HVAC's rate limit
// and drift, the 1 Hz bookkeeping over a reading (a surplus charges, a deficit
// discharges), the once-per-reading step with its freshness, and the commands.
#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>

#include <fmofp/power/power_management.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::power;  // NOLINT: test
using namespace fmofp::icd;    // NOLINT: test

constexpr double kDt = kDtHours;

PlantElectrical reading(std::uint8_t epoch, double generator_kw, double consumption_kw) {
    PlantElectrical e{};
    e.epoch = epoch;
    e.generator_output = generator_kw;
    e.total_power_consumption = consumption_kw;
    e.main_bus_voltage = 115.0;
    e.aux_bus_voltage = 27.0;
    e.generator_frequency = 400.0;
    e.power_factor = 0.98;
    return e;
}

PwrCmd command(std::uint8_t seq, PowerCommand what, double value = 0.0, EngineSelect engine = EngineSelect::ALL) {
    PwrCmd c{};
    c.cmd_seq = seq;
    c.command = what;
    c.value = value;
    c.engine = engine;
    return c;
}

TEST(Battery, DischargeAndChargeArithmetic) {
    Battery b(40.0, 24.0, 100.0);
    EXPECT_DOUBLE_EQ(40.0, b.capacity_remaining_ah());
    const double amps = 20.0 * 1000.0 / 24.0;  // a 20 kW deficit on the 24 V bus
    EXPECT_NEAR(0.2314814814814815, b.discharge(amps, kDt), 1e-12);
    EXPECT_NEAR(99.42129629629629, b.charge_pct(), 1e-9);
    EXPECT_DOUBLE_EQ(amps, b.load_amps());
    EXPECT_DOUBLE_EQ(0.0, b.discharge(0.0, kDt));
    EXPECT_DOUBLE_EQ(0.0, b.discharge(10.0, 0.0));
    b.set_online(false);
    EXPECT_DOUBLE_EQ(0.0, b.discharge(10.0, kDt));
    b.set_online(true);
    // Charging accepts only the headroom.
    EXPECT_NEAR(0.2314814814814815, b.charge(3600.0, kDt), 1e-12);
    EXPECT_DOUBLE_EQ(100.0, b.charge_pct());
    EXPECT_DOUBLE_EQ(0.0, b.charge(3600.0, kDt));
    EXPECT_DOUBLE_EQ(0.0, b.charge(-5.0, kDt));
}

TEST(Battery, DepletedMidDrawSuppliesWhatIsLeftAndDropsTheLoad) {
    Battery b(10.0, 24.0, 1.0);  // 0.1 Ah left
    EXPECT_NEAR(0.1, b.discharge(1000.0, 1.0), 1e-12);
    EXPECT_DOUBLE_EQ(0.0, b.charge_pct());
    EXPECT_TRUE(b.depleted());
    EXPECT_DOUBLE_EQ(0.0, b.load_amps());
    const Battery over(10.0, 24.0, 150.0);
    EXPECT_DOUBLE_EQ(100.0, over.charge_pct());
    const Battery under(10.0, 24.0, -3.0);
    EXPECT_DOUBLE_EQ(0.0, under.charge_pct());
}

TEST(MainBattery, EngineStartDrawsFiveSecondsAtThreeHundredAmps) {
    MainBattery m;
    EXPECT_TRUE(m.start_engine());
    EXPECT_NEAR(98.95833333333333, m.charge_pct(), 1e-9);  // 0.4167 Ah of 40
    // Under 20 % the start is refused and nothing is drawn.
    (void)m.supply_essential_loads(32.0 * 3600.0, kDt);  // 32 Ah in one second
    EXPECT_NEAR(18.95833333333333, m.charge_pct(), 1e-9);
    EXPECT_FALSE(m.start_engine());
    EXPECT_NEAR(18.95833333333333, m.charge_pct(), 1e-9);
}

TEST(ApuBattery, LightOffDrawsOnceAndTheRunningApuIsNotStartedAgain) {
    ApuBattery a;
    EXPECT_FALSE(a.apu_running());
    EXPECT_TRUE(a.start_apu());
    EXPECT_NEAR(97.77777777777777, a.charge_pct(), 1e-9);  // 0.3333 Ah of 15
    EXPECT_TRUE(a.start_apu());
    EXPECT_NEAR(97.77777777777777, a.charge_pct(), 1e-9);
    a.stop_apu();
    EXPECT_FALSE(a.apu_running());
    (void)a.assist_main_battery_start(12.75 * 3600.0, kDt);  // 12.75 Ah: down to 12.78 %
    EXPECT_FALSE(a.start_apu());
    EXPECT_FALSE(a.apu_running());
}

TEST(EmergencyBattery, SustainsTheCriticalLoadOnlyInEmergencyMode) {
    EmergencyBattery e;
    EXPECT_TRUE(e.sustain_critical_systems(kDt));
    EXPECT_DOUBLE_EQ(100.0, e.charge_pct());
    EXPECT_DOUBLE_EQ(90.0, e.estimated_endurance_minutes());
    e.activate_emergency_power();
    EXPECT_TRUE(e.sustain_critical_systems(kDt));
    EXPECT_NEAR(99.98148148148148, e.charge_pct(), 1e-9);  // 8 A for one second of 12 Ah
    EXPECT_DOUBLE_EQ(8.0, e.load_amps());
    e.deactivate_emergency_power();
    EXPECT_FALSE(e.emergency_mode_active());
    EXPECT_DOUBLE_EQ(0.0, e.load_amps());
    // Nearly empty, the load cannot be met.
    EmergencyBattery low;
    low.activate_emergency_power();
    (void)low.discharge(12.0 * 3600.0 * 0.9999, kDt);
    EXPECT_FALSE(low.sustain_critical_systems(kDt));
}

TEST(MissionEquipmentBattery, PowersItsEquipmentWhileTheLoadIsMet) {
    MissionEquipmentBattery b;
    EXPECT_TRUE(b.power_equipment(10.0, kDt));
    EXPECT_NEAR(99.9537037037037, b.charge_pct(), 1e-9);  // 0.00278 Ah of 6
    EXPECT_TRUE(b.powering_equipment());
    EXPECT_FALSE(b.power_equipment(0.0, kDt));
    EXPECT_FALSE(b.powering_equipment());
}

TEST(ActiveDissipationUnit, FanControllerAndHeatRejection) {
    ActiveDissipationUnit d;
    EXPECT_DOUBLE_EQ(10.0, d.fan_pct());
    d.auto_control(20.0, 25.0);
    EXPECT_DOUBLE_EQ(10.0, d.fan_pct());
    d.auto_control(27.5, 25.0);
    EXPECT_DOUBLE_EQ(55.0, d.fan_pct());
    d.auto_control(31.0, 25.0);
    EXPECT_DOUBLE_EQ(100.0, d.fan_pct());
    EXPECT_DOUBLE_EQ(600.0, d.reject_heat(30.0, 20.0));
    EXPECT_DOUBLE_EQ(600.0, d.last_rejected_watts());
    EXPECT_DOUBLE_EQ(0.0, d.reject_heat(15.0, 20.0));
    d.set_fan_speed(3.0);
    EXPECT_DOUBLE_EQ(10.0, d.fan_pct());  // never under the minimum while active
    d.deactivate();
    EXPECT_FALSE(d.active());
    EXPECT_DOUBLE_EQ(0.0, d.fan_pct());
    EXPECT_DOUBLE_EQ(0.0, d.reject_heat(50.0, 20.0));
    d.auto_control(40.0, 25.0);
    EXPECT_DOUBLE_EQ(0.0, d.fan_pct());  // no control while inactive
    d.set_fan_speed(50.0);
    EXPECT_DOUBLE_EQ(50.0, d.fan_pct());  // allowed down to 0 while inactive
    d.activate();
    EXPECT_DOUBLE_EQ(50.0, d.fan_pct());
    d.deactivate();
    d.activate();
    EXPECT_DOUBLE_EQ(10.0, d.fan_pct());
}

TEST(CoolingSystem, OneSecondOfAvionicsHeatAndTheStatusThresholds) {
    CoolingSystem c;
    c.set_heat_load(1200.0);
    c.update(kDt);
    EXPECT_NEAR(20.0 + 1200.0 * kDt * 0.02, c.coolant_temp_c(), 1e-12);  // at ambient the minimum fan rejects nothing
    EXPECT_DOUBLE_EQ(10.0, c.dissipation_unit().fan_pct());
    EXPECT_EQ(ThermalStatus::OK, c.thermal_status());
    c.set_heat_load(-50.0);
    EXPECT_DOUBLE_EQ(0.0, c.heat_load_w());
    c.update(kDt);
    EXPECT_GE(c.coolant_temp_c(), 20.0);  // never below ambient
    // A huge load: WARNING from 55 C, CRITICAL from 70 C, the fan at full speed above 30 C.
    c.set_heat_load(1.0e6);
    int seconds = 0;
    while (c.thermal_status() == ThermalStatus::OK && seconds < 100) {
        c.update(kDt);
        ++seconds;
    }
    EXPECT_EQ(ThermalStatus::WARNING, c.thermal_status());
    EXPECT_GE(c.coolant_temp_c(), 55.0);
    EXPECT_LT(c.coolant_temp_c(), 70.0);
    while (c.thermal_status() == ThermalStatus::WARNING && seconds < 100) {
        c.update(kDt);
        ++seconds;
    }
    EXPECT_EQ(ThermalStatus::CRITICAL, c.thermal_status());
    EXPECT_DOUBLE_EQ(100.0, c.dissipation_unit().fan_pct());
    EXPECT_LT(seconds, 20);
}

TEST(HvacSystem, MovesTowardTheSetpointAtTheAirflowRateAndDriftsWhenOff) {
    HvacSystem h;
    h.update(kDt);
    EXPECT_DOUBLE_EQ(22.0, h.cabin_temp_c());
    EXPECT_TRUE(h.at_setpoint());
    h.set_temperature(26.0);
    EXPECT_FALSE(h.at_setpoint());
    h.update(kDt);
    EXPECT_NEAR(22.0 + 50.0 * 0.15 * kDt, h.cabin_temp_c(), 1e-12);
    h.set_temperature(35.0);
    EXPECT_DOUBLE_EQ(30.0, h.setpoint_c());
    h.set_temperature(-5.0);
    EXPECT_DOUBLE_EQ(10.0, h.setpoint_c());
    h.set_airflow(150.0);
    EXPECT_DOUBLE_EQ(100.0, h.airflow_pct());
    h.set_airflow(-1.0);
    EXPECT_DOUBLE_EQ(0.0, h.airflow_pct());
    // No airflow: the cabin drifts toward the 15 C ambient, powered or not.
    const double before = h.cabin_temp_c();
    h.update(kDt);
    EXPECT_NEAR(before + (15.0 - before) * (kDt * 2.0), h.cabin_temp_c(), 1e-12);
    h.set_airflow(50.0);
    h.power_off();
    EXPECT_FALSE(h.powered());
    const double off = h.cabin_temp_c();
    h.update(kDt);
    EXPECT_NEAR(off + (15.0 - off) * (kDt * 2.0), h.cabin_temp_c(), 1e-12);
    h.power_on();
    EXPECT_TRUE(h.powered());
}

TEST(PowerManagement, TheBalanceChargesOrDischargesTheMainBattery) {
    PowerManagement pm;
    ASSERT_EQ(Status::kOk, pm.init());
    EXPECT_EQ(TerminalState::INITIALIZING, pm.state());
    EXPECT_FALSE(pm.status().electrical_valid);
    EXPECT_FALSE(pm.status().generator_online);
    EXPECT_TRUE(pm.status().healthy);
    pm.update(reading(1, 240.0, 190.0));  // +50 kW: both batteries full, nothing accepted
    EXPECT_DOUBLE_EQ(100.0, pm.main_battery().charge_pct());
    EXPECT_DOUBLE_EQ(100.0, pm.apu_battery().charge_pct());
    EXPECT_TRUE(pm.status().generator_online);
    EXPECT_DOUBLE_EQ(50.0, pm.status().power_balance);
    EXPECT_DOUBLE_EQ(190.0 * 6.0, pm.status().heat_load);
    EXPECT_DOUBLE_EQ(115.0, pm.status().main_bus_voltage);
    EXPECT_DOUBLE_EQ(27.0, pm.status().aux_bus_voltage);
    EXPECT_DOUBLE_EQ(0.98, pm.status().power_factor);
    pm.update(reading(2, 200.0, 220.0));  // -20 kW: 833 A for one second off the main battery
    EXPECT_NEAR(99.42129629629629, pm.main_battery().charge_pct(), 1e-9);
    EXPECT_NEAR(20.0 * 1000.0 / 24.0, pm.main_battery().load_amps(), 1e-9);
    EXPECT_DOUBLE_EQ(-20.0, pm.status().power_balance);
    EXPECT_DOUBLE_EQ(100.0, pm.apu_battery().charge_pct());
    pm.update(reading(3, 250.0, 180.0));  // +70 kW: the main battery takes only its headroom back
    EXPECT_DOUBLE_EQ(100.0, pm.main_battery().charge_pct());
    EXPECT_DOUBLE_EQ(100.0, pm.status().main_battery_charge);
    EXPECT_DOUBLE_EQ(100.0, pm.emergency_battery().charge_pct());  // untouched without the emergency mode
    EXPECT_GT(pm.cooling().coolant_temp_c(), 20.0);               // three seconds of avionics heat
    EXPECT_EQ(ThermalStatus::OK, pm.status().thermal_status);
    EXPECT_DOUBLE_EQ(10.0, pm.status().fan_pct);
    EXPECT_DOUBLE_EQ(22.0, pm.status().cabin_temp);
    EXPECT_TRUE(pm.status().hvac_at_setpoint);
    pm.update(reading(4, 0.0, 200.0));  // the generator gone: the whole consumption off the main battery
    EXPECT_FALSE(pm.status().generator_online);
    EXPECT_NEAR(100.0 - (200.0 * 1000.0 / 24.0 * kDt / 40.0) * 100.0, pm.main_battery().charge_pct(), 1e-9);
}

TEST(PowerManagement, StepRunsTheBookkeepingOncePerReadingAndTracksFreshness) {
    PowerManagement pm;
    ASSERT_EQ(Status::kOk, pm.init());
    pm.step(nullptr, 1);
    EXPECT_EQ(TerminalState::INITIALIZING, pm.state());
    const PlantElectrical none{};  // epoch 0: a plant without the model
    pm.step(&none, 2);
    EXPECT_EQ(TerminalState::INITIALIZING, pm.state());
    EXPECT_FALSE(pm.updated());
    const PlantElectrical deficit = reading(1, 200.0, 220.0);
    pm.step(&deficit, 3);
    EXPECT_EQ(TerminalState::NORMAL, pm.state());
    EXPECT_TRUE(pm.status().electrical_valid);
    EXPECT_TRUE(pm.updated());
    EXPECT_NEAR(99.42129629629629, pm.main_battery().charge_pct(), 1e-9);
    pm.step(&deficit, 4);  // the same epoch again (the relay repeats the words): not applied twice
    EXPECT_NEAR(99.42129629629629, pm.main_battery().charge_pct(), 1e-9);
    pm.step(nullptr, 4 + kElectricalStaleFrames);
    EXPECT_EQ(TerminalState::DEGRADED, pm.state());
    EXPECT_FALSE(pm.status().electrical_valid);
    EXPECT_NEAR(99.42129629629629, pm.status().main_battery_charge, 1e-9);  // the last known values stay
    const PlantElectrical next = reading(2, 200.0, 220.0);
    pm.step(&next, 4 + kElectricalStaleFrames + 1);
    EXPECT_EQ(TerminalState::NORMAL, pm.state());
    EXPECT_NEAR(98.84259259259258, pm.main_battery().charge_pct(), 1e-8);
    pm.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, pm.state());
    EXPECT_DOUBLE_EQ(100.0, pm.main_battery().charge_pct());
}

TEST(PowerManagement, CommandsReachTheComponentsAndReportTheirOutcome) {
    PowerManagement pm;
    ASSERT_EQ(Status::kOk, pm.init());
    EXPECT_EQ(CmdStatus::NONE, pm.status().power_cmd_status);
    pm.command(command(1, PowerCommand::SET_GENERATOR_OUTPUT, -5.0), 10);
    EXPECT_EQ(CmdStatus::ACCEPTED, pm.status().power_cmd_status);
    EXPECT_TRUE(pm.gen_cmd().override);
    EXPECT_DOUBLE_EQ(0.0, pm.gen_cmd().generator_output);  // max(0, output)
    EXPECT_EQ(1U, pm.gen_cmd().sequence);
    pm.command(command(2, PowerCommand::SET_GENERATOR_OUTPUT, 150.0), 11);
    EXPECT_DOUBLE_EQ(150.0, pm.gen_cmd().generator_output);
    pm.command(command(2, PowerCommand::GENERATOR_AUTO), 12);  // a repeated cmd_seq is ignored
    EXPECT_TRUE(pm.gen_cmd().override);
    pm.command(command(3, PowerCommand::GENERATOR_AUTO), 13);
    EXPECT_FALSE(pm.gen_cmd().override);
    EXPECT_EQ(3U, pm.gen_cmd().sequence);
    pm.command(command(4, PowerCommand::EMERGENCY_POWER_ON), 14);
    EXPECT_TRUE(pm.status().emergency_mode_active);
    pm.update(reading(1, 240.0, 190.0));
    EXPECT_NEAR(99.98148148148148, pm.emergency_battery().charge_pct(), 1e-9);
    pm.command(command(5, PowerCommand::EMERGENCY_POWER_OFF), 15);
    EXPECT_FALSE(pm.status().emergency_mode_active);
    pm.command(command(6, PowerCommand::APU_START), 16);
    EXPECT_EQ(CmdStatus::ACCEPTED, pm.status().power_cmd_status);
    EXPECT_TRUE(pm.status().apu_running);
    EXPECT_NEAR(97.77777777777777, pm.status().apu_battery_charge, 1e-9);
    pm.command(command(7, PowerCommand::APU_STOP), 17);
    EXPECT_FALSE(pm.status().apu_running);
    pm.command(command(8, PowerCommand::ENGINE_START, 0.0, EngineSelect::ALL), 18);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, pm.status().power_cmd_status);
    EXPECT_DOUBLE_EQ(100.0, pm.main_battery().charge_pct());
    pm.command(command(9, PowerCommand::ENGINE_START, 0.0, EngineSelect::ENGINE_2), 19);
    EXPECT_EQ(CmdStatus::ACCEPTED, pm.status().power_cmd_status);
    EXPECT_NEAR(98.95833333333333, pm.main_battery().charge_pct(), 1e-9);
    pm.command(command(10, PowerCommand::HVAC_SETPOINT, 35.0), 20);
    EXPECT_DOUBLE_EQ(30.0, pm.hvac().setpoint_c());
    EXPECT_FALSE(pm.status().hvac_at_setpoint);
    pm.command(command(11, PowerCommand::HVAC_AIRFLOW, -10.0), 21);
    EXPECT_DOUBLE_EQ(0.0, pm.hvac().airflow_pct());
    pm.command(command(12, PowerCommand::HVAC_POWER_OFF), 22);
    EXPECT_FALSE(pm.status().hvac_powered);
    pm.command(command(13, PowerCommand::HVAC_POWER_ON), 23);
    EXPECT_TRUE(pm.status().hvac_powered);
    pm.command(command(14, PowerCommand::DISSIPATION_OFF), 24);
    EXPECT_FALSE(pm.status().dissipation_active);
    EXPECT_DOUBLE_EQ(0.0, pm.status().fan_pct);
    pm.command(command(15, PowerCommand::DISSIPATION_ON), 25);
    EXPECT_TRUE(pm.status().dissipation_active);
    EXPECT_DOUBLE_EQ(10.0, pm.status().fan_pct);
    pm.command(command(16, PowerCommand::NONE), 26);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, pm.status().power_cmd_status);
    EXPECT_TRUE(pm.power_equipment(0, 10.0));
    EXPECT_FALSE(pm.power_equipment(kEquipmentCount, 10.0));
    EXPECT_NEAR(99.9537037037037, pm.equipment(0).charge_pct(), 1e-9);
    EXPECT_DOUBLE_EQ(100.0, pm.equipment(1).charge_pct());
}

TEST(PowerManagement, StartsFailWhenTheBatteriesAreLow) {
    PowerManagement pm;
    ASSERT_EQ(Status::kOk, pm.init());
    // The generator gone under a 600 kW load: 6.9 Ah a second empties the main battery within six seconds.
    for (std::uint8_t epoch = 1; epoch <= 15; ++epoch) {
        pm.update(reading(epoch, 0.0, 600.0));
    }
    EXPECT_TRUE(pm.main_battery().depleted());
    EXPECT_DOUBLE_EQ(0.0, pm.main_battery().load_amps());  // depleted mid-draw: the load reads 0
    EXPECT_DOUBLE_EQ(0.0, pm.status().main_battery_charge);
    pm.command(command(1, PowerCommand::ENGINE_START, 0.0, EngineSelect::ENGINE_1), 1);
    EXPECT_EQ(CmdStatus::FAILED, pm.status().power_cmd_status);
    // The APU battery: thirty-nine light-offs take it under 15 %; the fortieth fails.
    for (int n = 0; n < 39; ++n) {
        pm.command(command(static_cast<std::uint8_t>(2 + 2 * n), PowerCommand::APU_START), 2);
        EXPECT_EQ(CmdStatus::ACCEPTED, pm.status().power_cmd_status);
        pm.command(command(static_cast<std::uint8_t>(3 + 2 * n), PowerCommand::APU_STOP), 3);
    }
    EXPECT_NEAR(100.0 - 39.0 * (150.0 * 8.0 / 3600.0 / 15.0) * 100.0, pm.apu_battery().charge_pct(), 1e-8);
    pm.command(command(90, PowerCommand::APU_START), 4);
    EXPECT_EQ(CmdStatus::FAILED, pm.status().power_cmd_status);
    EXPECT_FALSE(pm.status().apu_running);
}

TEST(PowerManagement, ModeCommandsFollowTheSharedRules) {
    PowerManagement pm;
    ASSERT_EQ(Status::kOk, pm.init());
    PwrModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::MAINTENANCE;
    pm.command_mode(mode);
    EXPECT_EQ(TerminalState::MAINTENANCE, pm.state());
    EXPECT_FALSE(pm.status().cmd_rejected);
    EXPECT_EQ(1U, pm.status().last_cmd_seq);
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::FAILURE;
    pm.command_mode(mode);
    EXPECT_TRUE(pm.status().cmd_rejected);
    EXPECT_EQ(TerminalState::MAINTENANCE, pm.state());
    pm.start_self_test();
    EXPECT_TRUE(pm.bit().in_progress);
    for (std::uint32_t frame = 1; frame <= kSelfTestFrames + 2; ++frame) {
        pm.step(nullptr, frame);
    }
    EXPECT_FALSE(pm.bit().in_progress);
}

}  // namespace
