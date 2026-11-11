#include <fmofp/bc/command_port.hpp>

#include <array>

#include <fmofp/bus/command_word.hpp>

namespace fmofp::bc {

namespace {

constexpr std::uint8_t kMaxAddress = 30;  // RT 31 is the broadcast address, subaddresses 0 and 31 are mode codes

}  // namespace

Status CommandPort::open(std::uint16_t port) noexcept {
    stats_ = CommandPortStats{};
    return socket_.open(port);
}

void CommandPort::close() noexcept { socket_.close(); }

Status CommandPort::handle(BusController& controller, const bus::Frame& frame, bus::Word& command_word) noexcept {
    if (frame.type != bus::FrameType::kCommand || frame.word_count < 2) {
        return Status::kMalformed;  // a command needs its command word and at least one data word
    }
    command_word = frame.words[0];
    const bus::CommandWord cw = bus::decode_command_word(command_word);
    const auto data_words = static_cast<std::uint8_t>(frame.word_count - 1);
    // A receive to a terminal's subaddress, with the data that follows: nothing else is queued (a transmit poll
    // or a mode code would be the controller's own business).
    if (cw.transmit || cw.is_mode_code() || cw.rt < 1 || cw.rt > kMaxAddress || cw.subaddress < 1 ||
        cw.subaddress > kMaxAddress || data_words > bus::kMaxDataWords || cw.count_or_mode != data_words) {
        return Status::kInvalidArgument;  // the decoded count is 1-32, as the data count must be
    }
    return controller.queue_receive(cw.rt, cw.subaddress, &frame.words[1], data_words);
}

void CommandPort::acknowledge(std::uint16_t port, bus::Word transaction, bus::Word command_word, Status outcome,
                              std::uint32_t frame) noexcept {
    bus::Frame ack{};
    ack.type = bus::FrameType::kCommandAck;
    ack.transaction = transaction;
    ack.word_count = kAckWords;
    ack.words[0] = command_word;
    ack.words[1] = static_cast<bus::Word>(outcome);
    ack.words[2] = static_cast<bus::Word>(frame >> 16U);
    ack.words[3] = static_cast<bus::Word>(frame & 0xFFFFU);
    std::array<std::uint8_t, bus::kMaxFrameBytes> bytes{};
    std::size_t length = 0;
    if (bus::encode_frame(ack, bytes.data(), bytes.size(), length) != Status::kOk ||
        socket_.send_to(port, bytes.data(), length) != Status::kOk) {
        ++stats_.ack_failures;
    }
}

unsigned CommandPort::poll(BusController& controller) noexcept {
    if (!socket_.is_open()) {
        return 0;
    }
    unsigned queued = 0;
    std::array<std::uint8_t, bus::kMaxFrameBytes> bytes{};
    for (std::size_t n = 0; n < kMaxCommandsPerFrame; ++n) {
        std::size_t length = 0;
        std::uint16_t from_port = 0;
        const Status got = socket_.receive(bytes.data(), bytes.size(), length, 0, &from_port);
        if (got == Status::kTimeout) {
            break;  // the port is drained
        }
        ++stats_.received;
        if (got != Status::kOk) {
            ++stats_.malformed;  // too long to be a frame: dropped by the socket, nobody to answer
            continue;
        }
        bus::Frame frame{};
        bus::Word command_word = 0;
        Status outcome = bus::decode_frame(bytes.data(), length, frame);
        if (outcome == Status::kOk) {
            outcome = handle(controller, frame, command_word);
        }
        if (outcome == Status::kOk) {
            ++stats_.queued;
            ++queued;
        } else if (outcome == Status::kMalformed || outcome == Status::kBadMagic || outcome == Status::kBadLength) {
            ++stats_.malformed;
        } else {
            ++stats_.refused;
        }
        if (from_port != 0) {
            acknowledge(from_port, frame.transaction, command_word, outcome, controller.stats().frames);
        }
    }
    return queued;
}

}  // namespace fmofp::bc
