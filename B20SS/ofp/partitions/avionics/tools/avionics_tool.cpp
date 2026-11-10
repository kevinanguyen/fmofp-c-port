// fmofp_avionics_tool: the avionics logic on stdin/stdout, so the Python tests can
// run the original LRUstatus.py, builtInTesting.py, bitControl.py, fmStatus.py and
// swConfigure.py beside it (B20SS/fmofp_bus/tests/test_avionics_oracle.py). Test
// support, not flight code.
//
// One command per line; enums are printed by their names. Masks are hexadecimal,
// bit n for RT n.
//   reset                                   -> ok
//   view <valid 0|1> <listed> <responded> <answering> <status> <healthy> <bit_failed> <normal> <degraded> <failure>
//                                           -> ok   (the bus view the commands below use)
//   update <frame>                          -> ok   (the terminal's 1 Hz pass on the view)
//   derive <empty> <running> <healthy> <OTHER|NOMINAL|DEGRADED|FAULT> <NONE|PASS|FAIL|ABORT|PENDING>
//                                           -> health   (_derive_health)
//   poll                                    -> ok   (LRUStatusMonitor._poll_all on the view)
//   resolve <key...>                        -> lru_id | -
//   force <state> <key...>                  -> lru_id | refused
//   clear <key...>                          -> count ; clear_all -> count
//   bitresult <lru_id> <status>             -> 0|1
//   lrus                                    -> count, then one line per LRU: health forced declared lru_id
//   overall                                 -> overall_health fault_count forced_count
//   post                                    -> six statuses
//   periodic <now_s>                        -> returned | five last statuses | stored BIT-AVIONICS stored BIT-COMM
//   initiated                               -> fifteen statuses
//   fitness <cpu> <memory>                  -> status
//   redundancy <component 0-2>              -> 0|1
//   load <id>                               -> 0|1
//   versions                                -> three versions, as the Python's strings

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>

#include <fmofp/avionics/avionics.hpp>

namespace {

namespace avionics = fmofp::avionics;
namespace icd = fmofp::icd;

bool parse_health(const std::string& text, icd::LruHealth& out) {
    for (const icd::LruHealth h : {icd::LruHealth::UNKNOWN, icd::LruHealth::NOMINAL, icd::LruHealth::DEGRADED,
                                   icd::LruHealth::FAULT, icd::LruHealth::OFFLINE}) {
        if (text == icd::to_string(h)) {
            out = h;
            return true;
        }
    }
    return false;
}

// NONE is "no BIT result"; the others are the result.
bool parse_bit(const std::string& text, bool& has, icd::BitStatus& out) {
    has = text != "NONE";
    if (!has) {
        return true;
    }
    for (const icd::BitStatus s :
         {icd::BitStatus::PENDING, icd::BitStatus::PASS, icd::BitStatus::FAIL, icd::BitStatus::ABORT}) {
        if (text == icd::to_string(s)) {
            out = s;
            return true;
        }
    }
    return false;
}

// The rest of the line after one separating space, as the key (it may be empty or hold spaces).
std::string rest_of(std::istringstream& in) {
    std::string rest;
    std::getline(in, rest);
    if (!rest.empty() && rest[0] == ' ') {
        rest.erase(0, 1);
    }
    return rest;
}

void print_version(const avionics::SwVersion& v) {
    if (v.has_patch) {
        std::printf("%u.%u.%u", static_cast<unsigned>(v.major), static_cast<unsigned>(v.minor),
                    static_cast<unsigned>(v.patch));
    } else {
        std::printf("%u.%u", static_cast<unsigned>(v.major), static_cast<unsigned>(v.minor));
    }
}

}  // namespace

