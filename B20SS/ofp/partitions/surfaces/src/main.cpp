// The flight surfaces partition process: terminal RT 21 on the bus.
//
//   fmofp_surfaces [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (FSF_MODE_CMD, FSF_CMD,
// the plant's sensed flight state relayed as FSF_SENSORS), run
// FlightSurfaces::step() (the ailerons, elevators and slats re-commanded from
// the roll, pitch and angle of attack; every surface one step toward its
// command), and load FSF_STATUS, FSF_POSITIONS and TERM_STATUS for the bus
// controller to collect.

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>
#include <fmofp/surfaces/flight_surfaces.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;
namespace surfaces = fmofp::surfaces;

constexpr std::uint8_t kRt = icd::FsfStatus::kRt;

struct Options {
    fmofp::rt::RtProcessConfig rt{};
    unsigned long syncs{0};
    bool quiet{false};
};

bool parse_number(const char* text, unsigned long max, unsigned long& out) {
    if (text == nullptr) {
        return false;
    }
    char* end = nullptr;
    const unsigned long v = std::strtoul(text, &end, 10);
    if (end == text || *end != '\0' || v > max) {
        return false;
    }
    out = v;
    return true;
}

bool parse(int argc, char** argv, Options& o) {
    o.rt.rt = kRt;
    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];
        const char* next = i + 1 < argc ? argv[i + 1] : nullptr;
        unsigned long v = 0;
        if (std::strcmp(a, "--port-base") == 0 && parse_number(next, 65000, v)) {
            o.rt.port_base = static_cast<std::uint16_t>(v);
            ++i;
        } else if (std::strcmp(a, "--syncs") == 0 && parse_number(next, 1000000000UL, v)) {
            o.syncs = v;
            ++i;
        } else if (std::strcmp(a, "--quiet") == 0) {
            o.quiet = true;
        } else {
            return false;
        }
    }
    return true;
}

template <typename Message>
bool take_fresh(bus::RemoteTerminal& terminal, Message& out) {
    typename Message::Words words{};
    std::uint8_t count = 0;
    bool fresh = false;
    if (terminal.get_received(Message::kSubaddress, words.data(), Message::kWords, count, fresh) != Status::kOk ||
        !fresh || count != Message::kWords) {
        return false;
    }
    return Message::decode(words, out) == Status::kOk;
}

template <typename Message>
Status load(bus::RemoteTerminal& terminal, const Message& message) {
    typename Message::Words words{};
    const Status s = message.encode(words);
    if (!fmofp::ok(s)) {
        return s;
    }
    return terminal.set_transmit(Message::kSubaddress, words.data(), Message::kWords);
}

Status load_outputs(bus::RemoteTerminal& terminal, const surfaces::FlightSurfaces& fs, bus::Word last_sync) {
    Status result = load(terminal, fs.status());
    result = fmofp::worst(result, load(terminal, fs.positions()));
    icd::TermStatus ts{};
    ts.state = fs.state();
    ts.healthy = fs.status().healthy;
    ts.last_cmd_seq = fs.status().last_cmd_seq;
    ts.cmd_rejected = fs.status().cmd_rejected;
    ts.bit_in_progress = fs.bit().in_progress;
    ts.bit_failed = fs.bit().failed;
    ts.fault_count = fs.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

surfaces::FlightSurfaces g_surfaces;

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_surfaces [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "surfaces: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_surfaces.init() != Status::kOk) {
        std::fprintf(stderr, "surfaces: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    (void)load_outputs(terminal, g_surfaces, 0);
    if (!o.quiet) {
        std::printf("surfaces: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned sensor_frames = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_surfaces.reset();
                (void)load_outputs(terminal, g_surfaces, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_surfaces.start_self_test();
        }
        terminal.set_bit(g_surfaces.bit());

        icd::FsfModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_surfaces.command_mode(mode_cmd);
        }
        icd::FsfCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_surfaces.command(cmd, frame);
        }
        icd::FsfSensors sensors{};
        const bool have_sensors = take_fresh(terminal, sensors);
        if (have_sensors) {
            ++sensor_frames;
        }
        g_surfaces.step(have_sensors ? &sensors.payload : nullptr, frame);
        terminal.set_subsystem_flag(g_surfaces.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_surfaces, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::FsfPositions& p = g_surfaces.positions();
            const icd::FsfStatus& st = g_surfaces.status();
            std::printf("surfaces: major frame %u, state %s, ail %+.1f/%+.1f el %+.1f rud %+.1f flaps %.1f (detent %.0f) "
                        "slats %.1f sb %.1f trim %+.2f/%+.2f/%+.2f%s, sensor frames %u\n",
                        major, icd::to_string(g_surfaces.state()), p.aileron_l, p.aileron_r, p.elevator_l, p.rudder,
                        p.flap_l, st.flap_cmd, p.slat_l, p.speedbrake, st.trim_pitch, st.trim_roll, st.trim_yaw,
                        st.sensors_valid ? "" : " NO SENSORS", sensor_frames);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("surfaces: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s sensor_frames=%u\n",
                syncs, c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_surfaces.state()),
                sensor_frames);
    return 0;
}
