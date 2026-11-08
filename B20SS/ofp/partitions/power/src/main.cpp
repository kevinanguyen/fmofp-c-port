// The power management partition process: terminal RT 8 on the bus.
//
//   fmofp_power [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (PWR_MODE_CMD, PWR_CMD,
// the plant's electrical reading relayed as PWR_ELECTRICAL), run
// PowerManagement::step(), and load PWR_STATUS, PWR_GEN_CMD and TERM_STATUS for
// the bus controller to collect. The status reaches the EICAS by relay; the
// generator command reaches the plant by relay.

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/power/power_management.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::PwrStatus::kRt;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::power::PowerManagement& pm, bus::Word last_sync) {
    Status result = load(terminal, pm.status());
    result = fmofp::worst(result, load(terminal, pm.gen_cmd()));
    icd::TermStatus ts{};
    ts.state = pm.state();
    ts.healthy = pm.status().healthy;
    ts.last_cmd_seq = pm.status().last_cmd_seq;
    ts.cmd_rejected = pm.status().cmd_rejected;
    ts.bit_in_progress = pm.bit().in_progress;
    ts.bit_failed = pm.bit().failed;
    ts.fault_count = pm.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

fmofp::power::PowerManagement g_power;

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_power [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "power: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_power.init() != Status::kOk) {
        std::fprintf(stderr, "power: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    (void)load_outputs(terminal, g_power, 0);
    if (!o.quiet) {
        std::printf("power: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned readings = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_power.reset();
                (void)load_outputs(terminal, g_power, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_power.start_self_test();
        }
        terminal.set_bit(g_power.bit());

        icd::PwrModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_power.command_mode(mode_cmd);
        }
        icd::PwrCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_power.command(cmd, frame);
        }
        icd::PwrElectrical electrical{};
        const bool have_electrical = take_fresh(terminal, electrical);
        if (have_electrical) {
            ++readings;
        }
        g_power.step(have_electrical ? &electrical.payload : nullptr, frame);
        terminal.set_subsystem_flag(g_power.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_power, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::PwrStatus& st = g_power.status();
            std::printf("power: major frame %u, state %s, gen %.0f kW cons %.0f kW bal %+.0f%s, main %.1f %% emerg %.1f %% "
                        "apu %.1f %%, coolant %.1f C (%s, fan %.0f %%) cabin %.1f C, readings %u\n",
                        major, icd::to_string(g_power.state()), st.generator_output, st.total_power_consumption,
                        st.power_balance, st.generator_online ? "" : " GEN OFF", st.main_battery_charge,
                        st.emergency_battery_charge, st.apu_battery_charge, st.coolant_temp,
                        icd::to_string(st.thermal_status), st.fan_pct, st.cabin_temp, readings);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("power: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s readings=%u\n", syncs,
                c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_power.state()), readings);
    return 0;
}
