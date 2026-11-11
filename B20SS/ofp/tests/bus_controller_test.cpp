// The Phase 1 gate: a bus controller and stub terminals, each a real
// RtProcess on its own socket, exchanging TERM_STATUS in lockstep. The
// terminals run on threads here so the test is one process; fmofp_bc and
// fmofp_rt_stub do the same from separate processes.
#include <gtest/gtest.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <thread>

#include <fmofp/bc/bus_controller.hpp>
#include <fmofp/bc/bus_health.hpp>
#include <fmofp/bc/command_port.hpp>
#include <fmofp/bc/icd_schedule.hpp>
#include <fmofp/bc/schedule.hpp>
#include <fmofp/bus/transport.hpp>
#include <fmofp/icd/messages.hpp>
#include <fmofp/osal/clock.hpp>
#include <fmofp/osal/udp.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
using fmofp::bc::BcConfig;
using fmofp::bc::BcMode;
using fmofp::bc::BusController;
using fmofp::bc::encode_sync_word;
using fmofp::bc::kMinorFramesPerMajor;
using fmofp::bc::Schedule;
using fmofp::bus::Word;
using fmofp::icd::TermStatus;
using fmofp::osal::kNsPerMs;
using fmofp::osal::Nanoseconds;
using fmofp::osal::now;

constexpr std::uint16_t kPortBase = 52000;

// A stub terminal on its own thread: answers the bus, and on every sync
// refreshes its TERM_STATUS with the sync word it just received.
class StubTerminal {
public:
    // `preload` runs on the fresh terminal before its thread starts, for
    // loading transmit subaddresses other than TERM_STATUS.
    Status start(std::uint8_t rt, void (*preload)(fmofp::bus::RemoteTerminal&) = nullptr) {
        fmofp::rt::RtProcessConfig cfg;
        cfg.rt = rt;
        cfg.port_base = kPortBase;
        const Status s = process_.init(cfg);
        if (s != Status::kOk) {
            return s;
        }
        if (preload != nullptr) {
            preload(process_.terminal());
        }
        thread_ = std::thread([this] { run(); });
        return Status::kOk;
    }

    void stop() {
        stop_ = true;
        if (thread_.joinable()) {
            thread_.join();
        }
    }

    ~StubTerminal() { stop(); }

    std::uint32_t syncs() const { return syncs_.load(); }
    // Only valid after stop(): the terminal is then no longer touched by its thread.
    fmofp::rt::RtProcess& process() { return process_; }

private:
    void run() {
        while (!stop_) {
            (void)process_.poll(2 * kNsPerMs);
            Word sync = 0;
            if (process_.terminal().take_sync(sync)) {
                last_sync_ = sync;
                syncs_.fetch_add(1);
                TermStatus status{};
                status.state = fmofp::icd::TerminalState::NORMAL;
                status.healthy = true;
                status.last_sync = sync;
                status.icd_major = 1;
                TermStatus::Words words{};
                if (status.encode(words) == Status::kOk) {
                    (void)process_.terminal().set_transmit(TermStatus::kSubaddress, words.data(), TermStatus::kWords);
                }
            }
        }
    }

    fmofp::rt::RtProcess process_;
    std::thread thread_;
    std::atomic<bool> stop_{false};
    std::atomic<std::uint32_t> syncs_{0};
    Word last_sync_{0};
};

BcConfig config(std::initializer_list<std::uint8_t> rts, BcMode mode, bool monitor = false) {
    BcConfig c;
    c.port_base = kPortBase;
    c.mode = mode;
    c.monitor_enabled = monitor;
    c.response_timeout = 20 * kNsPerMs;  // generous: the stubs are threads sharing a CI core
    for (const std::uint8_t rt : rts) {
        c.terminals[c.terminal_count++] = rt;
    }
    return c;
}

Schedule schedule_for(const BcConfig& c) {
    Schedule s;
    EXPECT_EQ(Status::kOk, fmofp::bc::add_icd_messages(s, c.terminals.data(), c.terminal_count));
    EXPECT_EQ(Status::kOk, s.build());
    return s;
}

void wait_for_syncs(const StubTerminal& t, std::uint32_t expected) {
    const Nanoseconds deadline = now() + 500 * kNsPerMs;
    while (t.syncs() < expected && now() < deadline) {
        (void)fmofp::osal::sleep_for(kNsPerMs);
    }
}

