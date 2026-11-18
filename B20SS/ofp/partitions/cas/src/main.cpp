// The crew alerting partition process: terminal RT 26 on the bus.
//
//   fmofp_cas [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (CAS_MODE_CMD; the FMS
// status, GCAS alerts, flight envelope, engine and fuel status and weather scan
// heard by broadcast; the defensive, sensor, power and hydraulics statuses by
// their relays; the fused tracks and radar warning contacts blocks by
// broadcast), run CrewAlerting::step(), and load CAS_ALERTS and TERM_STATUS.
// CAS_ALERTS reaches the EICAS by relay.

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/block.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/cas/crew_alerting.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::CasAlerts::kRt;
using FusedIn = icd::BcastRdrFusedTracks;
using ContactsIn = icd::BcastDefRwrContacts;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::cas::CrewAlerting& cas, bus::Word last_sync) {
    Status result = load(terminal, cas.status());
    icd::TermStatus ts{};
    ts.state = cas.state();
    ts.healthy = cas.status().healthy;
    ts.last_cmd_seq = cas.status().last_cmd_seq;
    ts.cmd_rejected = cas.status().cmd_rejected;
    ts.bit_in_progress = cas.bit().in_progress;
    ts.bit_failed = cas.bit().failed;
    ts.fault_count = cas.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

// The broadcasts the rules read (ICD README section 8).
constexpr std::array<std::uint8_t, 10> kBroadcasts{
    icd::BcastFmsStatus::kSubaddress,      icd::BcastFcsGcasAlerts::kSubaddress,
    icd::BcastFcsPerfStatus::kSubaddress,  icd::BcastEngEngineStatus::kSubaddress,
    icd::BcastEngFuelStatus::kSubaddress,  icd::BcastRdrWxScan::kSubaddress,
    FusedIn::kDescriptorSubaddress,        FusedIn::kSegmentSubaddress,
    ContactsIn::kDescriptorSubaddress,     ContactsIn::kSegmentSubaddress,
};

std::array<bus::Word, FusedIn::kMaxPayloadWords> g_fused_storage{};
std::array<bus::Word, ContactsIn::kMaxPayloadWords> g_contacts_storage{};
fmofp::cas::CrewAlerting g_cas;
icd::RdrFusedTracks g_fused{};
icd::DefRwrContacts g_contacts{};

Status init_collectors(bus::BlockCollector& fused, bus::BlockCollector& contacts) {
    const Status s = fused.init(g_fused_storage.data(), static_cast<std::uint16_t>(g_fused_storage.size()));
    return fmofp::worst(s, contacts.init(g_contacts_storage.data(), static_cast<std::uint16_t>(g_contacts_storage.size())));
}

// One frame's receptions, decoded into the messages they carry.
struct Frame {
    icd::BcastFmsStatus fms{};
    icd::BcastFcsGcasAlerts gcas{};
    icd::BcastFcsPerfStatus perf{};
    icd::BcastEngEngineStatus engine{};
    icd::BcastEngFuelStatus fuel{};
    icd::BcastRdrWxScan weather{};
    icd::CasDefStatus defensive{};
    icd::CasSnsStatus sensor{};
    icd::CasPwrStatus power{};
    icd::CasHydStatus hydraulics{};
};

template <typename Message, typename Payload>
void take_into(bus::RemoteTerminal& terminal, Message& message, const Payload*& out) {
    out = take_fresh(terminal, message) ? &message.payload : nullptr;
}

fmofp::cas::Received take_all(bus::RemoteTerminal& terminal, Frame& f, bus::BlockCollector& fused,
                              bus::BlockCollector& contacts) {
    fmofp::cas::Received r{};
    take_into(terminal, f.fms, r.fms);
    take_into(terminal, f.gcas, r.gcas);
    take_into(terminal, f.perf, r.perf);
    take_into(terminal, f.engine, r.engine);
    take_into(terminal, f.fuel, r.fuel);
    take_into(terminal, f.weather, r.weather);
    take_into(terminal, f.defensive, r.defensive);
    take_into(terminal, f.sensor, r.sensor);
    take_into(terminal, f.power, r.power);
    take_into(terminal, f.hydraulics, r.hydraulics);
    if (fused.collect(terminal, FusedIn::kDescriptorSubaddress, FusedIn::kSegmentSubaddress) &&
        FusedIn::Layout::decode(fused.receiver().payload(), fused.receiver().length(), g_fused) == Status::kOk) {
        r.fused = &g_fused;
    }
    if (contacts.collect(terminal, ContactsIn::kDescriptorSubaddress, ContactsIn::kSegmentSubaddress) &&
        ContactsIn::Layout::decode(contacts.receiver().payload(), contacts.receiver().length(), g_contacts) ==
            Status::kOk) {
        r.contacts = &g_contacts;
    }
    return r;
}

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_cas [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "cas: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_cas.init() != Status::kOk) {
        std::fprintf(stderr, "cas: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    const auto refused = std::find_if(kBroadcasts.begin(), kBroadcasts.end(), [&terminal](std::uint8_t sa) {
        return terminal.accept_broadcast(sa) != Status::kOk;
    });
    if (refused != kBroadcasts.end()) {
        std::fprintf(stderr, "cas: cannot accept the broadcast at subaddress %u\n", static_cast<unsigned>(*refused));
        return 1;
    }
    bus::BlockCollector fused_collector;
    bus::BlockCollector contacts_collector;
    if (init_collectors(fused_collector, contacts_collector) != Status::kOk) {
        std::fprintf(stderr, "cas: block init failed\n");
        return 1;
    }
    (void)load_outputs(terminal, g_cas, 0);
    if (!o.quiet) {
        std::printf("cas: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    static Frame received_frame;  // static: the frame's messages are kept off the stack
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_cas.reset();
                fused_collector = bus::BlockCollector{};
                contacts_collector = bus::BlockCollector{};
                (void)init_collectors(fused_collector, contacts_collector);
                (void)load_outputs(terminal, g_cas, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_cas.start_self_test();
        }
        terminal.set_bit(g_cas.bit());

        icd::CasModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_cas.command_mode(mode_cmd);
        }
        g_cas.step(take_all(terminal, received_frame, fused_collector, contacts_collector), frame);
        terminal.set_subsystem_flag(g_cas.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_cas, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::CasAlerts& st = g_cas.status();
            std::printf("cas: major frame %u, state %s, %u warnings, %u cautions, %u advisories\n", major,
                        icd::to_string(g_cas.state()), st.warning_count, st.caution_count, st.advisory_count);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    const icd::CasAlerts& st = g_cas.status();
    std::printf("cas: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s warnings=%u "
                "cautions=%u advisories=%u\n",
                syncs, c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_cas.state()),
                st.warning_count, st.caution_count, st.advisory_count);
    return 0;
}
