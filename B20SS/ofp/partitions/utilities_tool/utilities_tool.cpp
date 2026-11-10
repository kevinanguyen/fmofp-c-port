// fmofp_utilities_tool: the four small utility terminals' logic on stdin/stdout,
// so the Python tests can run the original ecsControl.py, hydrControl.py,
// airframeControl.py and fdmControl.py beside it
// (B20SS/fmofp_bus/tests/test_utilities_oracle.py). Test support, not flight
// code.
//
// One command per line, the first word naming the terminal; numbers are printed
// with 17 significant digits, enums by their names, texts separated by '|'.
//   ecs reset                                   -> ok
//   ecs monitor <temp_c> <pressure_kpa> <air_%> -> ok   (monitor_ecs with sensor data: one pass)
//   ecs oxygen_rate <l_min> | ecs humidity <pct> | ecs climate_temp <c>  -> ok
//   ecs data  -> temperature pressure air_quality climate_temperature humidity oxygen_level oxygen_rate
//                temperature_adjusting pressure_adjusting purification_active passes
//   hyd reset                                   -> ok
//   hyd monitor <primary_psi> <backup_psi>      -> ok   (monitor_pressure on a reading)
//   hyd backup                                  -> ok   (activate_backup)
//   hyd data  -> active_system pressure_status primary_psi backup_psi
//   hyd config -> nominal warning critical
//   afr reset                                   -> ok
//   afr gear <deploy|retract>                   -> the gear state (control_landing_gear's return)
//   afr sensors <wing_root> <fuselage> <leading_edge_c>  -> ok   (a reading: one pass of monitor_airframe)
//   afr data  -> gear_state wing_root_strain fuselage_strain leading_edge_temp passes
//   afr config -> id|type|location per sensor, '|'-separated fields and ';'-separated sensors
//   fdm reset                                   -> ok
//   fdm record <frame> <altitude_ft> <airspeed_kt> -> ok
//   fdm eject <slot>                            -> 1|0   (eject_storage's outcome: a card was there)
//   fdm data  -> records held slot_1_present slot_2_present last_frame last_altitude last_airspeed
//   fdm config -> recorders (id|description|type|name units,...) ';'-separated, then '#', then the cards
//                (slot|description|capacity|contents) ';'-separated

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fmofp/airframe/airframe_manager.hpp>
#include <fmofp/ecs/ecs_control.hpp>
#include <fmofp/fdm/flight_data_recorder.hpp>
#include <fmofp/hydraulics/hydraulic_controller.hpp>

namespace {

namespace icd = fmofp::icd;

bool read(std::istringstream& in, std::vector<double>& out, std::size_t count) {
    out.clear();
    double value = 0.0;
    while (out.size() < count && in >> value) {
        out.push_back(value);
    }
    return out.size() == count;
}

void ecs_command(fmofp::ecs::EcsControl& ecs, const std::string& cmd, std::istringstream& in, std::vector<double>& a) {
    if (cmd == "reset") {
        (void)ecs.init();
        std::printf("ok\n");
    } else if (cmd == "monitor" && read(in, a, 3)) {
        ecs.monitor(a[0], a[1], a[2]);
        std::printf("ok\n");
    } else if (cmd == "oxygen_rate" && read(in, a, 1)) {
        ecs.set_oxygen_rate(a[0]);
        std::printf("ok\n");
    } else if (cmd == "humidity" && read(in, a, 1)) {
        ecs.set_humidity(a[0]);
        std::printf("ok\n");
    } else if (cmd == "climate_temp" && read(in, a, 1)) {
        ecs.set_climate_temperature(a[0]);
        std::printf("ok\n");
    } else if (cmd == "data") {
        std::printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %d %d %d %u\n", ecs.temperature(), ecs.pressure(),
                    ecs.air_quality(), ecs.climate_temperature(), ecs.humidity(), ecs.oxygen_level(),
                    ecs.oxygen_rate(), ecs.temperature_adjusting() ? 1 : 0, ecs.pressure_adjusting() ? 1 : 0,
                    ecs.purification_active() ? 1 : 0, ecs.passes());
    } else {
        std::printf("error unknown ecs command\n");
    }
}

void hyd_command(fmofp::hydraulics::HydraulicController& hyd, const std::string& cmd, std::istringstream& in,
                 std::vector<double>& a) {
    if (cmd == "reset") {
        (void)hyd.init();
        std::printf("ok\n");
    } else if (cmd == "monitor" && read(in, a, 2)) {
        hyd.monitor(a[0], a[1]);
        std::printf("ok\n");
    } else if (cmd == "backup") {
        hyd.activate_backup();
        std::printf("ok\n");
    } else if (cmd == "data") {
        std::printf("%s %s %.17g %.17g\n", icd::to_string(hyd.active_system()), icd::to_string(hyd.pressure_status()),
                    hyd.primary_psi(), hyd.backup_psi());
    } else if (cmd == "config") {
        std::printf("%.17g %.17g %.17g\n", fmofp::hydraulics::kNominalPsi, fmofp::hydraulics::kWarningPsi,
                    fmofp::hydraulics::kCriticalPsi);
    } else {
        std::printf("error unknown hyd command\n");
    }
}