int main() {
    static avionics::Avionics av;
    (void)av.init();
    avionics::BusView view;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            (void)av.init();
            view = avionics::BusView{};
            std::printf("ok\n");
        } else if (cmd == "view") {
            int valid = 0;
            in >> valid >> std::hex >> view.listed >> view.responded >> view.answering >> view.status >>
                view.healthy >> view.bit_failed >> view.normal >> view.degraded >> view.failure;
            view.valid = valid != 0;
            std::printf(in ? "ok\n" : "error view\n");
        } else if (cmd == "update") {
            std::uint32_t frame = 0;
            in >> frame;
            av.update(view, frame);
            std::printf("ok\n");
        } else if (cmd == "derive") {
            int empty = 0;
            int running = 0;
            int healthy = 0;
            std::string health;
            std::string bit;
            in >> empty >> running >> healthy >> health >> bit;
            avionics::SystemStatus status;
            status.empty = empty != 0;
            status.running = running != 0;
            status.healthy = healthy != 0;
            status.health = health == "NOMINAL"    ? avionics::ReportedHealth::kNominal
                            : health == "DEGRADED" ? avionics::ReportedHealth::kDegraded
                            : health == "FAULT"    ? avionics::ReportedHealth::kFault
                                                   : avionics::ReportedHealth::kOther;
            bool has_bit = false;
            icd::BitStatus bit_result = icd::BitStatus::PENDING;
            if (!in || !parse_bit(bit, has_bit, bit_result)) {
                std::printf("error derive\n");
                continue;
            }
            std::printf("%s\n", icd::to_string(avionics::derive_health(status, has_bit, bit_result)));
        } else if (cmd == "poll") {
            av.lrus().poll(view);
            std::printf("ok\n");
        } else if (cmd == "resolve") {
            const std::size_t index = av.lrus().resolve(rest_of(in).c_str());
            std::printf("%s\n", index == avionics::kMaxLrus ? "-" : av.lrus().at(index).lru_id.data());
        } else if (cmd == "force") {
            std::string state;
            in >> state;
            icd::LruHealth health = icd::LruHealth::FAULT;
            if (!parse_health(state, health)) {
                std::printf("error force\n");
                continue;
            }
            const std::size_t index = av.lrus().force_fault(rest_of(in).c_str(), health);
            std::printf("%s\n", index == avionics::kMaxLrus ? "refused" : av.lrus().at(index).lru_id.data());
        } else if (cmd == "clear") {
            std::printf("%zu\n", av.lrus().clear_forced_fault(rest_of(in).c_str()));
        } else if (cmd == "clear_all") {
            std::printf("%zu\n", av.lrus().clear_forced_fault(nullptr));
        } else if (cmd == "bitresult") {
            std::string id;
            std::string status;
            in >> id >> status;
            bool has = false;
            icd::BitStatus result = icd::BitStatus::PENDING;
            if (!parse_bit(status, has, result) || !has) {
                std::printf("error bitresult\n");
                continue;
            }
            std::printf("%d\n", av.lrus().update_bit_result(id.c_str(), result) ? 1 : 0);
        } else if (cmd == "lrus") {
            std::printf("%zu\n", av.lrus().count());
            for (std::size_t i = 0; i < av.lrus().count(); ++i) {
                const avionics::Lru& lru = av.lrus().at(i);
                std::printf("%s %d %d %s\n", icd::to_string(lru.health), lru.forced ? 1 : 0, lru.declared ? 1 : 0,
                            lru.lru_id.data());
            }
        } else if (cmd == "overall") {
            std::printf("%s %zu %zu\n", icd::to_string(av.lrus().overall_health()), av.lrus().fault_count(),
                        av.lrus().forced_count());
        } else if (cmd == "post") {
            av.tests().run_post(view);
            for (const icd::BitStatus s : av.tests().post_results()) {
                std::printf("%s ", icd::to_string(s));
            }
            std::printf("\n");
        } else if (cmd == "periodic") {
            double now_s = 0.0;
            in >> now_s;
            std::printf("%zu |", av.tests().run_due(now_s, view));
            for (const icd::BitStatus s : av.tests().periodic_results()) {
                std::printf(" %s", icd::to_string(s));
            }
            std::printf(" | %u %u\n", static_cast<unsigned>(av.tests().stored(0)),
                        static_cast<unsigned>(av.tests().stored(1)));
        } else if (cmd == "initiated") {
            const avionics::InitiatedSummary summary = av.tests().run_all(view);
            for (const icd::BitStatus s : summary.results) {
                std::printf("%s ", icd::to_string(s));
            }
            std::printf("\n");
        } else if (cmd == "fitness") {
            int cpu = 0;
            int memory = 0;
            in >> cpu >> memory;
            std::printf("%s\n", icd::to_string(avionics::FmFitness::check_thresholds(cpu, memory)));
        } else if (cmd == "redundancy") {
            unsigned component = 0;
            in >> component;
            const icd::FitnessComponent which = component == 0U   ? icd::FitnessComponent::FLIGHT_CONTROL_FITNESS
                                                : component == 1U ? icd::FitnessComponent::NAVIGATION_FITNESS
                                                                  : icd::FitnessComponent::AVIONICS_FITNESS;
            std::printf("%d\n", av.fitness().handle_redundancy(which) ? 1 : 0);
        } else if (cmd == "load") {
            std::uint32_t id = 0;
            in >> id;
            std::printf("%d\n", av.software().perform_update(id) ? 1 : 0);
        } else if (cmd == "versions") {
            for (std::size_t i = 0; i < avionics::kSwComponents; ++i) {
                print_version(av.software().version(i));
                std::printf(i + 1 < avionics::kSwComponents ? " " : "\n");
            }
        } else {
            std::printf("error unknown command\n");
        }
        std::fflush(stdout);
    }
    return 0;
}
