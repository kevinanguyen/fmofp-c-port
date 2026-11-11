"""The bus controller's command port: how a Python client queues a receive transaction (ICD README section 7, v1.23).

The controller listens on port_base + 34. A client sends a frame of type COMMAND whose words are the command word
it wants sent (a receive to a terminal's subaddress, with the data count) and the data words; the controller
queues the transaction in its next aperiodic slot and answers with a COMMAND_ACK frame: the client's transaction
number, the command word as understood, the outcome as a status code and its frame count. The scenario engine and
the debug CLI send every command this way; a test can too. Each client numbers the commands it sends per
destination (cmd_seq from 201, as the demo's scripted events do, so nothing collides with a display's own
numbering from 1).
"""

import select
import socket
import time
from dataclasses import dataclass

from fmofp_bus.command_word import CommandWord, encode_command_word
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, DEFAULT_PORT_BASE, LOOPBACK
from fmofp_bus.status import Status
from fmofp_bus.transport import MAX_FRAME_BYTES, Frame, FrameType, decode_frame, encode_frame

ACK_WORDS = 4
FIRST_CMD_SEQ = 201
MAX_DATA_WORDS = 32


@dataclass
class Acknowledgement:
    """What the controller said: OK means queued for the next frame's aperiodic slot; NOT_READY its queue was
    full; INVALID_ARGUMENT the command was not a receive to a terminal's subaddress; TIMEOUT no controller
    answered; IO_ERROR the port refused the datagram (no controller there)."""
    status: Status
    frame: int = 0         # the controller's frame count when it answered
    command_word: int = 0  # the command word as the controller read it
    cmd_seq: int = 0       # the sequence number the message carried (0 when it has no cmd_seq field)

    @property
    def queued(self):
        return self.status == Status.OK


class CommandClient:
    """A client of the command port."""

    def __init__(self, port_base=DEFAULT_PORT_BASE, timeout_s=0.5):
        self.port = port_base + COMMAND_PORT_OFFSET
        self.timeout_s = timeout_s
        self._sock = None
        self._transaction = 0
        self._sequences = {}  # (rt, subaddress) -> the last cmd_seq given
        self.sent = 0

    def open(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((LOOPBACK, 0))
        except OSError:
            sock.close()
            return Status.IO_ERROR
        sock.setblocking(False)
        self._sock = sock
        return Status.OK

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def next_cmd_seq(self, rt, subaddress):
        """The next sequence number for commands to rt/subaddress: 201 up, wrapping to 1 (0 is no command)."""
        seq = self._sequences.get((rt, subaddress), FIRST_CMD_SEQ - 1) + 1
        if seq > 255:
            seq = 1
        self._sequences[(rt, subaddress)] = seq
        return seq

    def send(self, message, rt=None):
        """Queues an ICD command message (any receive message class of fmofp_bus.icd.messages). A cmd_seq left at
        0 is given the next number for its destination; one set by the caller is kept and remembered. A message
        defined for every terminal (TERM_CMD) needs the terminal's address in `rt`."""
        rt = message.RT if rt is None else rt
        cmd_seq = 0
        if hasattr(message, "cmd_seq"):
            if message.cmd_seq == 0:
                message.cmd_seq = self.next_cmd_seq(rt, message.SUBADDRESS)
            else:
                self._sequences[(rt, message.SUBADDRESS)] = message.cmd_seq
            cmd_seq = message.cmd_seq
        status, words = message.encode()
        if status not in (Status.OK, Status.CLAMPED):
            return Acknowledgement(status, cmd_seq=cmd_seq)
        ack = self.send_words(rt, message.SUBADDRESS, words)
        ack.cmd_seq = cmd_seq
        return ack

    def send_words(self, rt, subaddress, words):
        """Queues raw data words to a terminal's subaddress and waits for the acknowledgement."""
        if not 1 <= len(words) <= MAX_DATA_WORDS:
            return Acknowledgement(Status.INVALID_ARGUMENT)
        status, command_word = encode_command_word(CommandWord(rt=rt, transmit=False, subaddress=subaddress,
                                                               count_or_mode=len(words)))
        if status != Status.OK:
            return Acknowledgement(status)
        return self.send_command_word(command_word, words)

    def send_command_word(self, command_word, words):
        """The datagram as the controller reads it: the command word to send, then the data words. The command
        port refuses anything but a receive to a terminal's subaddress (a test can ask for a transmit and see)."""
        if self._sock is None:
            return Acknowledgement(Status.NOT_READY)
        self._transaction = self._transaction % 0xFFFF + 1
        status, data = encode_frame(Frame(FrameType.COMMAND, 0, self._transaction, [command_word] + list(words)))
        if status != Status.OK:
            return Acknowledgement(status)
        try:
            self._sock.sendto(data, (LOOPBACK, self.port))
        except OSError:
            return Acknowledgement(Status.IO_ERROR)
        self.sent += 1
        return self._await_ack(self._transaction)

    def _await_ack(self, transaction):
        deadline = time.monotonic() + self.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return Acknowledgement(Status.TIMEOUT)
            ready, _, _ = select.select([self._sock], [], [], remaining)
            if not ready:
                return Acknowledgement(Status.TIMEOUT)
            try:
                data, _ = self._sock.recvfrom(MAX_FRAME_BYTES)
            except OSError:
                return Acknowledgement(Status.IO_ERROR)  # Windows: the port refused the datagram (no controller)
            status, frame = decode_frame(data)
            if (status != Status.OK or frame.type != FrameType.COMMAND_ACK or frame.transaction != transaction
                    or len(frame.words) < ACK_WORDS):
                continue  # not ours: an old acknowledgement, or noise
            try:
                outcome = Status(frame.words[1])
            except ValueError:
                outcome = Status.MALFORMED
            return Acknowledgement(outcome, (frame.words[2] << 16) | frame.words[3], frame.words[0])
