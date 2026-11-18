#include <fmofp/cas/crew_alerting.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::cas {

namespace {

using icd::TerminalState;

constexpr std::uint32_t kSelfTestFrames = 10;
constexpr std::uint8_t kCountMax = 255;

struct AlertInfo {
    const char* name;
    Severity severity;
};

// The table below and the switch after it follow fmofp_bus/cas_alerts.py's ALERTS, entry for entry.
constexpr std::array<AlertInfo, kAlertCount> kAlerts{{
    {"eng_egt_high", Severity::kWarning},
    {"eng_egt_caution", Severity::kCaution},
    {"eng_egt_unknown", Severity::kCaution},
    {"eng_oil_press_lo", Severity::kWarning},
    {"eng_oil_press_low", Severity::kCaution},
    {"eng_oil_press_unknown", Severity::kCaution},
    {"eng_oil_temp_high", Severity::kWarning},
    {"eng_oil_temp_unknown", Severity::kCaution},
    {"eng_vibration_high", Severity::kCaution},
    {"eng_vib_unknown", Severity::kCaution},
    {"fuel_qty_unknown", Severity::kCaution},
    {"fuel_quantity_low", Severity::kWarning},
    {"fuel_quantity_caution", Severity::kCaution},
    {"fuel_balance_unknown", Severity::kCaution},
    {"fuel_imbalance", Severity::kCaution},
    {"hyd_a_unknown", Severity::kCaution},
    {"hyd_a_low", Severity::kWarning},
    {"hyd_a_reduced", Severity::kCaution},
    {"hyd_b_unknown", Severity::kCaution},
    {"hyd_b_low", Severity::kWarning},
    {"hyd_b_reduced", Severity::kCaution},
    {"hyd_c_unknown", Severity::kCaution},
    {"hyd_c_low", Severity::kWarning},
    {"hyd_c_reduced", Severity::kCaution},
    {"elec_gen_1_unknown", Severity::kCaution},
    {"elec_gen_1_fault", Severity::kWarning},
    {"elec_gen_2_unknown", Severity::kCaution},
    {"elec_gen_2_fault", Severity::kWarning},
    {"elec_bus_volts_unknown", Severity::kCaution},
    {"elec_main_bus_lo", Severity::kCaution},
    {"eng_max_continuous_thrust", Severity::kAdvisory},
    {"fcs_pull_up", Severity::kWarning},
    {"fcs_sink_rate", Severity::kWarning},
    {"fcs_terrain", Severity::kWarning},
    {"fcs_alt_low", Severity::kCaution},
    {"perf_g_force", Severity::kWarning},
    {"perf_angle_of_attack", Severity::kWarning},
    {"perf_roll", Severity::kWarning},
    {"perf_pitch", Severity::kWarning},
    {"perf_vertical_speed", Severity::kWarning},
    {"rwr_high_pri_threats", Severity::kWarning},
    {"rwr_threat_contacts", Severity::kCaution},
    {"cmds_chaff_depleted", Severity::kWarning},
    {"cmds_chaff_low", Severity::kCaution},
    {"cmds_flares_depleted", Severity::kWarning},
    {"cmds_flares_low", Severity::kCaution},
    {"ew_ecm_active", Severity::kAdvisory},
    {"sensor_system_fault", Severity::kWarning},
    {"sensor_degraded_mode", Severity::kCaution},
    {"fusion_hostile_tracks", Severity::kWarning},
    {"fusion_hostile_track", Severity::kCaution},
    {"wx_microburst", Severity::kWarning},
    {"wx_severe_windshear", Severity::kWarning},
    {"wx_moderate_windshear", Severity::kCaution},
    {"wx_windshear_ahead", Severity::kAdvisory},
    {"wx_extreme_turbulence", Severity::kWarning},
    {"wx_severe_turbulence", Severity::kWarning},
    {"wx_moderate_turbulence", Severity::kCaution},
    {"wx_light_turbulence", Severity::kAdvisory},
}};

void set_field(icd::CasAlerts& s, Alert alert, bool on) noexcept {
    switch (alert) {
        case Alert::kEngEgtHigh:
            s.eng_egt_high = on;
            break;
        case Alert::kEngEgtCaution:
            s.eng_egt_caution = on;
            break;
        case Alert::kEngEgtUnknown:
            s.eng_egt_unknown = on;
            break;
        case Alert::kEngOilPressLo:
            s.eng_oil_press_lo = on;
            break;
        case Alert::kEngOilPressLow:
            s.eng_oil_press_low = on;
            break;
        case Alert::kEngOilPressUnknown:
            s.eng_oil_press_unknown = on;
            break;
        case Alert::kEngOilTempHigh:
            s.eng_oil_temp_high = on;
            break;
        case Alert::kEngOilTempUnknown:
            s.eng_oil_temp_unknown = on;
            break;
        case Alert::kEngVibrationHigh:
            s.eng_vibration_high = on;
            break;
        case Alert::kEngVibUnknown:
            s.eng_vib_unknown = on;
            break;
        case Alert::kFuelQtyUnknown:
            s.fuel_qty_unknown = on;
            break;
        case Alert::kFuelQuantityLow:
            s.fuel_quantity_low = on;
            break;
        case Alert::kFuelQuantityCaution:
            s.fuel_quantity_caution = on;
            break;
        case Alert::kFuelBalanceUnknown:
            s.fuel_balance_unknown = on;
            break;
        case Alert::kFuelImbalance:
            s.fuel_imbalance = on;
            break;
        case Alert::kHydAUnknown:
            s.hyd_a_unknown = on;
            break;
        case Alert::kHydALow:
            s.hyd_a_low = on;
            break;
        case Alert::kHydAReduced:
            s.hyd_a_reduced = on;
            break;
        case Alert::kHydBUnknown:
            s.hyd_b_unknown = on;
            break;
        case Alert::kHydBLow:
            s.hyd_b_low = on;
            break;
        case Alert::kHydBReduced:
            s.hyd_b_reduced = on;
            break;
        case Alert::kHydCUnknown:
            s.hyd_c_unknown = on;
            break;
        case Alert::kHydCLow:
            s.hyd_c_low = on;
            break;
        case Alert::kHydCReduced:
            s.hyd_c_reduced = on;
            break;
        case Alert::kElecGen1Unknown:
            s.elec_gen_1_unknown = on;
            break;
        case Alert::kElecGen1Fault:
            s.elec_gen_1_fault = on;
            break;
        case Alert::kElecGen2Unknown:
            s.elec_gen_2_unknown = on;
            break;
        case Alert::kElecGen2Fault:
            s.elec_gen_2_fault = on;
            break;
        case Alert::kElecBusVoltsUnknown:
            s.elec_bus_volts_unknown = on;
            break;
        case Alert::kElecMainBusLo:
            s.elec_main_bus_lo = on;
            break;
        case Alert::kEngMaxContinuousThrust:
            s.eng_max_continuous_thrust = on;
            break;
        case Alert::kFcsPullUp:
            s.fcs_pull_up = on;
            break;
        case Alert::kFcsSinkRate:
            s.fcs_sink_rate = on;
            break;
        case Alert::kFcsTerrain:
            s.fcs_terrain = on;
            break;
        case Alert::kFcsAltLow:
            s.fcs_alt_low = on;
            break;
        case Alert::kPerfGForce:
            s.perf_g_force = on;
            break;
        case Alert::kPerfAngleOfAttack:
            s.perf_angle_of_attack = on;
            break;
        case Alert::kPerfRoll:
            s.perf_roll = on;
            break;
        case Alert::kPerfPitch:
            s.perf_pitch = on;
            break;
        case Alert::kPerfVerticalSpeed:
            s.perf_vertical_speed = on;
            break;
        case Alert::kRwrHighPriThreats:
            s.rwr_high_pri_threats = on;
            break;
        case Alert::kRwrThreatContacts:
            s.rwr_threat_contacts = on;
            break;
        case Alert::kCmdsChaffDepleted:
            s.cmds_chaff_depleted = on;
            break;
        case Alert::kCmdsChaffLow:
            s.cmds_chaff_low = on;
            break;
        case Alert::kCmdsFlaresDepleted:
            s.cmds_flares_depleted = on;
            break;
        case Alert::kCmdsFlaresLow:
            s.cmds_flares_low = on;
            break;
        case Alert::kEwEcmActive:
            s.ew_ecm_active = on;
            break;
        case Alert::kSensorSystemFault:
            s.sensor_system_fault = on;
            break;
        case Alert::kSensorDegradedMode:
            s.sensor_degraded_mode = on;
            break;
        case Alert::kFusionHostileTracks:
            s.fusion_hostile_tracks = on;
            break;
        case Alert::kFusionHostileTrack:
            s.fusion_hostile_track = on;
            break;
        case Alert::kWxMicroburst:
            s.wx_microburst = on;
            break;
        case Alert::kWxSevereWindshear:
            s.wx_severe_windshear = on;
            break;
        case Alert::kWxModerateWindshear:
            s.wx_moderate_windshear = on;
            break;
        case Alert::kWxWindshearAhead:
            s.wx_windshear_ahead = on;
            break;
        case Alert::kWxExtremeTurbulence:
            s.wx_extreme_turbulence = on;
            break;
        case Alert::kWxSevereTurbulence:
            s.wx_severe_turbulence = on;
            break;
        case Alert::kWxModerateTurbulence:
            s.wx_moderate_turbulence = on;
            break;
        case Alert::kWxLightTurbulence:
            s.wx_light_turbulence = on;
            break;
        case Alert::kCount:
        default:
            break;
    }
}


bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

std::uint8_t clamp_count(unsigned n) noexcept { return static_cast<std::uint8_t>(std::min(n, unsigned{kCountMax})); }

void set(AlertSet& out, Alert alert) noexcept { out[static_cast<std::size_t>(alert)] = true; }

// _compute_alerts' engine and fuel rows. A field with no real data is reported UNKNOWN, never judged.
void engine_and_fuel(const AlertInputs& in, AlertSet& out) noexcept {
    // The EGT judged is the display's model of it from the thrust (350 + 4.5 x thrust), not the engine's reading:
    // _poll_data wrote the model just before the rules ran (ICD README section 2, v1.9).
    const double egt = 350.0 + in.thrust_pct * 4.5;
    if (!in.egt_valid) {
        set(out, Alert::kEngEgtUnknown);
    } else if (egt > kEgtWarningC) {
        set(out, Alert::kEngEgtHigh);
    } else if (egt > kEgtCautionC) {
        set(out, Alert::kEngEgtCaution);
    }
    if (!in.oil_press_valid) {
        set(out, Alert::kEngOilPressUnknown);
    } else if (in.oil_psi < kOilPressWarningPsi) {
        set(out, Alert::kEngOilPressLo);
    } else if (in.oil_psi < kOilPressCautionPsi) {
        set(out, Alert::kEngOilPressLow);
    }
    if (!in.oil_temp_valid) {
        set(out, Alert::kEngOilTempUnknown);
    } else if (in.oil_temp_c > kOilTempWarningC) {
        set(out, Alert::kEngOilTempHigh);
    }
    if (!in.vib_valid) {
        set(out, Alert::kEngVibUnknown);
    } else if (in.vib > kVibrationCaution) {
        set(out, Alert::kEngVibrationHigh);
    }
    if (!in.fuel_total_valid) {
        set(out, Alert::kFuelQtyUnknown);
    } else if (in.fuel_total_kg < kFuelWarningKg) {
        set(out, Alert::kFuelQuantityLow);
    } else if (in.fuel_total_kg < kFuelCautionKg) {
        set(out, Alert::kFuelQuantityCaution);
    }
    if (!in.fuel_balance_valid) {
        set(out, Alert::kFuelBalanceUnknown);
    } else if (std::fabs(in.fuel_balance_kg) > kFuelImbalanceKg) {
        set(out, Alert::kFuelImbalance);
    }
}

// _compute_alerts' hydraulic and electrical rows and the thrust advisory.
void systems(const AlertInputs& in, AlertSet& out) noexcept {
    constexpr std::array<std::array<Alert, 3>, 3> kHyd{{
        {Alert::kHydAUnknown, Alert::kHydALow, Alert::kHydAReduced},
        {Alert::kHydBUnknown, Alert::kHydBLow, Alert::kHydBReduced},
        {Alert::kHydCUnknown, Alert::kHydCLow, Alert::kHydCReduced},
    }};
    for (std::size_t i = 0; i < kHyd.size(); ++i) {
        if (!in.hyd_valid[i]) {
            set(out, kHyd[i][0]);
        } else if (in.hyd_psi[i] < kHydWarningPsi) {
            set(out, kHyd[i][1]);
        } else if (in.hyd_psi[i] < kHydCautionPsi) {
            set(out, kHyd[i][2]);
        }
    }
    if (!in.gen_1_valid) {
        set(out, Alert::kElecGen1Unknown);
    } else if (!in.gen_1_ok) {
        set(out, Alert::kElecGen1Fault);
    }
    if (!in.gen_2_valid) {
        set(out, Alert::kElecGen2Unknown);
    } else if (!in.gen_2_ok) {
        set(out, Alert::kElecGen2Fault);
    }
    if (!in.main_bus_valid) {
        set(out, Alert::kElecBusVoltsUnknown);
    } else if (in.main_bus_v < kMainBusLowV) {
        set(out, Alert::kElecMainBusLo);
    }
    if (in.thrust_pct > kMaxContinuousThrustPct) {
        set(out, Alert::kEngMaxContinuousThrust);
    }
}

// The rows _poll_data appended from the GCAS (severity 1 a warning, 2 a caution) and the performance monitor.
void flight_control(const AlertInputs& in, AlertSet& out) noexcept {
    if (in.gcas_pullup) {
        set(out, Alert::kFcsPullUp);
    } else if (in.gcas_sink_rate) {
        set(out, Alert::kFcsSinkRate);
    }
    if (in.gcas_terrain) {
        set(out, Alert::kFcsTerrain);
    }
    if (in.gcas_alt_low) {
        set(out, Alert::kFcsAltLow);
    }
    constexpr std::array<Alert, 5> kPerf{Alert::kPerfGForce, Alert::kPerfAngleOfAttack, Alert::kPerfRoll,
                                         Alert::kPerfPitch, Alert::kPerfVerticalSpeed};
    for (std::size_t i = 0; i < kPerf.size(); ++i) {
        if (in.perf_exceed[i]) {
            set(out, kPerf[i]);
        }
    }
}

// _compute_defensive_alerts and _compute_sensor_alerts.
void tactical(const AlertInputs& in, AlertSet& out) noexcept {
    if (in.rwr_high_priority > 0U) {
        set(out, Alert::kRwrHighPriThreats);
    } else if (in.rwr_hostile > 0U) {
        set(out, Alert::kRwrThreatContacts);
    }
    if (in.chaff_remaining == 0U) {
        set(out, Alert::kCmdsChaffDepleted);
    } else if (in.chaff_remaining <= kChaffLow) {
        set(out, Alert::kCmdsChaffLow);
    }
    if (in.flares_remaining == 0U) {
        set(out, Alert::kCmdsFlaresDepleted);
    } else if (in.flares_remaining <= kFlaresLow) {
        set(out, Alert::kCmdsFlaresLow);
    }
    if (in.ecm_active) {
        set(out, Alert::kEwEcmActive);
    }
    if (in.sensor_health == icd::SensorHealth::FAULT) {
        set(out, Alert::kSensorSystemFault);
    } else if (in.sensor_health == icd::SensorHealth::DEGRADED) {
        set(out, Alert::kSensorDegradedMode);
    }
    if (in.fused_hostile >= kFusionWarningTracks) {
        set(out, Alert::kFusionHostileTracks);
    } else if (in.fused_hostile >= 1U) {
        set(out, Alert::kFusionHostileTrack);
    }
}

// _compute_weather_alerts.
void weather(const AlertInputs& in, AlertSet& out) noexcept {
    if (in.wx_microburst) {
        set(out, Alert::kWxMicroburst);
    } else if (in.wx_windshear == icd::ShearSeverity::SEVERE) {
        set(out, Alert::kWxSevereWindshear);
    } else if (in.wx_windshear == icd::ShearSeverity::MODERATE) {
        set(out, Alert::kWxModerateWindshear);
    } else if (in.wx_windshear == icd::ShearSeverity::LOW) {
        set(out, Alert::kWxWindshearAhead);
    }
    if (in.wx_turbulence == icd::TurbulenceCategory::EXTREME) {
        set(out, Alert::kWxExtremeTurbulence);
    } else if (in.wx_turbulence == icd::TurbulenceCategory::SEVERE) {
        set(out, Alert::kWxSevereTurbulence);
    } else if (in.wx_turbulence == icd::TurbulenceCategory::MODERATE) {
        set(out, Alert::kWxModerateTurbulence);
    } else if (in.wx_turbulence == icd::TurbulenceCategory::LIGHT) {
        set(out, Alert::kWxLightTurbulence);
    }
}

}  // namespace