// The controller holds ~80 KB of buffers; keep it off the test's stack.
std::unique_ptr<BusController> make_bc() { return std::make_unique<BusController>(); }

TEST(BusControllerGate, TwoTerminalsFollowTheBusControllerFrameForFrame) {
    StubTerminal a;
    StubTerminal b;
    ASSERT_EQ(Status::kOk, a.start(24));
    ASSERT_EQ(Status::kOk, b.start(25));

    const BcConfig cfg = config({24, 25}, BcMode::kFreeRun);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    const std::uint32_t frames = 2 * kMinorFramesPerMajor;  // two major frames
    EXPECT_EQ(Status::kOk, bc->run_frames(frames));
    wait_for_syncs(a, frames);
    wait_for_syncs(b, frames);
    a.stop();
    b.stop();

    EXPECT_EQ(frames, a.syncs());
    EXPECT_EQ(frames, b.syncs());
    EXPECT_EQ(frames, bc->stats().frames);
    for (const std::uint8_t rt : {std::uint8_t{24}, std::uint8_t{25}}) {
        const fmofp::bc::TerminalStats& t = bc->terminal(rt);
        EXPECT_TRUE(t.responded);
        EXPECT_EQ(0U, t.no_response) << "RT " << static_cast<int>(rt);
        EXPECT_EQ(0U, t.malformed);
        EXPECT_EQ(0U, t.message_errors);
        EXPECT_EQ(2U, t.transactions) << "TERM_STATUS is 1 Hz: once per major frame";
    }

    // The last TERM_STATUS poll of RT 24 happened in major frame 1, minor 0,
    // after that frame's sync, so it carries exactly that sync word.
    TermStatus::Words words{};
    std::uint8_t count = 0;
    std::uint32_t frame = 0;
    ASSERT_EQ(Status::kOk, bc->get_latest(24, TermStatus::kSubaddress, words.data(), TermStatus::kWords, count, frame));
    ASSERT_EQ(TermStatus::kWords, count);
    TermStatus status{};
    ASSERT_EQ(Status::kOk, TermStatus::decode(words, status));
    EXPECT_EQ(fmofp::icd::TerminalState::NORMAL, status.state);
    EXPECT_TRUE(status.healthy);
    EXPECT_EQ(encode_sync_word(1, 0), status.last_sync);
    EXPECT_EQ(2U, a.process().terminal().counters().transmits);
    EXPECT_EQ(frames, a.process().terminal().counters().syncs);
    bc->shutdown();
}

TEST(BusControllerGate, RealTimeFramesHoldTwentyMillisecondsWithoutOverruns) {
    StubTerminal a;
    StubTerminal b;
    ASSERT_EQ(Status::kOk, a.start(24));
    ASSERT_EQ(Status::kOk, b.start(25));
    const BcConfig cfg = config({24, 25}, BcMode::kRealTime);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    const std::uint32_t frames = kMinorFramesPerMajor;  // one second
    const Nanoseconds start = now();
    EXPECT_EQ(Status::kOk, bc->run_frames(frames));
    const Nanoseconds elapsed = now() - start;
    wait_for_syncs(a, frames);
    a.stop();
    b.stop();

    EXPECT_EQ(0U, bc->stats().overruns);
    EXPECT_LT(bc->stats().worst_frame_ns, fmofp::bc::kMinorFramePeriodNs);
    // 50 frames of 20 ms: the first runs at once, so 49 periods must have passed.
    EXPECT_GE(elapsed, 49 * fmofp::bc::kMinorFramePeriodNs);
    EXPECT_LT(elapsed, 2 * frames * fmofp::bc::kMinorFramePeriodNs);
    EXPECT_EQ(frames, a.syncs());
    EXPECT_EQ(0U, bc->terminal(24).no_response);
    EXPECT_EQ(0U, bc->terminal(2).no_response);
    // The timing counters (unit 30): no overrun, so none started late and no terminal is held to one; every
    // frame started within the period of its deadline.
    EXPECT_EQ(0U, bc->stats().overruns_late_start);
    EXPECT_EQ(0U, bc->terminal(24).overruns_slowest);
    EXPECT_GE(bc->stats().worst_wake_late_ns, 0);
    EXPECT_LT(bc->stats().worst_wake_late_ns, fmofp::bc::kMinorFramePeriodNs);
}

