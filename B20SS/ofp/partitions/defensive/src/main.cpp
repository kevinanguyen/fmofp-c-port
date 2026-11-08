// The defensive systems partition process: terminal RT 22 on the bus.
//
//   fmofp_defensive [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (DEF_MODE_CMD, DEF_CMD,
// the plant's ESM intercepts relayed as DEF_ESM, the fused air tracks heard by
// broadcast), run DefensiveSystems::step(), load DEF_STATUS and TERM_STATUS,
// and serve the DEF_RWR_CONTACTS block (republished at every RWR update, every
// 25 frames). The status reaches the EICAS by relay; the contacts reach the
// EICAS and the TSD by broadcast.

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/block.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/defensive/defensive_systems.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::DefStatus::kRt;
using FusedIn = icd::BcastRdrFusedTracks;
using ContactsOut = icd::DefRwrContacts;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::defensive::DefensiveSystems& ds,
                    bus::Word last_sync) {
    Status result = load(terminal, ds.status());
    icd::TermStatus ts{};
    ts.state = ds.state();
    ts.healthy = ds.status().healthy;
    ts.last_cmd_seq = ds.status().last_cmd_seq;
    ts.cmd_rejected = ds.status().cmd_rejected;
    ts.bit_in_progress = ds.bit().in_progress;
    ts.bit_failed = ds.bit().failed;
    ts.fault_count = ds.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

std::array<bus::Word, ContactsOut::kMaxPayloadWords> g_contacts_payload{};
std::array<bus::Word, ContactsOut::kMaxPayloadWords> g_contacts_storage{};  // the publisher's own copy, in flight
std::array<bus::Word, FusedIn::kMaxPayloadWords> g_fused_storage{};
fmofp::defensive::DefensiveSystems g_defensive;

Status init_blocks(bus::BlockPublisher& contacts_block, bus::BlockCollector& fused_collector) {
    const Status s = contacts_block.init(g_contacts_storage.data(), static_cast<std::uint16_t>(g_contacts_storage.size()));
    return fmofp::worst(s, fused_collector.init(g_fused_storage.data(), static_cast<std::uint16_t>(g_fused_storage.size())));
}

void publish_contacts(const bus::RemoteTerminal& terminal, bus::BlockPublisher& block) {
    std::uint16_t length = 0;
    const Status s = g_defensive.contacts().encode(g_contacts_payload.data(),
                                                   static_cast<std::uint16_t>(g_contacts_payload.size()), length);
    if (s != Status::kOk && s != Status::kClamped) {
        return;
    }
    (void)block.publish(terminal, ContactsOut::kSegmentSubaddress, g_contacts_payload.data(), length);
}

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_defensive [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "defensive: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_defensive.init() != Status::kOk) {
        std::fprintf(stderr, "defensive: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    // The radar warning receiver reads the fused air tracks the radar computer broadcasts (ICD README section 8).
    if (terminal.accept_broadcast(FusedIn::kDescriptorSubaddress) != Status::kOk ||
        terminal.accept_broadcast(FusedIn::kSegmentSubaddress) != Status::kOk) {
        std::fprintf(stderr, "defensive: cannot accept the fused tracks broadcast\n");
        return 1;
    }
    bus::BlockPublisher contacts_block;
    bus::BlockCollector fused_collector;
    if (init_blocks(contacts_block, fused_collector) != Status::kOk) {
        std::fprintf(stderr, "defensive: block init failed\n");
        return 1;
    }
    if (g_defensive.take_contacts_update()) {
        publish_contacts(terminal, contacts_block);
    }
    (void)contacts_block.serve(terminal, ContactsOut::kDescriptorSubaddress, ContactsOut::kSegmentSubaddress);
    (void)load_outputs(terminal, g_defensive, 0);
    if (!o.quiet) {
        std::printf("defensive: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned blocks = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_defensive.reset();
                contacts_block = bus::BlockPublisher{};
                fused_collector = bus::BlockCollector{};
                (void)init_blocks(contacts_block, fused_collector);
                if (g_defensive.take_contacts_update()) {
                    publish_contacts(terminal, contacts_block);
                }
                (void)contacts_block.serve(terminal, ContactsOut::kDescriptorSubaddress, ContactsOut::kSegmentSubaddress);
                (void)load_outputs(terminal, g_defensive, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_defensive.start_self_test();
        }
        terminal.set_bit(g_defensive.bit());

        icd::DefModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_defensive.command_mode(mode_cmd);
        }
        icd::DefCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_defensive.command(cmd, frame);
        }
        icd::DefEsm esm{};
        const bool have_esm = take_fresh(terminal, esm);
        icd::RdrFusedTracks fused{};
        bool have_fused = false;
        if (fused_collector.collect(terminal, FusedIn::kDescriptorSubaddress, FusedIn::kSegmentSubaddress)) {
            have_fused = FusedIn::Layout::decode(fused_collector.receiver().payload(),
                                                 fused_collector.receiver().length(), fused) == Status::kOk;
        }
        g_defensive.step(have_fused ? &fused : nullptr, have_esm ? &esm.payload : nullptr, frame);
        if (g_defensive.take_contacts_update()) {
            publish_contacts(terminal, contacts_block);
            ++blocks;
        }
        (void)contacts_block.serve(terminal, ContactsOut::kDescriptorSubaddress, ContactsOut::kSegmentSubaddress);
        terminal.set_subsystem_flag(g_defensive.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_defensive, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::DefStatus& st = g_defensive.status();
            std::printf("defensive: major frame %u, state %s, chaff %u, flares %u, ECM %s, %u contacts (%u priority 1), "
                        "%u salvos, blocks %u\n",
                        major, icd::to_string(g_defensive.state()), st.chaff_remaining, st.flares_remaining,
                        icd::to_string(st.ecm_mode), st.contact_count, st.high_priority_count, st.auto_salvos, blocks);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("defensive: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s blocks=%u\n", syncs,
                c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_defensive.state()), blocks);
    return 0;
}
