// The crew alerting terminal against eicas.py's alert rules: each threshold on
// both sides, the order of the else-if chains, the defaults while nothing is
// heard, the inputs gathered from the bus with their freshness, the commands
// and the outputs.
#include <gtest/gtest.h>

#include <cstdint>
#include <string>

#include <fmofp/cas/crew_alerting.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::cas;  // NOLINT: test
using namespace fmofp::icd;  // NOLINT: test

bool has(const AlertSet& set, Alert alert) { return set[static_cast<std::size_t>(alert)]; }

// Every input valid and inside its limits: no alert but HYD C's (no system behind it, never valid here).
AlertInputs nominal() {
    AlertInputs in{};
    in.thrust_pct = 70.0;
    in.oil_press_valid = in.oil_temp_valid = in.vib_valid = true;
    in.oil_psi = 60.0;
    in.oil_temp_c = 95.0;
    in.vib = 0.3;
    in.fuel_total_valid = in.fuel_balance_valid = true;
    in.fuel_total_kg = 6000.0;
    in.fuel_balance_kg = 0.0;
    in.hyd_valid = {true, true, true};
    in.hyd_psi = {3000.0, 3000.0, 3000.0};
    in.gen_1_valid = in.gen_2_valid = in.main_bus_valid = true;
    in.main_bus_v = 115.0;
    return in;
}

unsigned count(const AlertSet& set) {
    unsigned n = 0;
    for (const bool b : set) {
        n += b ? 1U : 0U;
    }
    return n;
}

TEST(CrewAlerting, NominalInputsRaiseNothing) {
    EXPECT_EQ(0U, count(evaluate(nominal())));
}

TEST(CrewAlerting, TheDefaultsReportEveryUnmeasuredFieldUnknown) {
    // eicas.py's starting state on the bus: only the thrust (and with it the EGT model) is given.
    const AlertSet set = evaluate(AlertInputs{});
    for (const Alert a : {Alert::kEngOilPressUnknown, Alert::kEngOilTempUnknown, Alert::kEngVibUnknown,
                          Alert::kFuelQtyUnknown, Alert::kFuelBalanceUnknown, Alert::kHydAUnknown, Alert::kHydBUnknown,
                          Alert::kHydCUnknown, Alert::kElecGen1Unknown, Alert::kElecGen2Unknown,
                          Alert::kElecBusVoltsUnknown}) {
        EXPECT_TRUE(has(set, a)) << name_of(a);
    }
    EXPECT_EQ(11U, count(set));
}

TEST(CrewAlerting, TheEgtIsTheThrustModel) {
    AlertInputs in = nominal();
    in.thrust_pct = 100.0;  // 350 + 450 = 800: not above 800, above 750
    AlertSet set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kEngEgtCaution));
    EXPECT_FALSE(has(set, Alert::kEngEgtHigh));
    EXPECT_TRUE(has(set, Alert::kEngMaxContinuousThrust));
    in.thrust_pct = 0.7 * 100.0;  // NORMAL: 665
    EXPECT_EQ(0U, count(evaluate(in)));
    in.thrust_pct = 0.9 * 100.0;  // TRAINING: 755
    set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kEngEgtCaution));
    EXPECT_FALSE(has(set, Alert::kEngMaxContinuousThrust));
    in.thrust_pct = 101.0;  // 804.5
    EXPECT_TRUE(has(evaluate(in), Alert::kEngEgtHigh));
    in.egt_valid = false;
    set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kEngEgtUnknown));
    EXPECT_FALSE(has(set, Alert::kEngEgtHigh));
}

TEST(CrewAlerting, EngineThresholds) {
    AlertInputs in = nominal();
    in.oil_psi = 50.0;
    EXPECT_FALSE(has(evaluate(in), Alert::kEngOilPressLow));
    in.oil_psi = 49.9;
    EXPECT_TRUE(has(evaluate(in), Alert::kEngOilPressLow));
    in.oil_psi = 39.9;
    AlertSet set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kEngOilPressLo));
    EXPECT_FALSE(has(set, Alert::kEngOilPressLow));
    in = nominal();
    in.oil_temp_c = 130.0;
    EXPECT_FALSE(has(evaluate(in), Alert::kEngOilTempHigh));
    in.oil_temp_c = 130.1;
    EXPECT_TRUE(has(evaluate(in), Alert::kEngOilTempHigh));
    in.vib = 0.8;
    EXPECT_FALSE(has(evaluate(in), Alert::kEngVibrationHigh));
    in.vib = 0.81;
    EXPECT_TRUE(has(evaluate(in), Alert::kEngVibrationHigh));
}