TEST(BusController, AMissingTerminalIsCountedAndTheBusKeepsGoing) {
    StubTerminal a;
    ASSERT_EQ(Status::kOk, a.start(24));
    BcConfig cfg = config({24, 7}, BcMode::kFreeRun);  // nobody is listening at RT 7
    cfg.response_timeout = 2 * kNsPerMs;
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    const Status worst = bc->run_frames(kMinorFramesPerMajor + 2);
    EXPECT_EQ(Status::kTimeout, worst) << "the worst outcome of the run is reported";
    a.stop();

    EXPECT_TRUE(bc->terminal(24).responded);
    EXPECT_EQ(0U, bc->terminal(24).no_response);
    EXPECT_FALSE(bc->terminal(7).responded);
    EXPECT_GE(bc->terminal(7).no_response, 1U);
    EXPECT_EQ(bc->terminal(7).transactions, bc->terminal(7).no_response);
    EXPECT_EQ(kMinorFramesPerMajor + 2, bc->stats().frames);
    // Response times (unit 30) are those of answered transactions: the terminal that answers has one, under
    // the timeout it was given and no larger than their sum; the one that never answers has none.
    EXPECT_GT(bc->terminal(24).worst_response_ns, 0);
    EXPECT_LT(bc->terminal(24).worst_response_ns, 2 * cfg.response_timeout);
    EXPECT_GE(bc->terminal(24).total_response_ns, bc->terminal(24).worst_response_ns);
    EXPECT_EQ(0, bc->terminal(7).worst_response_ns);
    EXPECT_EQ(0, bc->terminal(7).total_response_ns);
    EXPECT_EQ(0U, bc->stats().overruns_late_start) << "free running has no deadline to miss";
}

TEST(BusController, AQueuedCommandReachesTheTerminalNextFrame) {
    StubTerminal a;
    ASSERT_EQ(Status::kOk, a.start(24));
    const BcConfig cfg = config({24}, BcMode::kFreeRun);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    const std::array<Word, 3> data{0xCAFE, 0x0001, 0xBEEF};
    ASSERT_EQ(Status::kOk, bc->queue_receive(24, 20, data.data(), 3));
    EXPECT_EQ(Status::kOk, bc->run_frames(2));
    EXPECT_EQ(1U, bc->stats().aperiodic_sent);
    wait_for_syncs(a, 2);
    a.stop();

    std::array<Word, 32> got{};
    std::uint8_t count = 0;
    bool fresh = false;
    ASSERT_EQ(Status::kOk, a.process().terminal().get_received(20, got.data(), 32, count, fresh));
    EXPECT_EQ(3, count);
    EXPECT_TRUE(fresh);
    EXPECT_EQ(Word{0xCAFE}, got[0]);
    EXPECT_EQ(Word{0xBEEF}, got[2]);

    // The queue is bounded; overflow is reported, not silently grown.
    for (std::size_t i = 0; i < fmofp::bc::kAperiodicQueueDepth; ++i) {
        ASSERT_EQ(Status::kOk, bc->queue_receive(24, 20, data.data(), 1));
    }
    EXPECT_EQ(Status::kNotReady, bc->queue_receive(24, 20, data.data(), 1));
    EXPECT_EQ(1U, bc->stats().aperiodic_dropped);
}

