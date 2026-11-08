// fmofp_sensor_tool: the sensor management logic on stdin/stdout, so the Python
// tests can run the original sensorService.py and sensorDataFusion.py beside it
// (B20SS/fmofp_bus/tests/test_sensor_oracle.py). Test support, not flight code.
//
// One command per line; numbers are printed with 17 significant digits, enums by
// their names, a value the Python held as None as "-".
//   reset                                         -> ok
//   sensor <id> <on 0|1>                          -> 0|1   (id: the sensor_id enum's number)
//   scan_begin <epoch>                            -> ok    (a scan set is present at the next update)
//   radar <sensor> <distance> <angle> <speed>     -> ok    (sensor: 0 main radar, 1 terrain-following radar)
//   lidar <distance> <azimuth> <elevation>        -> ok
//   ir <sensor> <temperature> <angle> <distance>  -> ok    (sensor: 3 FLIR, 4 MAWS)
//   esm_begin <epoch>                             -> ok    (an ESM set is present at the next update)
//   signal <freq_mhz> <strength_dbm> <bearing> <range_nm> -> ok
//   update <frame>                                -> ok    (the 5 Hz body on what was staged; the staging is cleared)
//   data                                          -> health main tfr lidar flir maws esm contacts dropped sequence
//   contacts                                      -> lines "id origin source class range bearing elevation speed
//                                                    frequency signal band confidence last_seen corroborated"
//                                                    in table order, then "end"

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fmofp/sensor/sensor_management.hpp>

namespace {

namespace sensor = fmofp::sensor;
namespace icd = fmofp::icd;

bool read(std::istringstream& in, std::vector<double>& out, std::size_t count) {
    out.clear();
    double value = 0.0;
    while (out.size() < count && in >> value) {
        out.push_back(value);
    }
    return out.size() == count;
}

std::uint8_t byte(double v) { return static_cast<std::uint8_t>(v); }

void print_optional(bool present, double value) {
    if (present) {
        std::printf(" %.17g", value);
    } else {
        std::printf(" -");
    }
}

void print_corroborated(std::uint8_t mask) {
    static const char* const names[] = {"RADAR", "LIDAR", "IR", "ESM"};
    bool any = false;
    std::printf(" ");
    for (unsigned i = 0; i < 4; ++i) {
        if ((mask & (1U << i)) != 0) {
            std::printf(any ? ",%s" : "%s", names[i]);
            any = true;
        }
    }
    if (!any) {
        std::printf("-");
    }
}

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
    icd::PlantSensorScan scan{};
    bool scan_present{false};
    icd::PlantEsm esm{};
    bool esm_present{false};

    void clear() {
        scan = icd::PlantSensorScan{};
        scan_present = false;
        esm = icd::PlantEsm{};
        esm_present = false;
    }
};

}  // namespace

int main() {
    sensor::SensorManagement sm;
    (void)sm.init();
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
            (void)sm.init();
            staged.clear();
            std::printf("ok\n");
        } else if (cmd == "sensor" && read(in, a, 2)) {
            std::printf("%d\n", sm.set_active(static_cast<icd::SensorId>(byte(a[0])), a[1] != 0.0) ? 1 : 0);
        } else if (cmd == "scan_begin" && read(in, a, 1)) {
            staged.scan = icd::PlantSensorScan{};
            staged.scan.epoch = byte(a[0]);
            staged.scan_present = true;
            std::printf("ok\n");
        } else if (cmd == "radar" && read(in, a, 4)) {
            if (staged.scan.radar_count < icd::PlantSensorScan::kMaxRadar) {
                icd::PlantSensorScanRadar& r = staged.scan.radar[staged.scan.radar_count++];
                r.sensor = static_cast<icd::SensorId>(byte(a[0]));
                r.distance = a[1];
                r.angle = a[2];
                r.speed = a[3];
                staged.scan_present = true;
                std::printf("ok\n");
            } else {
                std::printf("error full\n");
            }
        } else if (cmd == "lidar" && read(in, a, 3)) {
            if (staged.scan.lidar_count < icd::PlantSensorScan::kMaxLidar) {
                icd::PlantSensorScanLidar& p = staged.scan.lidar[staged.scan.lidar_count++];
                p.distance = a[0];
                p.azimuth = a[1];
                p.elevation = a[2];
                staged.scan_present = true;
                std::printf("ok\n");
            } else {
                std::printf("error full\n");
            }
        } else if (cmd == "ir" && read(in, a, 4)) {
            if (staged.scan.infrared_count < icd::PlantSensorScan::kMaxInfrared) {
                icd::PlantSensorScanInfrared& o = staged.scan.infrared[staged.scan.infrared_count++];
                o.sensor = static_cast<icd::SensorId>(byte(a[0]));
                o.temperature = a[1];
                o.angle = a[2];
                o.distance = a[3];
                staged.scan_present = true;
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
            if (staged.esm.count < 5) {
                set_signal(staged.esm, staged.esm.count, a[0], a[1], a[2], a[3]);
                ++staged.esm.count;
                staged.esm_present = true;
                std::printf("ok\n");
            } else {
                std::printf("error full\n");
            }
        } else if (cmd == "update" && read(in, a, 1)) {
            sm.update(staged.scan_present ? &staged.scan : nullptr, staged.esm_present ? &staged.esm : nullptr,
                      static_cast<std::uint32_t>(a[0]));
            staged.clear();
            std::printf("ok\n");
        } else if (cmd == "data") {
            const icd::SnsStatus& s = sm.status();
            std::printf("%s %u %u %u %u %u %u %u %u %u\n", icd::to_string(s.health), s.main_radar_active ? 1U : 0U,
                        s.tfr_radar_active ? 1U : 0U, s.lidar_active ? 1U : 0U, s.flir_active ? 1U : 0U,
                        s.maws_active ? 1U : 0U, s.esm_active ? 1U : 0U, s.contact_count, s.dropped, s.sequence);
        } else if (cmd == "contacts") {
            for (std::size_t i = 0; i < sm.contact_count(); ++i) {
                const sensor::Contact& c = sm.contact(i);
                std::printf("%u %s %s %s", c.id, sensor::to_string(c.origin), sensor::to_string(c.source),
                            sensor::to_string(c.contact_class));
                print_optional(c.has_range, c.range_m);
                print_optional(c.has_bearing, c.bearing_deg);
                print_optional(c.has_elevation, c.elevation_deg);
                print_optional(c.has_speed, c.speed_ms);
                print_optional(c.has_frequency, c.frequency_hz);
                print_optional(c.has_frequency, c.signal_dbm);
                std::printf(" %s %.17g %u", c.has_frequency ? icd::to_string(c.band) : "-", c.confidence, c.last_seen);
                print_corroborated(c.corroborated);
                std::printf("\n");
            }
            std::printf("end\n");
        } else {
            std::printf("error unknown command\n");
        }
    }
    return 0;
}
