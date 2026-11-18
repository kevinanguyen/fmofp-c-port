// fmofp_cas_tool: the crew alerting rules on stdin/stdout, so the Python tests
// can run the frozen eicas.py's alert methods beside them
// (B20SS/fmofp_bus/tests/test_cas_oracle.py). Test support, not flight code.
//
// One command per line.
//   reset               -> ok   (the inputs back to their defaults: AlertInputs{})
//   set <name> <value>  -> ok | error unknown <name>   (an AlertInputs field; bools 0/1, enums by number;
//                          hyd_valid_a..c, hyd_psi_a..c and perf_0..4 for the arrays)
//   eval                -> the CAS_ALERTS field names of the alerts set, in the list's order, or "none"
//   power <mode>|none   -> the profile's engine power for an FMS flight mode number, or with the FMS not heard

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>

#include <fmofp/cas/crew_alerting.hpp>

namespace {

namespace cas = fmofp::cas;
namespace icd = fmofp::icd;

bool set_bool(cas::AlertInputs& in, const std::string& name, double v) {
    const bool b = v != 0.0;
    if (name == "egt_valid") {
        in.egt_valid = b;
    } else if (name == "oil_press_valid") {
        in.oil_press_valid = b;
    } else if (name == "oil_temp_valid") {
        in.oil_temp_valid = b;
    } else if (name == "vib_valid") {
        in.vib_valid = b;
    } else if (name == "fuel_total_valid") {
        in.fuel_total_valid = b;
    } else if (name == "fuel_balance_valid") {
        in.fuel_balance_valid = b;
    } else if (name == "gen_1_valid") {
        in.gen_1_valid = b;
    } else if (name == "gen_1_ok") {
        in.gen_1_ok = b;
    } else if (name == "gen_2_valid") {
        in.gen_2_valid = b;
    } else if (name == "gen_2_ok") {
        in.gen_2_ok = b;
    } else if (name == "main_bus_valid") {
        in.main_bus_valid = b;
    } else if (name == "gcas_pullup") {
        in.gcas_pullup = b;
    } else if (name == "gcas_sink_rate") {
        in.gcas_sink_rate = b;
    } else if (name == "gcas_terrain") {
        in.gcas_terrain = b;
    } else if (name == "gcas_alt_low") {
        in.gcas_alt_low = b;
    } else if (name == "ecm_active") {
        in.ecm_active = b;
    } else if (name == "wx_microburst") {
        in.wx_microburst = b;
    } else if (name.size() == 11 && name.compare(0, 10, "hyd_valid_") == 0 && name[10] >= 'a' && name[10] <= 'c') {
        in.hyd_valid[static_cast<std::size_t>(name[10] - 'a')] = b;
    } else if (name.size() == 6 && name.compare(0, 5, "perf_") == 0 && name[5] >= '0' && name[5] <= '4') {
        in.perf_exceed[static_cast<std::size_t>(name[5] - '0')] = b;
    } else {
        return false;
    }
    return true;
}

bool set_number(cas::AlertInputs& in, const std::string& name, double v) {
    const auto count = static_cast<unsigned>(v < 0.0 ? 0.0 : v);
    if (name == "thrust_pct") {
        in.thrust_pct = v;
    } else if (name == "oil_psi") {
        in.oil_psi = v;
    } else if (name == "oil_temp_c") {
        in.oil_temp_c = v;
    } else if (name == "vib") {
        in.vib = v;
    } else if (name == "fuel_total_kg") {
        in.fuel_total_kg = v;
    } else if (name == "fuel_balance_kg") {
        in.fuel_balance_kg = v;
    } else if (name == "main_bus_v") {
        in.main_bus_v = v;
    } else if (name == "gcas_vertical_speed") {
        in.gcas_vertical_speed = v;
    } else if (name == "gcas_altitude") {
        in.gcas_altitude = v;
    } else if (name == "gcas_terrain_clearance") {
        in.gcas_terrain_clearance = v;
    } else if (name == "rwr_hostile") {
        in.rwr_hostile = count;
    } else if (name == "rwr_high_priority") {
        in.rwr_high_priority = count;
    } else if (name == "chaff_remaining") {
        in.chaff_remaining = count;
    } else if (name == "flares_remaining") {
        in.flares_remaining = count;
    } else if (name == "fused_hostile") {
        in.fused_hostile = count;
    } else if (name == "sensor_health") {
        in.sensor_health = static_cast<icd::SensorHealth>(count);
    } else if (name == "wx_windshear") {
        in.wx_windshear = static_cast<icd::ShearSeverity>(count);
    } else if (name == "wx_turbulence") {
        in.wx_turbulence = static_cast<icd::TurbulenceCategory>(count);
    } else if (name.size() == 9 && name.compare(0, 8, "hyd_psi_") == 0 && name[8] >= 'a' && name[8] <= 'c') {
        in.hyd_psi[static_cast<std::size_t>(name[8] - 'a')] = v;
    } else {
        return false;
    }
    return true;
}

void print_alerts(const cas::AlertSet& set) {
    bool any = false;
    for (std::size_t i = 0; i < cas::kAlertCount; ++i) {
        if (set[i]) {
            std::printf("%s%s", any ? " " : "", cas::name_of(static_cast<cas::Alert>(i)));
            any = true;
        }
    }
    std::printf("%s\n", any ? "" : "none");
}

}  // namespace

int main() {
    cas::AlertInputs inputs{};
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            inputs = cas::AlertInputs{};
            std::printf("ok\n");
        } else if (cmd == "set") {
            std::string name;
            double value = 0.0;
            if ((in >> name >> value) && (set_bool(inputs, name, value) || set_number(inputs, name, value))) {
                std::printf("ok\n");
            } else {
                std::printf("error unknown %s\n", name.c_str());
            }
        } else if (cmd == "eval") {
            print_alerts(cas::evaluate(inputs));
        } else if (cmd == "power") {
            std::string arg;
            in >> arg;
            if (arg == "none") {
                std::printf("%.17g\n", cas::profile_engine_power(nullptr));
            } else {
                icd::FmsStatus fms{};
                fms.flight_mode = static_cast<icd::FmsFlightMode>(std::strtoul(arg.c_str(), nullptr, 10));
                std::printf("%.17g\n", cas::profile_engine_power(&fms));
            }
        } else {
            std::printf("error bad command\n");
        }
        std::fflush(stdout);
    }
    return 0;
}
