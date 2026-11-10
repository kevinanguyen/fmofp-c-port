// The airframe systems partition process: terminal RT 20 on the bus.
//
//   fmofp_airframe [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (AFR_MODE_CMD, AFR_CMD,
// the plant's sensor readings relayed as AFR_SENSORS, the FMS's thrust and gear
// status relayed as AFR_FMS_CONTROL), run AirframeManager::step() (a new
// reading is one pass of monitor_airframe; a changed FMS gear field is a gear
// command), and load AFR_STATUS and TERM_STATUS for the bus controller to
// collect.

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/airframe/airframe_manager.hpp>
#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::AfrStatus::kRt;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::airframe::AirframeManager& afr, bus::Word last_sync) {
    Status result = load(terminal, afr.status());
    icd::TermStatus ts{};
    ts.state = afr.state();
    ts.healthy = afr.status().healthy;
    ts.last_cmd_seq = afr.status().last_cmd_seq;
    ts.cmd_rejected = afr.status().cmd_rejected;
    ts.bit_in_progress = afr.bit().in_progress;
    ts.bit_failed = afr.bit().failed;
    ts.fault_count = afr.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

fmofp::airframe::AirframeManager g_airframe;

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_airframe [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "airframe: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_airframe.init() != Status::kOk) {
        std::fprintf(stderr, "airframe: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    (void)load_outputs(terminal, g_airframe, 0);
    if (!o.quiet) {
        std::printf("airframe: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned readings = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_airframe.reset();
                (void)load_outputs(terminal, g_airframe, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_airframe.start_self_test();
        }
        terminal.set_bit(g_airframe.bit());

        icd::AfrModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_airframe.command_mode(mode_cmd);
        }
        icd::AfrCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_airframe.command(cmd, frame);
        }
        icd::AfrSensors sensors{};
        const bool have_sensors = take_fresh(terminal, sensors);
        if (have_sensors) {
            ++readings;
        }
        icd::AfrFmsControl fms{};
        const bool have_fms = take_fresh(terminal, fms);
        g_airframe.step(have_sensors ? &sensors.payload : nullptr, have_fms ? &fms.payload : nullptr, frame);
        terminal.set_subsystem_flag(g_airframe.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_airframe, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::AfrStatus& st = g_airframe.status();
            std::printf("airframe: major frame %u, state %s, strain %.0f/%.0f ue, leading edge %.1f C, gear %s%s, "
                        "readings %u\n",
                        major, icd::to_string(g_airframe.state()), st.wing_root_strain, st.fuselage_strain,
                        st.leading_edge_temp, icd::to_string(st.gear_state), st.sensors_valid ? "" : " NO READINGS",
                        readings);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("airframe: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s readings=%u\n",
                syncs, c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_airframe.state()),
                readings);
    return 0;
}
