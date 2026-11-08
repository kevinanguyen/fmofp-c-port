// fmofp_power_tool: the power management logic on stdin/stdout, so the Python
// tests can run the original powerManagementSystem.py and its batteries and
// thermal units beside it (B20SS/fmofp_bus/tests/test_power_oracle.py). Test
// support, not flight code.
//
// One command per line; numbers are printed with 17 significant digits, enums by
// their names.
//   reset                                              -> ok
//   electrical <gen_kw> <cons_kw> <main_v> <aux_v> <freq_hz> <pf>
//                                                      -> ok   (one 1 Hz step on this reading: adjust_power_parameters + monitor)
//   gen <kw>                                           -> ok   (SET_GENERATOR_OUTPUT: the hold the plant is asked for)
//   gen_auto                                           -> ok
//   emergency <0|1>                                    -> ok
//   apu <start|stop>                                   -> 0|1 (start: the Python's return) / ok (stop)
//   engine_start                                       -> 0|1
//   hvac_setpoint <c> | hvac_airflow <pct> | hvac_power <0|1> -> ok
//   dissipation <0|1>                                  -> ok
//   equipment <index> <amps>                           -> 0|1  (the mission equipment bank's battery powers its equipment)
//   data        -> main_charge emergency_charge apu_charge generator consumption balance main_v aux_v freq pf coolant cabin
//                  (monitor()'s snapshot, unrounded)
//   batteries   -> main: charge load online | emergency: charge load active endurance_min | apu: charge load running |
//                  equipment: 3 x (charge load powering)
//   thermal     -> coolant target ambient heat_load fan rejected active status | cabin setpoint airflow powered at_setpoint
//   gencmd      -> override output sequence
//   status      -> state thermal_status generator_online emergency apu hvac_powered dissipation at_setpoint cmd_status

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fmofp/power/power_management.hpp>

namespace {

namespace power = fmofp::power;
namespace icd = fmofp::icd;

bool read(std::istringstream& in, std::vector<double>& out, std::size_t count) {
    out.clear();
    double value = 0.0;
    while (out.size() < count && in >> value) {
        out.push_back(value);
    }
    return out.size() == count;
}

void print_battery(const power::Battery& b) {
    std::printf("%.17g %.17g %d", b.charge_pct(), b.load_amps(), b.online() ? 1 : 0);
}

}  // namespace

int main() {
    power::PowerManagement pm;
    (void)pm.init();
    std::uint8_t sequence = 0;
    std::string line;
    std::vector<double> a;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            (void)pm.init();
            sequence = 0;
            std::printf("ok\n");
        } else if (cmd == "electrical" && read(in, a, 6)) {
            icd::PlantElectrical e{};
            e.epoch = 1;
            e.generator_output = a[0];
            e.total_power_consumption = a[1];
            e.main_bus_voltage = a[2];
            e.aux_bus_voltage = a[3];
            e.generator_frequency = a[4];
            e.power_factor = a[5];
            pm.update(e);
            std::printf("ok\n");
        } else if (cmd == "gen" && read(in, a, 1)) {
            pm.set_generator_output(a[0], ++sequence);
            std::printf("ok\n");
        } else if (cmd == "gen_auto") {
            pm.generator_auto(++sequence);
            std::printf("ok\n");
        } else if (cmd == "emergency" && read(in, a, 1)) {
            pm.set_emergency_power(a[0] != 0.0);
            std::printf("ok\n");
        } else if (cmd == "apu") {
            std::string what;
            in >> what;
            if (what == "start") {
                std::printf("%d\n", pm.start_apu() ? 1 : 0);
            } else if (what == "stop") {
                pm.stop_apu();
                std::printf("ok\n");
            } else {
                std::printf("error apu start|stop\n");
            }
        } else if (cmd == "engine_start") {
            std::printf("%d\n", pm.start_engine() ? 1 : 0);
        } else if (cmd == "hvac_setpoint" && read(in, a, 1)) {
            pm.set_hvac_setpoint(a[0]);
            std::printf("ok\n");
        } else if (cmd == "hvac_airflow" && read(in, a, 1)) {
            pm.set_hvac_airflow(a[0]);
            std::printf("ok\n");
        } else if (cmd == "hvac_power" && read(in, a, 1)) {
            pm.set_hvac_power(a[0] != 0.0);
            std::printf("ok\n");
        } else if (cmd == "dissipation" && read(in, a, 1)) {
            pm.set_dissipation(a[0] != 0.0);
            std::printf("ok\n");
        } else if (cmd == "equipment" && read(in, a, 2)) {
            std::printf("%d\n", pm.power_equipment(static_cast<std::size_t>(a[0]), a[1]) ? 1 : 0);
        } else if (cmd == "data") {
            const icd::PwrStatus& s = pm.status();
            std::printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n",
                        pm.main_battery().charge_pct(), pm.emergency_battery().charge_pct(), pm.apu_battery().charge_pct(),
                        s.generator_output, s.total_power_consumption, s.power_balance, s.main_bus_voltage,
                        s.aux_bus_voltage, s.generator_frequency, s.power_factor, pm.cooling().coolant_temp_c(),
                        pm.hvac().cabin_temp_c());
        } else if (cmd == "batteries") {
            print_battery(pm.main_battery());
            std::printf(" | ");
            print_battery(pm.emergency_battery());
            std::printf(" %d %.17g | ", pm.emergency_battery().emergency_mode_active() ? 1 : 0,
                        pm.emergency_battery().estimated_endurance_minutes());
            print_battery(pm.apu_battery());
            std::printf(" %d |", pm.apu_battery().apu_running() ? 1 : 0);
            for (std::size_t i = 0; i < power::kEquipmentCount; ++i) {
                std::printf(" ");
                print_battery(pm.equipment(i));
                std::printf(" %d", pm.equipment(i).powering_equipment() ? 1 : 0);
            }
            std::printf("\n");
        } else if (cmd == "thermal") {
            const power::CoolingSystem& c = pm.cooling();
            const power::ActiveDissipationUnit& d = c.dissipation_unit();
            const power::HvacSystem& h = pm.hvac();
            std::printf("%.17g %.17g %.17g %.17g %.17g %.17g %d %s | %.17g %.17g %.17g %d %d\n", c.coolant_temp_c(),
                        c.target_temp_c(), c.ambient_temp_c(), c.heat_load_w(), d.fan_pct(), d.last_rejected_watts(),
                        d.active() ? 1 : 0, icd::to_string(c.thermal_status()), h.cabin_temp_c(), h.setpoint_c(),
                        h.airflow_pct(), h.powered() ? 1 : 0, h.at_setpoint() ? 1 : 0);
        } else if (cmd == "gencmd") {
            const icd::PwrGenCmd& g = pm.gen_cmd();
            std::printf("%d %.17g %u\n", g.override ? 1 : 0, g.generator_output, static_cast<unsigned>(g.sequence));
        } else if (cmd == "status") {
            const icd::PwrStatus& s = pm.status();
            std::printf("%s %s %d %d %d %d %d %d %s\n", icd::to_string(s.state), icd::to_string(s.thermal_status),
                        s.generator_online ? 1 : 0, s.emergency_mode_active ? 1 : 0, s.apu_running ? 1 : 0,
                        s.hvac_powered ? 1 : 0, s.dissipation_active ? 1 : 0, s.hvac_at_setpoint ? 1 : 0,
                        icd::to_string(s.power_cmd_status));
        } else {
            std::printf("error unknown command\n");
        }
    }
    return 0;
}
