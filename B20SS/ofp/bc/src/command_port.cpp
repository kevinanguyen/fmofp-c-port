#include <fmofp/bc/command_port.hpp>

#include <algorithm>
#include <array>

#include <fmofp/bus/word.hpp>

namespace fmofp::bc {

namespace {

constexpr std::uint8_t kMaxAddress = 30;  // RT 31 is the broadcast address, subaddresses 0 and 31 are mode codes

// The number that follows `last` for one destination. The first since the
// controller started is put where the frame count happens to be: a controller
// started again beside a terminal that kept running then seldom repeats the
// number that terminal took last.
std::uint8_t number_after(std::uint8_t last, std::uint32_t frame) noexcept {
    if (last == 0U) {
        return static_cast<std::uint8_t>(kFirstClientNumber + frame % kClientNumbers);
    }
    return last >= kLastClientNumber ? kFirstClientNumber : static_cast<std::uint8_t>(last + 1U);
}

}  // namespace

Status CommandPort::open(std::uint16_t port) noexcept {
    stats_ = CommandPortStats{};
    last_number_ = {};
    return socket_.open(port);
}

void CommandPort::close() noexcept { socket_.close(); }

Status CommandPort::handle(BusController& controller, const bus::Frame& frame, Answer& answer) noexcept {
    const bool numbered = frame.type == bus::FrameType::kCommandNumbered;
    if (frame.type != bus::FrameType::kCommand && !numbered) {
        return Status::kMalformed;
    }
    // The command word, where the number goes if the controller is to give one, and at least one data word.
    const std::uint8_t header_words = numbered ? std::uint8_t{2} : std::uint8_t{1};
    if (frame.word_count <= header_words) {
        return Status::kMalformed;
    }
    answer.command_word = frame.words[0];
    const bus::CommandWord cw = bus::decode_command_word(answer.command_word);
    const auto data_words = static_cast<std::uint8_t>(frame.word_count - header_words);
    // A receive to a terminal's subaddress, with the data that follows: nothing else is queued (a transmit poll
    // or a mode code would be the controller's own business).
    if (cw.transmit || cw.is_mode_code() || cw.rt < 1 || cw.rt > kMaxAddress || cw.subaddress < 1 ||
        cw.subaddress > kMaxAddress || data_words > bus::kMaxDataWords || cw.count_or_mode != data_words) {
        return Status::kInvalidArgument;  // the decoded count is 1-32, as the data count must be
    }
    if (numbered) {
        return handle_numbered(controller, frame, cw, data_words, answer);
    }
    return controller.queue_receive(cw.rt, cw.subaddress, &frame.words[1], data_words);
}

Status CommandPort::handle_numbered(BusController& controller, const bus::Frame& frame, const bus::CommandWord& cw,
                                    std::uint8_t data_words, Answer& answer) noexcept {
    // Where the number goes: the data word's index in the high byte, the field's lowest bit in the low byte.
    const unsigned index = bus::get_field(frame.words[1], 15U, 8U);
    const unsigned lowest_bit = bus::get_field(frame.words[1], 7U, 0U);
    if (index >= data_words || lowest_bit + kNumberBits > bus::kWordBits) {
        return Status::kInvalidArgument;
    }
    std::array<bus::Word, bus::kMaxDataWords> words{};
    std::copy_n(&frame.words[2], data_words, words.begin());
    const std::uint8_t number = number_after(last_number_[cw.rt][cw.subaddress], controller.stats().frames);
    words[index] = bus::set_field(words[index], lowest_bit + kNumberBits - 1U, lowest_bit, number);
    const Status queued = controller.queue_receive(cw.rt, cw.subaddress, words.data(), data_words);
    if (queued == Status::kOk) {
        // Only a command that goes out uses its number up.
        last_number_[cw.rt][cw.subaddress] = number;
        answer.number = number;
        ++stats_.numbered;
    }
    return queued;
}

Status CommandPort::handle_monitor(BusController& controller, const bus::Frame& frame, std::uint16_t from_port,
                                   osal::Nanoseconds time_now) noexcept {
    if (frame.word_count != 1 || from_port == 0) {
        return Status::kMalformed;
    }
    if (frame.words[0] == kMonitorStop) {
        controller.remove_monitor_listener(from_port);
        return Status::kOk;
    }
    if (frame.words[0] != kMonitorStart) {
        return Status::kInvalidArgument;
    }
    return controller.add_monitor_listener(from_port, time_now + kMonitorLease);  // kNotReady: no room for another
}

void CommandPort::count(Status outcome) noexcept {
    ++stats_.received;
    if (outcome == Status::kOk) {
        ++stats_.queued;
    } else if (outcome == Status::kMalformed || outcome == Status::kBadMagic || outcome == Status::kBadLength) {
        ++stats_.malformed;
    } else {
        ++stats_.refused;
    }
}

void CommandPort::acknowledge(std::uint16_t port, bus::Word transaction, const Answer& answer, Status outcome,
                              std::uint32_t frame) noexcept {
    bus::Frame ack{};
    ack.type = bus::FrameType::kCommandAck;
    ack.transaction = transaction;
    ack.word_count = kAckWords;
    ack.words[0] = answer.command_word;
    ack.words[1] = static_cast<bus::Word>(outcome);
    ack.words[2] = static_cast<bus::Word>(frame >> 16U);
    ack.words[3] = static_cast<bus::Word>(frame & 0xFFFFU);
    ack.words[4] = answer.number;
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
    const osal::Nanoseconds time_now = osal::now();
    controller.expire_monitor_listeners(time_now);
    unsigned queued = 0;
    std::array<std::uint8_t, bus::kMaxFrameBytes> bytes{};
    for (std::size_t n = 0; n < kMaxCommandsPerFrame; ++n) {
        std::size_t length = 0;
        std::uint16_t from_port = 0;
        const Status got = socket_.receive(bytes.data(), bytes.size(), length, 0, &from_port);
        if (got == Status::kTimeout) {
            break;  // the port is drained
        }
        if (got != Status::kOk) {
            count(Status::kMalformed);  // too long to be a frame: dropped by the socket, nobody to answer
            continue;
        }
        bus::Frame frame{};
        Answer answer{};
        Status outcome = bus::decode_frame(bytes.data(), length, frame);
        if (outcome == Status::kOk && frame.type == bus::FrameType::kMonitorRequest) {
            ++stats_.monitor_requests;
            outcome = handle_monitor(controller, frame, from_port, time_now);
        } else {
            if (outcome == Status::kOk) {
                outcome = handle(controller, frame, answer);
            }
            count(outcome);
            if (outcome == Status::kOk) {
                ++queued;
            }
        }
        if (from_port != 0) {
            acknowledge(from_port, frame.transaction, answer, outcome, controller.stats().frames);
        }
    }
    return queued;
}

}  // namespace fmofp::bc