void afr_command(fmofp::airframe::AirframeManager& afr, const std::string& cmd, std::istringstream& in,
                 std::vector<double>& a, std::uint8_t& epoch, std::uint32_t& frame) {
    using fmofp::airframe::GearCommand;
    if (cmd == "reset") {
        (void)afr.init();
        epoch = 0;
        frame = 0;
        std::printf("ok\n");
    } else if (cmd == "gear") {
        std::string what;
        in >> what;
        if (what == "deploy") {
            std::printf("%s\n", icd::to_string(afr.control_landing_gear(GearCommand::DEPLOY)));
        } else if (what == "retract") {
            std::printf("%s\n", icd::to_string(afr.control_landing_gear(GearCommand::RETRACT)));
        } else {
            std::printf("error deploy|retract\n");
        }
    } else if (cmd == "sensors" && read(in, a, 3)) {
        icd::PlantAirframe reading{};
        epoch = static_cast<std::uint8_t>(epoch % 255U + 1U);
        reading.epoch = epoch;
        reading.wing_root_strain = a[0];
        reading.fuselage_strain = a[1];
        reading.leading_edge_temp = a[2];
        afr.step(&reading, nullptr, ++frame);
        std::printf("ok\n");
    } else if (cmd == "data") {
        std::printf("%s %.17g %.17g %.17g %u\n", icd::to_string(afr.gear_state()), afr.wing_root_strain(),
                    afr.fuselage_strain(), afr.leading_edge_temp(), afr.passes());
    } else if (cmd == "config") {
        for (std::size_t i = 0; i < fmofp::airframe::kSensors.size(); ++i) {
            const fmofp::airframe::SensorInfo& s = fmofp::airframe::kSensors[i];
            std::printf("%s%u|%s|%s", i == 0 ? "" : ";", static_cast<unsigned>(s.id), s.type, s.location);
        }
        std::printf("\n");
    } else {
        std::printf("error unknown afr command\n");
    }
}

void fdm_command(fmofp::fdm::FlightDataRecorder& fdm, const std::string& cmd, std::istringstream& in,
                 std::vector<double>& a) {
    if (cmd == "reset") {
        (void)fdm.init();
        std::printf("ok\n");
    } else if (cmd == "record" && read(in, a, 3)) {
        fdm.record(static_cast<std::uint32_t>(a[0]), a[1], a[2]);
        std::printf("ok\n");
    } else if (cmd == "eject" && read(in, a, 1)) {
        const double slot = a[0];
        const bool valid = slot >= 1.0 && slot <= 255.0;
        std::printf("%d\n", valid && fdm.eject_storage(static_cast<std::uint8_t>(slot)) ? 1 : 0);
    } else if (cmd == "data") {
        const fmofp::fdm::Record last = fdm.held() > 0 ? fdm.record_at(fdm.held() - 1) : fmofp::fdm::Record{};
        std::printf("%u %u %d %d %u %.17g %.17g\n", fdm.records(), static_cast<unsigned>(fdm.held()),
                    fdm.slot_present(1) ? 1 : 0, fdm.slot_present(2) ? 1 : 0, last.frame, last.altitude_ft,
                    last.airspeed_kt);
    } else if (cmd == "config") {
        for (std::size_t i = 0; i < fmofp::fdm::kRecorders.size(); ++i) {
            const fmofp::fdm::RecorderInfo& r = fmofp::fdm::kRecorders[i];
            std::printf("%s%u|%s|%s", i == 0 ? "" : ";", static_cast<unsigned>(r.id), r.description, r.type);
            for (std::size_t p = 0; p < r.parameter_count; ++p) {
                std::printf("|%s %s", r.parameters[p].name, r.parameters[p].units);
            }
        }
        std::printf("#");
        for (std::size_t i = 0; i < fmofp::fdm::kCards.size(); ++i) {
            const fmofp::fdm::StorageCard& c = fmofp::fdm::kCards[i];
            std::printf("%s%u|%s|%u|%s", i == 0 ? "" : ";", static_cast<unsigned>(c.slot), c.description, c.capacity_gb,
                        c.contents);
        }
        std::printf("\n");
    } else {
        std::printf("error unknown fdm command\n");
    }
}

}  // namespace

int main() {
    fmofp::ecs::EcsControl ecs;
    fmofp::hydraulics::HydraulicController hyd;
    fmofp::airframe::AirframeManager afr;
    fmofp::fdm::FlightDataRecorder fdm;
    (void)ecs.init();
    (void)hyd.init();
    (void)afr.init();
    (void)fdm.init();
    std::uint8_t afr_epoch = 0;
    std::uint32_t afr_frame = 0;
    std::string line;
    std::vector<double> a;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string which;
        std::string cmd;
        if (!(in >> which) || which.empty() || which[0] == '#') {
            continue;
        }
        in >> cmd;
        if (which == "ecs") {
            ecs_command(ecs, cmd, in, a);
        } else if (which == "hyd") {
            hyd_command(hyd, cmd, in, a);
        } else if (which == "afr") {
            afr_command(afr, cmd, in, a, afr_epoch, afr_frame);
        } else if (which == "fdm") {
            fdm_command(fdm, cmd, in, a);
        } else {
            std::printf("error unknown terminal\n");
        }
    }
    return 0;
}