TEST(CrewAlerting, FuelHydraulicAndElectricalThresholds) {
    AlertInputs in = nominal();
    in.fuel_total_kg = 1000.0;
    EXPECT_EQ(0U, count(evaluate(in)));
    in.fuel_total_kg = 999.0;
    EXPECT_TRUE(has(evaluate(in), Alert::kFuelQuantityCaution));
    in.fuel_total_kg = 499.0;
    AlertSet set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kFuelQuantityLow));
    EXPECT_FALSE(has(set, Alert::kFuelQuantityCaution));
    in = nominal();
    in.fuel_balance_kg = -200.0;
    EXPECT_EQ(0U, count(evaluate(in)));
    in.fuel_balance_kg = -201.0;
    EXPECT_TRUE(has(evaluate(in), Alert::kFuelImbalance));

    in = nominal();
    in.hyd_psi = {2500.0, 2499.0, 1999.0};
    set = evaluate(in);
    EXPECT_FALSE(has(set, Alert::kHydAReduced));
    EXPECT_TRUE(has(set, Alert::kHydBReduced));
    EXPECT_TRUE(has(set, Alert::kHydCLow));
    EXPECT_FALSE(has(set, Alert::kHydCReduced));

    in = nominal();
    in.gen_1_ok = false;
    in.main_bus_v = 99.0;
    set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kElecGen1Fault));
    EXPECT_FALSE(has(set, Alert::kElecGen2Fault));
    EXPECT_TRUE(has(set, Alert::kElecMainBusLo));
}

TEST(CrewAlerting, FlightControlRows) {
    AlertInputs in = nominal();
    in.gcas_pullup = in.gcas_sink_rate = in.gcas_terrain = in.gcas_alt_low = true;
    in.perf_exceed = {true, false, true, false, true};
    const AlertSet set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kFcsPullUp));
    EXPECT_FALSE(has(set, Alert::kFcsSinkRate));  // the GCAS reports PULL UP or SINK RATE, not both
    EXPECT_TRUE(has(set, Alert::kFcsTerrain));
    EXPECT_TRUE(has(set, Alert::kFcsAltLow));
    EXPECT_TRUE(has(set, Alert::kPerfGForce));
    EXPECT_FALSE(has(set, Alert::kPerfAngleOfAttack));
    EXPECT_TRUE(has(set, Alert::kPerfRoll));
    EXPECT_TRUE(has(set, Alert::kPerfVerticalSpeed));
}

TEST(CrewAlerting, DefensiveSensorAndWeatherRows) {
    AlertInputs in = nominal();
    in.rwr_hostile = 2;
    in.rwr_high_priority = 1;
    in.chaff_remaining = 10;
    in.flares_remaining = 0;
    in.ecm_active = true;
    in.sensor_health = SensorHealth::DEGRADED;
    in.fused_hostile = 3;
    in.wx_microburst = true;
    in.wx_windshear = ShearSeverity::SEVERE;
    in.wx_turbulence = TurbulenceCategory::LIGHT;
    AlertSet set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kRwrHighPriThreats));
    EXPECT_FALSE(has(set, Alert::kRwrThreatContacts));
    EXPECT_TRUE(has(set, Alert::kCmdsChaffLow));
    EXPECT_TRUE(has(set, Alert::kCmdsFlaresDepleted));
    EXPECT_FALSE(has(set, Alert::kCmdsFlaresLow));
    EXPECT_TRUE(has(set, Alert::kEwEcmActive));
    EXPECT_TRUE(has(set, Alert::kSensorDegradedMode));
    EXPECT_TRUE(has(set, Alert::kFusionHostileTracks));
    EXPECT_TRUE(has(set, Alert::kWxMicroburst));
    EXPECT_FALSE(has(set, Alert::kWxSevereWindshear));  // the microburst wins the chain
    EXPECT_TRUE(has(set, Alert::kWxLightTurbulence));

    in.rwr_high_priority = 0;
    in.chaff_remaining = 11;
    in.fused_hostile = 2;
    in.sensor_health = SensorHealth::FAULT;
    in.wx_microburst = false;
    in.wx_windshear = ShearSeverity::LOW;
    in.wx_turbulence = TurbulenceCategory::EXTREME;
    set = evaluate(in);
    EXPECT_TRUE(has(set, Alert::kRwrThreatContacts));
    EXPECT_FALSE(has(set, Alert::kCmdsChaffLow));
    EXPECT_TRUE(has(set, Alert::kFusionHostileTrack));
    EXPECT_TRUE(has(set, Alert::kSensorSystemFault));
    EXPECT_TRUE(has(set, Alert::kWxWindshearAhead));
    EXPECT_TRUE(has(set, Alert::kWxExtremeTurbulence));
}