TEST(BusController, TheCommandPortQueuesWhatAClientSendsAndAnswers) {
    ASSERT_EQ(Status::kOk, fmofp::osal::init());
    fmofp::bc::CommandPort port;
    const auto port_number = static_cast<std::uint16_t>(kPortBase + fmofp::bc::kCommandPortOffset);
    ASSERT_EQ(Status::kOk, port.open(port_number));
    fmofp::osal::UdpSocket client;
    ASSERT_EQ(Status::kOk, client.open(static_cast<std::uint16_t>(kPortBase + 40)));

    StubTerminal a;
    ASSERT_EQ(Status::kOk, a.start(24));
    const BcConfig cfg = config({24}, BcMode::kFreeRun);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    // A client's command: a receive of three words to RT 24 SA 20, as the scenario engine or the CLI sends it.
    fmofp::bus::Frame command{};
    command.type = fmofp::bus::FrameType::kCommand;
    command.transaction = 77;
    command.word_count = 4;
    fmofp::bus::CommandWord cw{};
    cw.rt = 24;
    cw.transmit = false;
    cw.subaddress = 20;
    cw.count_or_mode = 3;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_command_word(cw, command.words[0]));
    command.words[1] = 0xCAFE;
    command.words[2] = 0x0002;
    command.words[3] = 0xBEEF;
    std::array<std::uint8_t, fmofp::bus::kMaxFrameBytes> bytes{};
    std::size_t length = 0;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_frame(command, bytes.data(), bytes.size(), length));
    ASSERT_EQ(Status::kOk, client.send_to(port_number, bytes.data(), length));
    (void)fmofp::osal::sleep_for(5 * kNsPerMs);

    EXPECT_EQ(1U, port.poll(*bc));
    EXPECT_EQ(Status::kOk, bc->run_frames(2));
    EXPECT_EQ(1U, bc->stats().aperiodic_sent);
    wait_for_syncs(a, 2);

    // The acknowledgement: the client's transaction number, the command word, kOk, the frame count then (0).
    std::array<std::uint8_t, fmofp::bus::kMaxFrameBytes> reply{};
    std::size_t reply_length = 0;
    ASSERT_EQ(Status::kOk, client.receive(reply.data(), reply.size(), reply_length, 200 * kNsPerMs, nullptr));
    fmofp::bus::Frame ack{};
    ASSERT_EQ(Status::kOk, fmofp::bus::decode_frame(reply.data(), reply_length, ack));
    EXPECT_EQ(fmofp::bus::FrameType::kCommandAck, ack.type);
    EXPECT_EQ(Word{77}, ack.transaction);
    ASSERT_EQ(fmofp::bc::kAckWords, ack.word_count);
    EXPECT_EQ(command.words[0], ack.words[0]);
    EXPECT_EQ(static_cast<Word>(Status::kOk), ack.words[1]);
    EXPECT_EQ(Word{0}, ack.words[2]);
    EXPECT_EQ(Word{0}, ack.words[3]);

    // The terminal got the data in the frame after.
    std::array<Word, 32> got{};
    std::uint8_t count = 0;
    bool fresh = false;
    ASSERT_EQ(Status::kOk, a.process().terminal().get_received(20, got.data(), 32, count, fresh));
    EXPECT_EQ(3, count);
    EXPECT_TRUE(fresh);
    EXPECT_EQ(Word{0xCAFE}, got[0]);
    EXPECT_EQ(Word{0xBEEF}, got[2]);

    // A transmit command is nothing to queue: refused, acknowledged with kInvalidArgument. Bytes that are no
    // frame are counted malformed and acknowledged with the decoder's complaint.
    cw.transmit = true;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_command_word(cw, command.words[0]));
    command.transaction = 78;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_frame(command, bytes.data(), bytes.size(), length));
    ASSERT_EQ(Status::kOk, client.send_to(port_number, bytes.data(), length));
    const std::array<std::uint8_t, 4> junk{1, 2, 3, 4};
    ASSERT_EQ(Status::kOk, client.send_to(port_number, junk.data(), junk.size()));
    (void)fmofp::osal::sleep_for(5 * kNsPerMs);
    EXPECT_EQ(0U, port.poll(*bc));
    EXPECT_EQ(3U, port.stats().received);
    EXPECT_EQ(1U, port.stats().queued);
    EXPECT_EQ(1U, port.stats().refused);
    EXPECT_EQ(1U, port.stats().malformed);
    ASSERT_EQ(Status::kOk, client.receive(reply.data(), reply.size(), reply_length, 200 * kNsPerMs, nullptr));
    ASSERT_EQ(Status::kOk, fmofp::bus::decode_frame(reply.data(), reply_length, ack));
    EXPECT_EQ(Word{78}, ack.transaction);
    EXPECT_EQ(static_cast<Word>(Status::kInvalidArgument), ack.words[1]);
    ASSERT_EQ(Status::kOk, client.receive(reply.data(), reply.size(), reply_length, 200 * kNsPerMs, nullptr));
    ASSERT_EQ(Status::kOk, fmofp::bus::decode_frame(reply.data(), reply_length, ack));
    EXPECT_EQ(static_cast<Word>(Status::kBadLength), ack.words[1]);

    a.stop();
    bc->shutdown();
    port.close();
    client.close();
}

