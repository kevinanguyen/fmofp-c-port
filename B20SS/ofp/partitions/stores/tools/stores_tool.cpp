// fmofp_stores_tool: the stores management logic on stdin/stdout, so the Python
// tests can run the frozen sms.py beside it (B20SS/fmofp_bus/tests/test_stores_oracle.py).
// Test support, not flight code.
//
// One command per line; enums by number in, by name out.
//   reset                       -> ok   (the default loadout, master arm SAFE)
//   arm <weapons>|none          -> the master arm the FMS's weapons state gives (none: the FMS not heard); applied
//   cmd <command> <station> <release> <delivery>  -> the command's outcome (cmd_status)
//   table                       -> eleven lines "kind state qty"
//   sums                        -> "total_weight_kg armed_count"
//   modes                       -> "release delivery selected released jettisoned"

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>

#include <fmofp/stores/stores_management.hpp>

namespace {

namespace stores = fmofp::stores;
namespace icd = fmofp::icd;

std::uint8_t number(const std::string& text) {
    return static_cast<std::uint8_t>(std::strtoul(text.c_str(), nullptr, 10));
}

}  // namespace

int main() {
    stores::StoresManagement sms;
    (void)sms.init();
    std::uint8_t seq = 0;
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            (void)sms.init();
            std::printf("ok\n");
        } else if (cmd == "arm") {
            std::string arg;
            in >> arg;
            icd::MasterArm arm = stores::master_arm_from(nullptr);
            if (arg != "none") {
                icd::FmsStatus fms{};
                fms.weapons = static_cast<icd::WeaponsState>(number(arg));
                arm = stores::master_arm_from(&fms);
            }
            sms.set_master_arm(arm);
            std::printf("%s\n", icd::to_string(arm));
        } else if (cmd == "cmd") {
            std::string c;
            std::string station;
            std::string release;
            std::string delivery;
            in >> c >> station >> release >> delivery;
            icd::SmsCmd m{};
            seq = static_cast<std::uint8_t>(seq == 255U ? 1U : seq + 1U);
            m.cmd_seq = seq;
            m.command = static_cast<icd::SmsCommand>(number(c));
            m.station = number(station);
            m.release_mode = static_cast<icd::ReleaseMode>(number(release));
            m.delivery_mode = static_cast<icd::DeliveryMode>(number(delivery));
            sms.command(m);
            std::printf("%s\n", icd::to_string(sms.status().sms_cmd_status));
        } else if (cmd == "table") {
            for (const stores::Station& st : sms.loadout()) {
                std::printf("%s %s %u\n", icd::to_string(st.kind), icd::to_string(st.state), st.qty);
            }
        } else if (cmd == "sums") {
            std::printf("%.17g %u\n", stores::total_weight_kg(sms.loadout()), stores::armed_count(sms.loadout()));
        } else if (cmd == "modes") {
            const icd::SmsStatus& st = sms.status();
            std::printf("%s %s %u %u %u\n", icd::to_string(st.release_mode), icd::to_string(st.delivery_mode),
                        st.selected_station, st.stores_released, st.jettisoned ? 1U : 0U);
        } else {
            std::printf("error bad command\n");
        }
        std::fflush(stdout);
    }
    return 0;
}
