// The sensor management partition process: terminal RT 10 on the bus.
//
//   fmofp_sensor [--port-base 51000] [--syncs 0] [--quiet]
//
// Each SYNCHRONIZE_WITH_DATA frame: take what arrived (SNS_MODE_CMD, SNS_CMD,
// the plant's sensor scans relayed as the SNS_SCAN block, its ESM intercepts
// relayed as SNS_ESM), run SensorManagement::step(), and load SNS_STATUS and
// TERM_STATUS for the bus controller to collect. The status reaches the EICAS
// by relay.

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/block.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/blocks.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/icd/version.hpp>
#include <fmofp/rt/rt_process.hpp>
#include <fmofp/sensor/sensor_management.hpp>

namespace {

using fmofp::Status;
namespace icd = fmofp::icd;
namespace bus = fmofp::bus;

constexpr std::uint8_t kRt = icd::SnsStatus::kRt;
using ScanIn = icd::SnsScan;

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

Status load_outputs(bus::RemoteTerminal& terminal, const fmofp::sensor::SensorManagement& sm, bus::Word last_sync) {
    Status result = load(terminal, sm.status());
    icd::TermStatus ts{};
    ts.state = sm.state();
    ts.healthy = sm.status().healthy;
    ts.last_cmd_seq = sm.status().last_cmd_seq;
    ts.cmd_rejected = sm.status().cmd_rejected;
    ts.bit_in_progress = sm.bit().in_progress;
    ts.bit_failed = sm.bit().failed;
    ts.fault_count = sm.bit().fault_count;
    ts.icd_major = icd::kIcdMajor;
    ts.icd_minor = icd::kIcdMinor;
    ts.last_sync = last_sync;
    result = fmofp::worst(result, load(terminal, ts));
    return result;
}

std::array<bus::Word, ScanIn::kMaxPayloadWords> g_scan_storage{};
fmofp::sensor::SensorManagement g_sensor;

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::fprintf(stderr, "usage: fmofp_sensor [--port-base N] [--syncs N] [--quiet]\n");
        return 2;
    }

    fmofp::rt::RtProcess process;
    const Status init = process.init(o.rt);
    if (init != Status::kOk) {
        std::fprintf(stderr, "sensor: init failed: %s (port %u in use?)\n", fmofp::to_string(init),
                     static_cast<unsigned>(o.rt.port_base + kRt));
        return 1;
    }
    if (g_sensor.init() != Status::kOk) {
        std::fprintf(stderr, "sensor: logic init failed\n");
        return 1;
    }
    bus::RemoteTerminal& terminal = process.terminal();
    bus::BlockCollector scan_collector;
    if (scan_collector.init(g_scan_storage.data(), static_cast<std::uint16_t>(g_scan_storage.size())) != Status::kOk) {
        std::fprintf(stderr, "sensor: block init failed\n");
        return 1;
    }
    (void)load_outputs(terminal, g_sensor, 0);
    if (!o.quiet) {
        std::printf("sensor: RT %u on 127.0.0.1:%u\n", kRt, static_cast<unsigned>(o.rt.port_base + kRt));
    }

    unsigned long syncs = 0;
    std::uint32_t frame = 0;
    unsigned scans = 0;
    for (;;) {
        (void)process.poll(100 * fmofp::osal::kNsPerMs);
        bus::Word sync = 0;
        if (!terminal.take_sync(sync)) {
            if (terminal.take_reset_request()) {
                g_sensor.reset();
                scan_collector = bus::BlockCollector{};
                (void)scan_collector.init(g_scan_storage.data(), static_cast<std::uint16_t>(g_scan_storage.size()));
                (void)load_outputs(terminal, g_sensor, 0);
            }
            continue;
        }
        ++syncs;
        ++frame;
        if (terminal.take_self_test_request()) {
            g_sensor.start_self_test();
        }
        terminal.set_bit(g_sensor.bit());

        icd::SnsModeCmd mode_cmd{};
        if (take_fresh(terminal, mode_cmd)) {
            g_sensor.command_mode(mode_cmd);
        }
        icd::SnsCmd cmd{};
        if (take_fresh(terminal, cmd)) {
            g_sensor.command(cmd, frame);
        }
        icd::SnsEsm esm{};
        const bool have_esm = take_fresh(terminal, esm);
        icd::PlantSensorScan scan{};
        bool have_scan = false;
        if (scan_collector.collect(terminal, ScanIn::kDescriptorSubaddress, ScanIn::kSegmentSubaddress)) {
            have_scan = ScanIn::Layout::decode(scan_collector.receiver().payload(), scan_collector.receiver().length(),
                                               scan) == Status::kOk;
            if (have_scan) {
                ++scans;
            }
        }
        g_sensor.step(have_scan ? &scan : nullptr, have_esm ? &esm.payload : nullptr, frame);
        terminal.set_subsystem_flag(g_sensor.state() == icd::TerminalState::DEGRADED);
        (void)load_outputs(terminal, g_sensor, sync);

        if (!o.quiet && syncs % 50 == 1) {
            std::uint16_t major = 0;
            std::uint8_t minor = 0;
            fmofp::bc::decode_sync_word(sync, major, minor);
            const icd::SnsStatus& st = g_sensor.status();
            std::printf("sensor: major frame %u, state %s, health %s, %u contacts (seq %u, %u refused), sensors %c%c%c%c%c%c, "
                        "scans %u\n",
                        major, icd::to_string(g_sensor.state()), icd::to_string(st.health), st.contact_count, st.sequence,
                        st.dropped, st.main_radar_active ? 'R' : '-', st.tfr_radar_active ? 'T' : '-',
                        st.lidar_active ? 'L' : '-', st.flir_active ? 'F' : '-', st.maws_active ? 'M' : '-',
                        st.esm_active ? 'E' : '-', scans);
        }
        if (o.syncs != 0 && syncs >= o.syncs) {
            break;
        }
    }

    const bus::RtCounters& c = terminal.counters();
    std::printf("sensor: syncs=%lu commands=%u receives=%u transmits=%u message_errors=%u state=%s scans=%u\n", syncs,
                c.commands, c.receives, c.transmits, c.message_errors, icd::to_string(g_sensor.state()), scans);
    return 0;
}