TEST(BusController, TheMonitorSeesEveryTransaction) {
    ASSERT_EQ(Status::kOk, fmofp::osal::init());
    fmofp::osal::UdpSocket monitor;
    ASSERT_EQ(Status::kOk, monitor.open(static_cast<std::uint16_t>(kPortBase + 33)));

    StubTerminal a;
    ASSERT_EQ(Status::kOk, a.start(24));
    const BcConfig cfg = config({24}, BcMode::kFreeRun, true);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));
    const std::uint32_t frames = 10;
    EXPECT_EQ(Status::kOk, bc->run_frames(frames));
    a.stop();
    EXPECT_EQ(0U, bc->stats().monitor_failures);

    // 10 syncs plus the one TERM_STATUS poll in minor frame 0.
    std::uint32_t records = 0;
    std::uint32_t syncs = 0;
    std::uint32_t polls = 0;
    for (;;) {
        std::array<std::uint8_t, fmofp::osal::kMaxDatagramBytes> bytes{};
        std::size_t length = 0;
        if (monitor.receive(bytes.data(), bytes.size(), length, 100 * kNsPerMs, nullptr) != Status::kOk) {
            break;
        }
        fmofp::bus::Frame f;
        ASSERT_EQ(Status::kOk, fmofp::bus::decode_frame(bytes.data(), length, f));
        EXPECT_EQ(fmofp::bus::FrameType::kMonitor, f.type);
        ++records;
        if (f.word_count == 2) {
            ++syncs;  // command word + sync data word, no reply to a broadcast
        } else if (f.word_count == 1 + 1 + TermStatus::kWords) {
            ++polls;  // command, then status word + 5 data words
        }
    }
    EXPECT_EQ(frames + 1, records);
    EXPECT_EQ(frames, syncs);
    EXPECT_EQ(1U, polls);
}

void load_plant_sensors(fmofp::bus::RemoteTerminal& terminal) {
    fmofp::icd::PlantSensors s{};
    s.altitude_ssm = fmofp::icd::Ssm::NORMAL;
    s.vertical_speed_ssm = fmofp::icd::Ssm::NORMAL;
    s.altitude = 1500.0;
    s.vertical_speed = -4500.0;
    s.gear = fmofp::icd::GearPosition::UP;
    fmofp::icd::PlantSensors::Words words{};
    ASSERT_EQ(Status::kOk, s.encode(words));
    ASSERT_EQ(Status::kOk, terminal.set_transmit(fmofp::icd::PlantSensors::kSubaddress, words.data(),
                                                 fmofp::icd::PlantSensors::kWords));
}

TEST(BusController, APlantMessageIsRelayedToTheFlightControlComputer) {
    StubTerminal plant;
    StubTerminal fcs;
    ASSERT_EQ(Status::kOk, plant.start(27, load_plant_sensors));
    ASSERT_EQ(Status::kOk, fcs.start(5));
    const BcConfig cfg = config({27, 5}, BcMode::kFreeRun);
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));

    EXPECT_EQ(Status::kOk, bc->run_frames(3));
    wait_for_syncs(fcs, 3);
    plant.stop();
    fcs.stop();
    EXPECT_EQ(3U, bc->stats().relays);
    EXPECT_EQ(0U, bc->terminal(27).no_response);
    EXPECT_EQ(0U, bc->terminal(5).no_response);

    // The FCS terminal holds the plant's words at FCS_SENSORS, decodable as such.
    using fmofp::icd::FcsSensors;
    FcsSensors::Words got{};
    std::uint8_t count = 0;
    bool fresh = false;
    ASSERT_EQ(Status::kOk, fcs.process().terminal().get_received(FcsSensors::kSubaddress, got.data(),
                                                                   FcsSensors::kWords, count, fresh));
    ASSERT_EQ(FcsSensors::kWords, count);
    FcsSensors decoded{};
    ASSERT_EQ(Status::kOk, FcsSensors::decode(got, decoded));
    EXPECT_EQ(fmofp::icd::Ssm::NORMAL, decoded.payload.altitude_ssm);
    EXPECT_DOUBLE_EQ(1500.0, decoded.payload.altitude);
    EXPECT_DOUBLE_EQ(-4500.0, decoded.payload.vertical_speed);
    EXPECT_EQ(fmofp::icd::GearPosition::UP, decoded.payload.gear);
    EXPECT_EQ(3U, fcs.process().terminal().counters().receives);
}