TEST(CrewAlerting, TheTableNamesAndGradesEveryAlert) {
    EXPECT_EQ(59U, kAlertCount);
    EXPECT_EQ(std::string("eng_egt_high"), name_of(Alert::kEngEgtHigh));
    EXPECT_EQ(std::string("wx_light_turbulence"), name_of(Alert::kWxLightTurbulence));
    EXPECT_EQ(Severity::kWarning, severity_of(Alert::kFcsTerrain));
    EXPECT_EQ(Severity::kCaution, severity_of(Alert::kFcsAltLow));
    EXPECT_EQ(Severity::kAdvisory, severity_of(Alert::kEwEcmActive));
    EXPECT_EQ(std::string(""), name_of(Alert::kCount));
}

TEST(CrewAlerting, TheProfilePowerByFlightMode) {
    EXPECT_EQ(0.7, profile_engine_power(nullptr));
    FmsStatus fms{};
    const std::pair<FmsFlightMode, double> cases[] = {{FmsFlightMode::NORMAL, 0.7}, {FmsFlightMode::COMBAT, 1.0},
                                                      {FmsFlightMode::STEALTH, 0.6}, {FmsFlightMode::TRAINING, 0.9},
                                                      {FmsFlightMode::EMERGENCY, 1.0}};
    for (const auto& c : cases) {
        fms.flight_mode = c.first;
        EXPECT_EQ(c.second, profile_engine_power(&fms));
    }
}

// --- the terminal: inputs from the bus ------------------------------------------------------------

struct Bus {
    FmsStatus fms{};
    EngEngineStatus engine{};
    EngFuelStatus fuel{};
    HydStatus hyd{};
    PwrStatus power{};
    DefStatus def{};
    DefRwrContacts contacts{};
    RdrFusedTracks fused{};
    SnsStatus sensor{};
    FcsGcasAlerts gcas{};

    Bus() {
        engine.engine_1_ssm = Ssm::NORMAL;
        engine.oil_pressure_1 = 45.0;
        engine.oil_temperature_1 = 90.0;
        engine.vibration_1 = 0.2;
        fuel.main_left = 3000.0;
        fuel.main_right = 2700.0;
        fuel.total = 6000.0;
        hyd.pressures_valid = true;
        hyd.primary_psi = 2400.0;
        hyd.backup_psi = 3000.0;
        power.electrical_valid = true;
        power.generator_online = true;
        power.main_bus_voltage = 115.0;
        def.chaff_remaining = 60;
        def.flares_remaining = 30;
        contacts.contact_count = 3;
        contacts.contact[0].hostile = true;
        contacts.contact[0].priority = 1;
        contacts.contact[1].hostile = true;
        contacts.contact[1].priority = 2;
        contacts.contact[2].hostile = false;
        contacts.contact[2].priority = 1;
        fused.track_count = 2;
        fused.track[0].threat = Threat::HOSTILE;
        fused.track[1].threat = Threat::FRIENDLY;
        fused.track[5].threat = Threat::HOSTILE;  // beyond the count: not a track
        gcas.alt_low = true;
        gcas.altitude = 1500.0;
    }

    Received all() {
        Received r{};
        r.fms = &fms;
        r.engine = &engine;
        r.fuel = &fuel;
        r.hydraulics = &hyd;
        r.power = &power;
        r.defensive = &def;
        r.contacts = &contacts;
        r.fused = &fused;
        r.sensor = &sensor;
        r.gcas = &gcas;
        return r;
    }
};

TEST(CrewAlertingTerminal, StartsInitialisingWithNothingComputed) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    EXPECT_EQ(TerminalState::INITIALIZING, cas.state());
    EXPECT_FALSE(cas.status().computed);
    EXPECT_EQ(0U, cas.status().warning_count);
}

TEST(CrewAlertingTerminal, GathersTheBusIntoTheRules) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    Bus bus;
    cas.step(bus.all(), 1);
    EXPECT_EQ(TerminalState::NORMAL, cas.state());
    const AlertInputs& in = cas.inputs();
    EXPECT_EQ(70.0, in.thrust_pct);
    EXPECT_TRUE(in.oil_press_valid);
    EXPECT_EQ(300.0, in.fuel_balance_kg);
    EXPECT_EQ(2400.0, in.hyd_psi[0]);
    EXPECT_FALSE(in.hyd_valid[2]);
    EXPECT_EQ(2U, in.rwr_hostile);
    EXPECT_EQ(1U, in.rwr_high_priority);
    EXPECT_EQ(1U, in.fused_hostile);

    const CasAlerts& st = cas.status();
    EXPECT_TRUE(st.computed);
    EXPECT_TRUE(st.eng_oil_press_low);
    EXPECT_TRUE(st.fuel_imbalance);
    EXPECT_TRUE(st.hyd_a_reduced);
    EXPECT_TRUE(st.hyd_c_unknown);
    EXPECT_TRUE(st.fcs_alt_low);
    EXPECT_TRUE(st.rwr_high_pri_threats);
    EXPECT_TRUE(st.fusion_hostile_track);
    EXPECT_EQ(2U, st.rwr_hostile);
    EXPECT_EQ(1U, st.rwr_high_priority);
    EXPECT_EQ(1500.0, st.gcas_altitude);
    // rwr_high_pri_threats; oil low, imbalance, HYD A reduced, HYD C unknown, ALT LOW, fusion track.
    EXPECT_EQ(1U, st.warning_count);
    EXPECT_EQ(6U, st.caution_count);
    EXPECT_EQ(0U, st.advisory_count);
}

