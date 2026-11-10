// fmofp_surfaces_tool: the flight surfaces logic on stdin/stdout, so the Python
// tests can run the original flightSurfaceService.py beside it
// (B20SS/fmofp_bus/tests/test_surfaces_oracle.py). Test support, not flight code.
//
// One command per line; numbers are printed with 17 significant digits, enums by
// their names.
//   reset                         -> ok
//   sensors <roll> <pitch> <aoa>  -> ok   (_sync_from_fcc with the flight control computer's data)
//   step <dt>                     -> ok   (_step_all(dt): every surface one step)
//   flaps <deg>                   -> ok   (set_flaps)
//   speedbrake <pct>              -> ok   (set_speedbrake)
//   rudder <deg>                  -> ok   (set_rudder)
//   trim <pitch|roll|yaw> <deg>   -> ok | error bad axis   (set_trim)
//   data    -> the ten positions in _all's order (aileron_l aileron_r elevator_l elevator_r rudder flap_l flap_r
//              slat_l slat_r speedbrake), flap_cmd, trim pitch roll yaw, healthy   (get_data(), unrounded)
//   status  -> state cmd_status sensors_valid slats_extended healthy   (sensors_valid as of the last frame, which
//              the loop's halves do not run: 0 here)

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fmofp/surfaces/flight_surfaces.hpp>

namespace {

namespace surfaces = fmofp::surfaces;
namespace icd = fmofp::icd;

bool read(std::istringstream& in, std::vector<double>& out, std::size_t count) {
    out.clear();
    double value = 0.0;
    while (out.size() < count && in >> value) {
        out.push_back(value);
    }
    return out.size() == count;
}

bool axis_of(const std::string& name, icd::TrimAxis& axis) {
    if (name == "pitch") {
        axis = icd::TrimAxis::PITCH;
    } else if (name == "roll") {
        axis = icd::TrimAxis::ROLL;
    } else if (name == "yaw") {
        axis = icd::TrimAxis::YAW;
    } else {
        return false;
    }
    return true;
}

}  // namespace

int main() {
    surfaces::FlightSurfaces fs;
    (void)fs.init();
    std::string line;
    std::vector<double> a;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd) || cmd.empty() || cmd[0] == '#') {
            continue;
        }
        if (cmd == "reset") {
            (void)fs.init();
            std::printf("ok\n");
        } else if (cmd == "sensors" && read(in, a, 3)) {
            fs.sync_from_fcc(a[0], a[1], a[2]);
            std::printf("ok\n");
        } else if (cmd == "step" && read(in, a, 1)) {
            fs.step_all(a[0]);
            std::printf("ok\n");
        } else if (cmd == "flaps" && read(in, a, 1)) {
            fs.set_flaps(a[0]);
            std::printf("ok\n");
        } else if (cmd == "speedbrake" && read(in, a, 1)) {
            fs.set_speedbrake(a[0]);
            std::printf("ok\n");
        } else if (cmd == "rudder" && read(in, a, 1)) {
            fs.set_rudder(a[0]);
            std::printf("ok\n");
        } else if (cmd == "trim") {
            std::string name;
            icd::TrimAxis axis = icd::TrimAxis::PITCH;
            if (in >> name && axis_of(name, axis) && read(in, a, 1)) {
                (void)fs.set_trim(axis, a[0]);
                std::printf("ok\n");
            } else {
                std::printf("error bad axis\n");
            }
        } else if (cmd == "data") {
            for (std::size_t i = 0; i < surfaces::kSurfaceCount; ++i) {
                std::printf("%.17g ", fs.surface(static_cast<surfaces::SurfaceId>(i)).position);
            }
            std::printf("%.17g %.17g %.17g %.17g %d\n", fs.flap_cmd(), fs.trim(icd::TrimAxis::PITCH),
                        fs.trim(icd::TrimAxis::ROLL), fs.trim(icd::TrimAxis::YAW), fs.all_healthy() ? 1 : 0);
        } else if (cmd == "status") {
            const icd::FsfStatus& s = fs.status();
            // The message is filled by the frame (step()); the loop's halves leave it, so the slats and the
            // health are read live.
            std::printf("%s %s %d %d %d\n", icd::to_string(s.state), icd::to_string(s.surface_cmd_status),
                        s.sensors_valid ? 1 : 0, fs.slats_extended() ? 1 : 0, fs.all_healthy() ? 1 : 0);
        } else {
            std::printf("error unknown command\n");
        }
    }
    return 0;
}
