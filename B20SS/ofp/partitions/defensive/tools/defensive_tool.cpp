// fmofp_defensive_tool: the defensive systems logic on stdin/stdout, so the
// Python tests can run the original defensiveService.py beside it
// (B20SS/fmofp_bus/tests/test_defensive_oracle.py). Test support, not flight code.
//
// One command per line; every number is printed with 17 significant digits,
// enums by their ICD names.
//   reset                                            -> ok
//   fused_begin                                      -> ok   (a fused tracks block is present at the next update)
//   track <id> <class> <hostile> <x> <y> <z>         -> ok   (class: the target_class enum's number; hostile 0|1)
//   esm_begin <epoch>                                -> ok   (a new ESM detection set at the next update)
//   signal <freq_mhz> <strength_dbm> <bearing> <range_nm> -> ok
//   update <frame>                                   -> ok   (the 2 Hz body on what was staged; the staging is cleared)
//   chaff <count>                                    -> released
//   flares <frame> <count>                           -> released
//   ecm <mode>                                       -> 0|1  (mode: the ecm_mode enum's number)
//   inject <frame> <id> <bearing> <range> <band> <type> <priority> -> 0|1  (band, type: the enums' numbers)
//   data                                             -> chaff flares ecm jamming contacts high_priority auto_salvos
//                                                       cooldown chaff_released flares_released (as of the last call)
//   contacts                                         -> lines "source id bearing range band type priority hostile"
//                                                       in get_rwr_contacts() order, then "end"

#include <cstdio>
#include <initializer_list>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fmofp/defensive/defensive_systems.hpp>

namespace {

namespace defensive = fmofp::defensive;
namespace icd = fmofp::icd;

void print(std::initializer_list<double> values) {
    bool first = true;
    for (const double v : values) {
        std::printf(first ? "%.17g" : " %.17g", v);
        first = false;
    }
    std::printf("\n");
}

bool read(std::istringstream& in, std::vector<double>& out, std::size_t count) {
    out.clear();
    double value = 0.0;
    while (out.size() < count && in >> value) {
        out.push_back(value);
    }
    return out.size() == count;
}

std::uint8_t byte(double v) { return static_cast<std::uint8_t>(v); }

void set_signal(icd::PlantEsm& e, std::size_t i, double frequency, double strength, double bearing, double range) {
    switch (i) {
        case 0:
            e.frequency_1 = frequency;
            e.strength_1 = strength;
            e.bearing_1 = bearing;
            e.range_1 = range;
            break;
        case 1:
            e.frequency_2 = frequency;
            e.strength_2 = strength;
            e.bearing_2 = bearing;
            e.range_2 = range;
            break;
        case 2:
            e.frequency_3 = frequency;
            e.strength_3 = strength;
            e.bearing_3 = bearing;
            e.range_3 = range;
            break;
        case 3:
            e.frequency_4 = frequency;
            e.strength_4 = strength;
            e.bearing_4 = bearing;
            e.range_4 = range;
            break;
        default:
            e.frequency_5 = frequency;
            e.strength_5 = strength;
            e.bearing_5 = bearing;
            e.range_5 = range;
            break;
    }
}

struct Staging {
    icd::RdrFusedTracks fused{};
    bool fused_present{false};
    icd::PlantEsm esm{};
    bool esm_present{false};

    void clear() {
        fused = icd::RdrFusedTracks{};
        fused_present = false;
        esm = icd::PlantEsm{};
        esm_present = false;
    }
};

}  // namespace

int main() {
    defensive::DefensiveSystems ds;
    (void)ds.init();
    Staging staged;
    std::string line;
    std::vector<double> a;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            (void)ds.init();
            staged.clear();
            std::printf("ok\n");
        } else if (cmd == "fused_begin") {
            staged.fused = icd::RdrFusedTracks{};
            staged.fused_present = true;
            std::printf("ok\n");
        } else if (cmd == "track" && read(in, a, 6)) {
            if (staged.fused.track_count < icd::RdrFusedTracks::kMaxTrack) {
                icd::RdrFusedTracksTrack& t = staged.fused.track[staged.fused.track_count++];
                t.track_id = static_cast<std::uint16_t>(a[0]);
                t.classification = static_cast<icd::TargetClass>(byte(a[1]));
                t.threat = a[2] != 0.0 ? icd::Threat::HOSTILE : icd::Threat::UNKNOWN;
                t.x = a[3];
                t.y = a[4];
                t.z = a[5];
                staged.fused_present = true;
                std::printf("ok\n");
            } else {
                std::printf("error full\n");
            }
        } else if (cmd == "esm_begin" && read(in, a, 1)) {
            staged.esm = icd::PlantEsm{};
            staged.esm.epoch = byte(a[0]);
            staged.esm_present = true;
            std::printf("ok\n");
        } else if (cmd == "signal" && read(in, a, 4)) {
            if (staged.esm.count < defensive::kMaxEsmSignals) {
                set_signal(staged.esm, staged.esm.count, a[0], a[1], a[2], a[3]);
                ++staged.esm.count;
                staged.esm_present = true;
                std::printf("ok\n");
            } else {
                std::printf("error full\n");
            }
        } else if (cmd == "update" && read(in, a, 1)) {
            ds.update_rwr(staged.fused_present ? &staged.fused : nullptr, staged.esm_present ? &staged.esm : nullptr,
                          static_cast<std::uint32_t>(a[0]));
            staged.clear();
            std::printf("ok\n");
        } else if (cmd == "chaff" && read(in, a, 1)) {
            print({static_cast<double>(ds.dispense_chaff(byte(a[0])))});
        } else if (cmd == "flares" && read(in, a, 2)) {
            print({static_cast<double>(ds.dispense_flares(byte(a[1]), static_cast<std::uint32_t>(a[0])))});
        } else if (cmd == "ecm" && read(in, a, 1)) {
            print({ds.set_ecm_mode(static_cast<icd::EcmMode>(byte(a[0]))) ? 1.0 : 0.0});
        } else if (cmd == "inject" && read(in, a, 7)) {
            print({ds.inject_threat(byte(a[1]), a[2], a[3], static_cast<icd::RwrBand>(byte(a[4])),
                                    static_cast<icd::ThreatType>(byte(a[5])), byte(a[6]),
                                    static_cast<std::uint32_t>(a[0]))
                       ? 1.0
                       : 0.0});
        } else if (cmd == "data") {
            const icd::DefStatus& s = ds.status();
            std::printf("%u %u %s %u %u %u %u %u %u %u\n", s.chaff_remaining, s.flares_remaining, icd::to_string(s.ecm_mode),
                        s.jamming_active ? 1U : 0U, s.contact_count, s.high_priority_count, s.auto_salvos,
                        s.cooldown_frames, s.chaff_released, s.flares_released);
        } else if (cmd == "contacts") {
            ds.refresh_contacts();  // get_rwr_contacts() read the live table, not the last published block
            const icd::DefRwrContacts& c = ds.contacts();
            for (std::size_t i = 0; i < c.contact_count && i < c.contact.size(); ++i) {
                const icd::DefRwrContactsContact& r = c.contact[i];
                std::printf("%s %u %.17g %.17g %s %s %u %u\n", icd::to_string(r.source), r.id, r.bearing, r.range,
                            icd::to_string(r.band), icd::to_string(r.threat_type), r.priority, r.hostile ? 1U : 0U);
            }
            std::printf("end\n");
        } else {
            std::printf("error unknown command\n");
        }
    }
    return 0;
}
