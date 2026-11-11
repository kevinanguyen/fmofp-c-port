// The socket loop every partition runs around its terminal (partitions/common): what it does with a datagram
// that is not a command for it. The bus controller's tests cover the commands it does answer.
#include <gtest/gtest.h>

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bus/command_word.hpp>
#include <fmofp/bus/transport.hpp>
#include <fmofp/osal/clock.hpp>
#include <fmofp/osal/udp.hpp>
#include <fmofp/rt/rt_process.hpp>

namespace {

using fmofp::Status;
using fmofp::osal::kNsPerMs;
using fmofp::rt::RtProcess;
using fmofp::rt::RtProcessConfig;

constexpr std::uint16_t kPortBase = 52300;  // beside the bus controller tests' 52000
constexpr std::uint8_t kRt = 24;            // a free address

RtProcessConfig config() {
    RtProcessConfig c;
    c.rt = kRt;
    c.port_base = kPortBase;
    return c;
}

// The test stands where the bus controller would: at port_base + 32.
class RtProcessTest : public ::testing::Test {
protected:
    void SetUp() override {
        ASSERT_EQ(Status::kOk, fmofp::osal::init());
        ASSERT_EQ(Status::kOk, controller_.open(static_cast<std::uint16_t>(kPortBase + 32)));
    }

    void send(const std::uint8_t* bytes, std::size_t length) {
        ASSERT_EQ(Status::kOk, controller_.send_to(static_cast<std::uint16_t>(kPortBase + kRt), bytes, length));
    }

    void send(const fmofp::bus::Frame& frame) {
        std::array<std::uint8_t, fmofp::bus::kMaxFrameBytes> bytes{};
        std::size_t length = 0;
        ASSERT_EQ(Status::kOk, fmofp::bus::encode_frame(frame, bytes.data(), bytes.size(), length));
        send(bytes.data(), length);
    }

    // True when the terminal answered within 50 ms.
    bool answered() {
        std::array<std::uint8_t, fmofp::osal::kMaxDatagramBytes> bytes{};
        std::size_t length = 0;
        return controller_.receive(bytes.data(), bytes.size(), length, 50 * kNsPerMs, nullptr) == Status::kOk;
    }

    fmofp::osal::UdpSocket controller_;
};

TEST_F(RtProcessTest, RefusesAnAddressThatIsNotATerminals) {
    RtProcess process;
    EXPECT_EQ(Status::kNotReady, process.poll(kNsPerMs)) << "not initialised";
    RtProcessConfig bad = config();
    bad.rt = fmofp::bus::kBroadcastRt;
    EXPECT_EQ(Status::kInvalidArgument, process.init(bad));
    EXPECT_EQ(Status::kNotReady, process.poll(kNsPerMs));
    ASSERT_EQ(Status::kOk, process.init(config()));
    EXPECT_EQ(Status::kTimeout, process.poll(kNsPerMs)) << "nothing has been sent";
    EXPECT_EQ(kRt, process.config().rt);
    process.shutdown();
    EXPECT_EQ(Status::kNotReady, process.poll(kNsPerMs));
}

TEST_F(RtProcessTest, CountsWhatIsNotAFrameForATerminalAndAnswersNothing) {
    RtProcess process;
    ASSERT_EQ(Status::kOk, process.init(config()));

    // Bytes that are no frame at all.
    const std::array<std::uint8_t, 3> junk{0x01, 0x02, 0x03};
    send(junk.data(), junk.size());
    EXPECT_EQ(Status::kOk, process.poll(100 * kNsPerMs)) << "a datagram was handled, valid or not";
    EXPECT_EQ(1U, process.stats().datagrams);
    EXPECT_EQ(1U, process.stats().bad_frames);

    // A well-formed frame of the wrong kind: a terminal's reply, not a controller's command.
    fmofp::bus::Frame reply;
    reply.type = fmofp::bus::FrameType::kRtToBc;
    reply.word_count = 1;
    send(reply);
    EXPECT_EQ(Status::kOk, process.poll(100 * kNsPerMs));
    EXPECT_EQ(2U, process.stats().bad_frames);

    // A command for another terminal: decoded, ignored, not an error.
    fmofp::bus::CommandWord other;
    other.rt = 7;
    other.transmit = true;
    other.subaddress = 29;
    other.count_or_mode = 5;
    fmofp::bus::Frame command;
    command.type = fmofp::bus::FrameType::kBcToRt;
    command.word_count = 1;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_command_word(other, command.words[0]));
    send(command);
    EXPECT_EQ(Status::kOk, process.poll(100 * kNsPerMs));
    EXPECT_EQ(3U, process.stats().datagrams);
    EXPECT_EQ(2U, process.stats().bad_frames);
    EXPECT_EQ(0U, process.stats().replies);
    EXPECT_FALSE(answered()) << "none of the three drew a reply";

    // The same command for this terminal is answered.
    other.rt = kRt;
    ASSERT_EQ(Status::kOk, fmofp::bus::encode_command_word(other, command.words[0]));
    send(command);
    EXPECT_EQ(Status::kOk, process.poll(100 * kNsPerMs));
    EXPECT_EQ(1U, process.stats().replies);
    EXPECT_EQ(0U, process.stats().send_failures);
    EXPECT_TRUE(answered());
}

}  // namespace