Severity severity_of(Alert alert) noexcept {
    const auto i = static_cast<std::size_t>(alert);
    return i < kAlertCount ? kAlerts[i].severity : Severity::kAdvisory;
}

const char* name_of(Alert alert) noexcept {
    const auto i = static_cast<std::size_t>(alert);
    return i < kAlertCount ? kAlerts[i].name : "";
}

AlertSet evaluate(const AlertInputs& in) noexcept {
    AlertSet out{};
    engine_and_fuel(in, out);
    systems(in, out);
    flight_control(in, out);
    tactical(in, out);
    weather(in, out);
    return out;
}

double profile_engine_power(const icd::FmsStatus* fms) noexcept {
    // fmsControl's flight profiles (flight_feed.PROFILE_LIMITS): engine power per flight mode.
    if (fms == nullptr) {
        return 0.7;
    }
    switch (fms->flight_mode) {
        case icd::FmsFlightMode::COMBAT:
        case icd::FmsFlightMode::EMERGENCY:
            return 1.0;
        case icd::FmsFlightMode::STEALTH:
            return 0.6;
        case icd::FmsFlightMode::TRAINING:
            return 0.9;
        case icd::FmsFlightMode::NORMAL:
        default:
            return 0.7;
    }
}

Status CrewAlerting::init() noexcept {
    fms_ = {};
    gcas_ = {};
    perf_ = {};
    engine_ = {};
    fuel_ = {};
    weather_ = {};
    defensive_ = {};
    sensor_ = {};
    power_ = {};
    hydraulics_ = {};
    fused_ = {};
    contacts_ = {};
    inputs_ = AlertInputs{};
    alerts_ = AlertSet{};
    computed_ = false;
    status_ = icd::CasAlerts{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    fill_status();
    return Status::kOk;
}

void CrewAlerting::reset() noexcept { (void)init(); }

void CrewAlerting::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

template <typename Message>
void CrewAlerting::keep(Held<Message>& held, const Message* message, std::uint32_t frame) noexcept {
    if (message != nullptr) {
        held.message = *message;
        held.frame = frame;
        held.have = true;
    }
}

template <typename Message>
const Message* CrewAlerting::heard(const Held<Message>& held, std::uint32_t frame) noexcept {
    if (!held.have || frame < held.frame || frame - held.frame >= kStaleFrames) {
        return nullptr;
    }
    return &held.message;
}

bool CrewAlerting::any_heard(std::uint32_t frame) const noexcept {
    return heard(fms_, frame) != nullptr || heard(gcas_, frame) != nullptr || heard(perf_, frame) != nullptr ||
           heard(engine_, frame) != nullptr || heard(fuel_, frame) != nullptr || heard(weather_, frame) != nullptr ||
           heard(defensive_, frame) != nullptr || heard(sensor_, frame) != nullptr ||
           heard(power_, frame) != nullptr || heard(hydraulics_, frame) != nullptr ||
           heard(fused_, frame) != nullptr || heard(contacts_, frame) != nullptr;
}

void CrewAlerting::gather_engine(std::uint32_t frame) noexcept {
    inputs_.thrust_pct = profile_engine_power(heard(fms_, frame)) * 100.0;
    inputs_.egt_valid = true;
    const icd::EngEngineStatus* engine = heard(engine_, frame);
    const bool engine_valid = engine != nullptr && engine->engine_1_ssm == icd::Ssm::NORMAL;
    inputs_.oil_press_valid = engine_valid;
    inputs_.oil_temp_valid = engine_valid;
    inputs_.vib_valid = engine_valid;
    if (engine_valid) {
        inputs_.oil_psi = engine->oil_pressure_1;
        inputs_.oil_temp_c = engine->oil_temperature_1;
        inputs_.vib = engine->vibration_1;
    }
    const icd::EngFuelStatus* fuel = heard(fuel_, frame);
    inputs_.fuel_total_valid = fuel != nullptr;
    inputs_.fuel_balance_valid = fuel != nullptr;
    if (fuel != nullptr) {
        inputs_.fuel_total_kg = fuel->total;
        inputs_.fuel_balance_kg = fuel->main_left - fuel->main_right;
    }
}

void CrewAlerting::gather_systems(std::uint32_t frame) noexcept {
    const icd::HydStatus* hyd = heard(hydraulics_, frame);
    const bool hyd_valid = hyd != nullptr && hyd->pressures_valid;
    inputs_.hyd_valid = {hyd_valid, hyd_valid, false};  // SYS C has no system behind it (README section 2)
    if (hyd_valid) {
        inputs_.hyd_psi[0] = hyd->primary_psi;
        inputs_.hyd_psi[1] = hyd->backup_psi;
    }
    const icd::PwrStatus* power = heard(power_, frame);
    const bool power_valid = power != nullptr && power->electrical_valid;
    inputs_.gen_1_valid = power_valid;
    inputs_.gen_2_valid = power_valid;
    inputs_.main_bus_valid = power_valid;
    if (power_valid) {
        inputs_.gen_1_ok = power->generator_online;  // the one generator stands for both rows (README section 2)
        inputs_.gen_2_ok = power->generator_online;
        inputs_.main_bus_v = power->main_bus_voltage;
    }
}

void CrewAlerting::gather_tactical(std::uint32_t frame) noexcept {
    const icd::FcsGcasAlerts* gcas = heard(gcas_, frame);
    inputs_.gcas_pullup = gcas != nullptr && gcas->pullup;
    inputs_.gcas_sink_rate = gcas != nullptr && gcas->sink_rate;
    inputs_.gcas_terrain = gcas != nullptr && gcas->terrain;
    inputs_.gcas_alt_low = gcas != nullptr && gcas->alt_low;
    if (gcas != nullptr) {
        inputs_.gcas_vertical_speed = gcas->vertical_speed;
        inputs_.gcas_altitude = gcas->altitude;
        inputs_.gcas_terrain_clearance = gcas->terrain_clearance;
    }
    const icd::FcsPerfStatus* perf = heard(perf_, frame);
    inputs_.perf_exceed = {perf != nullptr && perf->exceed_g, perf != nullptr && perf->exceed_aoa,
                           perf != nullptr && perf->exceed_roll, perf != nullptr && perf->exceed_pitch,
                           perf != nullptr && perf->exceed_vertical_speed};

    // The defensive service's dictionary: its countermeasures and ECM mode, and its contacts, which the feed takes
    // from the broadcast block only while the status itself is heard; the EICAS's defaults otherwise.
    const icd::DefStatus* def = heard(defensive_, frame);
    inputs_.chaff_remaining = def != nullptr ? def->chaff_remaining : kChaffFull;
    inputs_.flares_remaining = def != nullptr ? def->flares_remaining : kFlaresFull;
    inputs_.ecm_active = def != nullptr && def->ecm_mode == icd::EcmMode::ACTIVE;
    inputs_.rwr_hostile = 0;
    inputs_.rwr_high_priority = 0;
    const icd::DefRwrContacts* contacts = heard(contacts_, frame);
    if (def != nullptr && contacts != nullptr) {
        const std::uint16_t n = std::min(contacts->contact_count, icd::DefRwrContacts::kMaxContact);
        for (std::uint16_t i = 0; i < n; ++i) {
            if (contacts->contact[i].hostile) {
                ++inputs_.rwr_hostile;
                if (contacts->contact[i].priority == 1U) {
                    ++inputs_.rwr_high_priority;
                }
            }
        }
    }
    const icd::SnsStatus* sensor = heard(sensor_, frame);
    inputs_.sensor_health = sensor != nullptr ? sensor->health : icd::SensorHealth::INITIALISING;
    inputs_.fused_hostile = 0;
    const icd::RdrFusedTracks* fused = heard(fused_, frame);
    if (fused != nullptr) {
        const std::uint16_t n = std::min(fused->track_count, icd::RdrFusedTracks::kMaxTrack);
        inputs_.fused_hostile = static_cast<unsigned>(
            std::count_if(fused->track.begin(), fused->track.begin() + n,
                          [](const icd::RdrFusedTracksTrack& t) { return t.threat == icd::Threat::HOSTILE; }));
    }
    const icd::RdrWxScan* wx = heard(weather_, frame);
    inputs_.wx_microburst = wx != nullptr && wx->microburst;
    inputs_.wx_windshear = wx != nullptr ? wx->max_shear : icd::ShearSeverity::NONE;
    inputs_.wx_turbulence = wx != nullptr ? wx->max_turbulence : icd::TurbulenceCategory::NONE;
}

void CrewAlerting::gather(std::uint32_t frame) noexcept {
    gather_engine(frame);
    gather_systems(frame);
    gather_tactical(frame);
}

void CrewAlerting::step(const Received& received, std::uint32_t frame) noexcept {
    keep(fms_, received.fms, frame);
    keep(gcas_, received.gcas, frame);
    keep(perf_, received.perf, frame);
    keep(engine_, received.engine, frame);
    keep(fuel_, received.fuel, frame);
    keep(weather_, received.weather, frame);
    keep(defensive_, received.defensive, frame);
    keep(sensor_, received.sensor, frame);
    keep(power_, received.power, frame);
    keep(hydraulics_, received.hydraulics, frame);
    keep(fused_, received.fused, frame);
    keep(contacts_, received.contacts, frame);

    gather(frame);
    alerts_ = evaluate(inputs_);
    computed_ = true;

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }
    const bool fresh = any_heard(frame);
    if (status_.state == TerminalState::INITIALIZING && fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status();
}

void CrewAlerting::command_mode(const icd::CasModeCmd& cmd) noexcept {
    if (!mode_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    status_.last_cmd_seq = cmd.cmd_seq;
    if (!commandable(cmd.requested_state)) {
        status_.cmd_rejected = true;
        return;
    }
    status_.cmd_rejected = false;
    status_.state = cmd.requested_state;
    status_.mode_transition = false;
}

void CrewAlerting::fill_status() noexcept {
    unsigned warnings = 0;
    unsigned cautions = 0;
    unsigned advisories = 0;
    for (std::size_t i = 0; i < kAlertCount; ++i) {
        const auto alert = static_cast<Alert>(i);
        set_field(status_, alert, alerts_[i]);
        if (!alerts_[i]) {
            continue;
        }
        switch (kAlerts[i].severity) {
            case Severity::kWarning:
                ++warnings;
                break;
            case Severity::kCaution:
                ++cautions;
                break;
            case Severity::kAdvisory:
            default:
                ++advisories;
                break;
        }
    }
    status_.warning_count = static_cast<std::uint8_t>(warnings);
    status_.caution_count = static_cast<std::uint8_t>(cautions);
    status_.advisory_count = static_cast<std::uint8_t>(advisories);
    status_.computed = computed_;
    status_.healthy = !bit_.failed;
    status_.chaff_remaining = clamp_count(inputs_.chaff_remaining);
    status_.flares_remaining = clamp_count(inputs_.flares_remaining);
    status_.rwr_high_priority = clamp_count(inputs_.rwr_high_priority);
    status_.rwr_hostile = clamp_count(inputs_.rwr_hostile);
    status_.fused_hostile = clamp_count(inputs_.fused_hostile);
    status_.gcas_vertical_speed = inputs_.gcas_vertical_speed;
    status_.gcas_altitude = inputs_.gcas_altitude;
    status_.gcas_terrain_clearance = inputs_.gcas_terrain_clearance;
}

}  // namespace fmofp::cas
