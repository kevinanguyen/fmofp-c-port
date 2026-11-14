#ifndef FMOFP_BC_COMMAND_PORT_HPP
#define FMOFP_BC_COMMAND_PORT_HPP

#include <array>
#include <cstddef>
#include <cstdint>

#include <fmofp/bc/bus_controller.hpp>
#include <fmofp/bus/command_word.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/bus/transport.hpp>
#include <fmofp/osal/clock.hpp>
#include <fmofp/osal/udp.hpp>

// The bus controller's command port (ICD README section 7, v1.23): a UDP port
// at port_base + 34 on which a client (the scenario engine, the debug CLI, a
// test) asks for a receive transaction to be sent. The client's datagram is a
// frame of type kCommand whose words are the command word it wants sent (a
// receive to RT 1-30, subaddress 1-30, with its data count) followed by the
// data words. The controller drains the port once per minor frame, queues each
// valid command in its aperiodic slot (the next frame's) and answers the sender
// with a kCommandAck frame: the client's transaction number, the command word
// as understood, the outcome as a status code, the controller's frame count,
// high word then low, and the sequence number it gave the command (0 if none).
// The queued transaction then shows on the monitor like any other. Test
// equipment's way in, not flight code's: nothing on the bus depends on it.
//
// Since v1.24 the port takes two more requests.
//
// kCommandNumbered is a kCommand whose second word says where the command's
// cmd_seq field lies (the data word's index in the high byte, the field's
// lowest bit in the low byte); the controller writes the number there. A
// terminal acts on a command only when its number differs from the last one it
// took, so clients that each counted for themselves repeated one another's
// numbers and had their commands dropped unseen. The controller counts once
// for all of them, per destination, in a range nobody else uses.
//
// kMonitorRequest (one word: kMonitorStart or kMonitorStop) asks for a copy of
// every monitor record on the port the request came from, for kMonitorLease
// from now; a client repeats it about once a second while it listens. The fixed
// monitor port has room for one listener, and the demo's dashboard is it.

namespace fmofp::bc {

constexpr std::uint8_t kCommandPortOffset = 34;
constexpr std::size_t kMaxCommandsPerFrame = kAperiodicQueueDepth;
constexpr std::uint8_t kAckWords = 5;

// The numbers given to the clients' commands. The displays count their own
// commands from 1 and the demo's script from 201: a number from here never
// equals the last one a terminal took from either.
constexpr std::uint8_t kFirstClientNumber = 101;
constexpr std::uint8_t kLastClientNumber = 200;
constexpr std::uint32_t kClientNumbers = 100;
constexpr unsigned kNumberBits = 8U;

constexpr bus::Word kMonitorStop = 0;
constexpr bus::Word kMonitorStart = 1;
constexpr osal::Nanoseconds kMonitorLease = 3 * osal::kNsPerS;

struct CommandPortStats {
    std::uint32_t received{0};      // command datagrams taken off the port (monitor requests are counted apart)
    std::uint32_t queued{0};        // commands handed to the controller
    std::uint32_t refused{0};       // well-formed frames the controller would not take (not a receive, bad address, queue full)
    std::uint32_t malformed{0};     // datagrams that were not a command frame
    std::uint32_t ack_failures{0};  // acknowledgements that could not be sent
    std::uint32_t numbered{0};          // queued commands the controller numbered
    std::uint32_t monitor_requests{0};  // monitor requests taken off the port, granted or not
};

class CommandPort {
public:
    [[nodiscard]] Status open(std::uint16_t port) noexcept;
    void close() noexcept;
    [[nodiscard]] bool is_open() const noexcept { return socket_.is_open(); }

    // Drains the port (at most kMaxCommandsPerFrame datagrams), queues what is valid on the controller, grants
    // and expires the monitor listeners and acknowledges every sender. Returns how many commands were queued.
    unsigned poll(BusController& controller) noexcept;

    [[nodiscard]] const CommandPortStats& stats() const noexcept { return stats_; }

private:
    // What the acknowledgement carries beside the outcome.
    struct Answer {
        bus::Word command_word{0};
        std::uint8_t number{0};
    };

    [[nodiscard]] Status handle(BusController& controller, const bus::Frame& frame, Answer& answer) noexcept;
    [[nodiscard]] Status handle_numbered(BusController& controller, const bus::Frame& frame,
                                         const bus::CommandWord& cw, std::uint8_t data_words,
                                         Answer& answer) noexcept;
    [[nodiscard]] static Status handle_monitor(BusController& controller, const bus::Frame& frame,
                                               std::uint16_t from_port, osal::Nanoseconds time_now) noexcept;
    void count(Status outcome) noexcept;
    void acknowledge(std::uint16_t port, bus::Word transaction, const Answer& answer, Status outcome,
                     std::uint32_t frame) noexcept;

    osal::UdpSocket socket_{};
    CommandPortStats stats_{};
    // The last number given per destination, [rt][subaddress]; 0 until the first.
    std::array<std::array<std::uint8_t, bus::kMaxSubaddress + 1>, bus::kBroadcastRt> last_number_{};
};

}  // namespace fmofp::bc

#endif
