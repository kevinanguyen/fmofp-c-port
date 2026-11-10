// The flight data monitoring partition process: terminal RT 23 on the bus.
//
//   fmofp_fdm [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (FDM_MODE_CMD, FDM_CMD,
// the FMS flight data heard by broadcast), run FlightDataRecorder::step()
// (a record every 25 frames while the flight data is fresh), and load
// FDM_STATUS and TERM_STATUS for the bus controller to collect.

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/fdm/flight_data_recorder.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::FdmStatus::kRt;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::fdm::FlightDataRecorder& fdm, bus::Word last_sync) {
    Status result = load(terminal, fdm.status());
    icd::TermStatus ts{};
    ts.state = fdm.state();
    ts.healthy = fdm.status().healthy;
    ts.last_cmd_seq = fdm.status().last_cmd_seq;
    ts.cmd_rejected = fdm.status().cmd_rejected;
    ts.bit_in_progress = fdm.bit().in_progress;
    ts.bit_failed = fdm.bit().failed;
    ts.fault_count = fdm.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

fmofp::fdm::FlightDataRecorder g_fdm;

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_fdm [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "fdm: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_fdm.init() != Status::kOk) {
        std::fprintf(stderr, "fdm: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    // The flight data recorder hears the FMS flight data by broadcast (ICD README section 8).
    if (terminal.accept_broadcast(icd::BcastFmsFlightData::kSubaddress) != Status::kOk) {
        std::fprintf(stderr, "fdm: cannot accept the flight data broadcast\n");
        return 1;
    }
    (void)load_outputs(terminal, g_fdm, 0);
    if (!o.quiet) {
        std::printf("fdm: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned flight_data_frames = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_fdm.reset();
                (void)load_outputs(terminal, g_fdm, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_fdm.start_self_test();
        }
        terminal.set_bit(g_fdm.bit());

        icd::FdmModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_fdm.command_mode(mode_cmd);
        }
        icd::FdmCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_fdm.command(cmd, frame);
        }
        icd::BcastFmsFlightData flight_data{};
        const bool have_flight_data = take_fresh(terminal, flight_data);
        if (have_flight_data) {
            ++flight_data_frames;
        }
        g_fdm.step(have_flight_data ? &flight_data.payload : nullptr, frame);
        terminal.set_subsystem_flag(g_fdm.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_fdm, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::FdmStatus& st = g_fdm.status();
            std::printf("fdm: major frame %u, state %s, %.0f records (%.0f held), last alt %.0f ft ias %.1f kt at frame "
                        "%.0f, cards %s/%s%s, flight data frames %u\n",
                        major, icd::to_string(g_fdm.state()), st.records, st.held, st.last_altitude, st.last_airspeed,
                        st.last_frame, st.slot_1_present ? "FDR" : "-", st.slot_2_present ? "CVR" : "-",
                        st.flight_data_valid ? "" : " NO FLIGHT DATA", flight_data_frames);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("fdm: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s records=%u\n", syncs,
                c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_fdm.state()), g_fdm.records());
    return 0;
}