TEST(CrewAlertingTerminal, AnInputGoesUnheardAfterTwoSeconds) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    Bus bus;
    cas.step(bus.all(), 1);
    cas.step(Received{}, 100);  // 99 frames on: still heard
    EXPECT_TRUE(cas.inputs().fuel_total_valid);
    EXPECT_EQ(TerminalState::NORMAL, cas.state());
    cas.step(Received{}, 101);  // 100 frames on: not
    EXPECT_FALSE(cas.inputs().fuel_total_valid);
    EXPECT_TRUE(cas.status().fuel_qty_unknown);
    EXPECT_EQ(60U, cas.inputs().chaff_remaining);  // the EICAS's defaults with the defensive service silent
    EXPECT_EQ(TerminalState::DEGRADED, cas.state());
    cas.step(bus.all(), 102);
    EXPECT_EQ(TerminalState::NORMAL, cas.state());
}

TEST(CrewAlertingTerminal, TheContactsCountOnlyWithTheDefensiveStatus) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    Bus bus;
    Received r = bus.all();
    r.defensive = nullptr;
    cas.step(r, 1);
    EXPECT_EQ(0U, cas.inputs().rwr_hostile);
    EXPECT_FALSE(cas.status().rwr_high_pri_threats);
}

TEST(CrewAlertingTerminal, AnEngineNotNormalIsUnknown) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    Bus bus;
    bus.engine.engine_1_ssm = Ssm::NO_COMPUTED_DATA;
    cas.step(bus.all(), 1);
    EXPECT_TRUE(cas.status().eng_oil_press_unknown);
    EXPECT_TRUE(cas.status().eng_vib_unknown);
}

TEST(CrewAlertingTerminal, TheModeCommandAndItsSequence) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    CasModeCmd cmd{};
    cmd.requested_state = TerminalState::STANDBY;
    cmd.cmd_seq = 5;
    cas.command_mode(cmd);
    EXPECT_EQ(TerminalState::STANDBY, cas.state());
    EXPECT_EQ(5U, cas.status().last_cmd_seq);
    cmd.requested_state = TerminalState::FAILURE;
    cas.command_mode(cmd);  // the same number: not a new command
    EXPECT_EQ(TerminalState::STANDBY, cas.state());
    cmd.cmd_seq = 6;
    cas.command_mode(cmd);
    EXPECT_TRUE(cas.status().cmd_rejected);
    EXPECT_EQ(TerminalState::STANDBY, cas.state());
}

TEST(CrewAlertingTerminal, TheSelfTestRunsTenFramesAndResetStartsOver) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    cas.start_self_test();
    EXPECT_TRUE(cas.bit().in_progress);
    cas.step(Received{}, 1);
    cas.step(Received{}, 10);
    EXPECT_TRUE(cas.bit().in_progress);
    cas.step(Received{}, 11);
    EXPECT_FALSE(cas.bit().in_progress);
    Bus bus;
    cas.step(bus.all(), 12);
    cas.reset();
    EXPECT_EQ(TerminalState::INITIALIZING, cas.state());
    EXPECT_FALSE(cas.status().computed);
}

TEST(CrewAlertingTerminal, TheStatusEncodes) {
    CrewAlerting cas;
    ASSERT_EQ(Status::kOk, cas.init());
    Bus bus;
    cas.step(bus.all(), 1);
    CasAlerts::Words w{};
    ASSERT_TRUE(fmofp::ok(cas.status().encode(w)));
    CasAlerts back{};
    ASSERT_EQ(Status::kOk, CasAlerts::decode(w, back));
    EXPECT_TRUE(back.hyd_a_reduced);
    EXPECT_TRUE(back.fusion_hostile_track);
    EXPECT_FALSE(back.wx_light_turbulence);
    EXPECT_EQ(cas.status().caution_count, back.caution_count);
}

}  // namespace
