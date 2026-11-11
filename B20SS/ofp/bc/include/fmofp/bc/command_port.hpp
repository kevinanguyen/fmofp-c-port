#ifndef FMOFP_BC_COMMAND_PORT_HPP
#define FMOFP_BC_COMMAND_PORT_HPP

#include <cstddef>
#include <cstdint>

#include <fmofp/bc/bus_controller.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/bus/transport.hpp>
#include <fmofp/osal/udp.hpp>

// The bus controller's command port (ICD README section 7, v1.23): a UDP port
// at port_base + 34 on which a client (the scenario engine, the debug CLI, a
// test) asks for a receive transaction to be sent. The client's datagram is a
// frame of type kCommand whose words are the command word it wants sent (a
// receive to RT 1-30, subaddress 1-30, with its data count) followed by the
// data words. The controller drains the port once per minor frame, queues each
// valid command in its aperiodic slot (the next frame's) and answers the sender
// with a kCommandAck frame: the client's transaction number, the command word
// as understood, the outcome as a status code and the controller's frame count,
// high word then low. The queued transaction then shows on the monitor like any
// other. Test equipment's way in, not flight code's: nothing on the bus depends
// on it.

namespace fmofp::bc {

constexpr std::uint8_t kCommandPortOffset = 34;
constexpr std::size_t kMaxCommandsPerFrame = kAperiodicQueueDepth;
constexpr std::uint8_t kAckWords = 4;

struct CommandPortStats {
    std::uint32_t received{0};      // datagrams taken off the port
    std::uint32_t queued{0};        // commands handed to the controller
    std::uint32_t refused{0};       // well-formed frames the controller would not take (not a receive, bad address, queue full)
    std::uint32_t malformed{0};     // datagrams that were not a command frame
    std::uint32_t ack_failures{0};  // acknowledgements that could not be sent
};

class CommandPort {
public:
    [[nodiscard]] Status open(std::uint16_t port) noexcept;
    void close() noexcept;
    [[nodiscard]] bool is_open() const noexcept { return socket_.is_open(); }

    // Drains the port (at most kMaxCommandsPerFrame datagrams), queues what is valid on the controller and
    // acknowledges every sender. Returns how many commands were queued.
    unsigned poll(BusController& controller) noexcept;

    [[nodiscard]] const CommandPortStats& stats() const noexcept { return stats_; }

private:
    [[nodiscard]] static Status handle(BusController& controller, const bus::Frame& frame,
                                       bus::Word& command_word) noexcept;
    void acknowledge(std::uint16_t port, bus::Word transaction, bus::Word command_word, Status outcome,
                     std::uint32_t frame) noexcept;

    osal::UdpSocket socket_{};
    CommandPortStats stats_{};
};

}  // namespace fmofp::bc

#endif