TEST(BusController, RefusesABadConfiguration) {
    auto bc = make_bc();
    Schedule unbuilt;
    BcConfig cfg = config({24}, BcMode::kFreeRun);
    EXPECT_EQ(Status::kInvalidArgument, bc->init(cfg, unbuilt));
    Schedule built;
    ASSERT_EQ(Status::kOk, built.build());
    cfg.terminals[0] = 31;
    EXPECT_EQ(Status::kInvalidArgument, bc->init(cfg, built));
    cfg = config({24}, BcMode::kFreeRun);
    cfg.response_timeout = 0;
    EXPECT_EQ(Status::kInvalidArgument, bc->init(cfg, built));
    EXPECT_EQ(Status::kNotReady, bc->run_minor_frame()) << "not initialised";
}

// AVN_BUS_HEALTH (ICD v1.20): the controller's own report of its terminals,
// stored as the data its receive slot at the avionics terminal carries.
TEST(BusController, ReportsTheBusHealthOfItsTerminals) {
    using fmofp::icd::AvnBusHealth;
    StubTerminal a;
    ASSERT_EQ(Status::kOk, a.start(24));
    BcConfig cfg = config({24, 7}, BcMode::kFreeRun);  // nobody is listening at RT 7
    cfg.response_timeout = 2 * kNsPerMs;
    auto bc = make_bc();
    ASSERT_EQ(Status::kOk, bc->init(cfg, schedule_for(cfg)));
    fmofp::bc::BusHealthReporter reporter;

    (void)bc->run_frames(kMinorFramesPerMajor);
    ASSERT_EQ(Status::kOk, reporter.report(*bc));
    const std::uint16_t rt24 = 1U << (24U - 16U);
    const std::uint16_t rt7 = 1U << 7U;
    AvnBusHealth first = reporter.last();
    EXPECT_EQ(1U, first.epoch);
    EXPECT_EQ(rt24, first.listed_mask_hi);
    EXPECT_EQ(rt7, first.listed_mask_lo);
    EXPECT_EQ(rt24, first.responded_mask_hi) << "RT 24 answers";
    EXPECT_EQ(0U, first.responded_mask_lo) << "RT 7 never has";
    EXPECT_EQ(rt24, first.answering_mask_hi);
    EXPECT_EQ(rt24, first.status_mask_hi) << "its TERM_STATUS arrived this major frame";
    EXPECT_EQ(rt24, first.healthy_mask_hi);
    EXPECT_EQ(rt24, first.normal_mask_hi);
    EXPECT_EQ(0U, first.degraded_mask_hi);
    EXPECT_EQ(0U, first.failure_mask_hi);
    EXPECT_EQ(0U, first.bit_failed_mask_hi);

    // The report is what the controller will send to RT 1 SA 11.
    AvnBusHealth::Words words{};
    std::uint8_t count = 0;
    std::uint32_t frame = 0;
    ASSERT_EQ(Status::kOk,
              bc->get_latest(AvnBusHealth::kRt, AvnBusHealth::kSubaddress, words.data(), AvnBusHealth::kWords, count, frame));
    AvnBusHealth stored{};
    ASSERT_EQ(Status::kOk, AvnBusHealth::decode(words, stored));
    EXPECT_EQ(1U, stored.epoch);
    EXPECT_EQ(rt24, stored.answering_mask_hi);

    // The terminal goes away: it has responded, but the polls of the next second go unanswered.
    a.stop();
    (void)bc->run_frames(kMinorFramesPerMajor);
    ASSERT_EQ(Status::kOk, reporter.report(*bc));
    EXPECT_EQ(2U, reporter.last().epoch);
    EXPECT_EQ(rt24, reporter.last().responded_mask_hi);
    EXPECT_EQ(0U, reporter.last().answering_mask_hi) << "silent since the last report";
    EXPECT_EQ(rt24, reporter.last().status_mask_hi) << "the last TERM_STATUS is still under three periods old";

    // Three periods without a TERM_STATUS and it no longer counts.
    (void)bc->run_frames(3 * kMinorFramesPerMajor);
    ASSERT_EQ(Status::kOk, reporter.report(*bc));
    EXPECT_EQ(0U, reporter.last().status_mask_hi);
    EXPECT_EQ(0U, reporter.last().healthy_mask_hi);

    EXPECT_EQ(Status::kInvalidArgument, bc->set_receive_data(31, 11, words.data(), 1));
    EXPECT_EQ(Status::kInvalidArgument, bc->set_receive_data(1, 0, words.data(), 1));
    EXPECT_EQ(Status::kInvalidArgument, bc->set_receive_data(1, 11, nullptr, 1));
    bc->shutdown();
}

}  // namespace
