"""The bus controller's command port: how a Python client queues a receive transaction (ICD README section 7).

The controller listens on port_base + 34. A client sends a frame of type COMMAND whose words are the command word
it wants sent (a receive to a terminal's subaddress, with the data count) and the data words; the controller
queues the transaction in its next aperiodic slot and answers with a COMMAND_ACK frame: the client's transaction
number, the command word as understood, the outcome as a status code, its frame count and the sequence number it
gave the command. The scenario engine and the debug CLI send every command this way; a test can too.

The controller numbers the commands (v1.24). A terminal acts on a command only when its cmd_seq differs from the
last one it took. Until v1.24 every client counted for itself, from 201, so the first command of a second client
program carried the number of the first program's last: the controller acknowledged it and the terminal dropped
it. A message whose cmd_seq is left at 0 now goes as COMMAND_NUMBERED, with the place of its cmd_seq field, and the
controller writes the next number for that destination there: 101 to 200, a range neither the displays (which
count from 1) nor the demo's scripted events (from 201) use. A cmd_seq the caller sets is sent as it is.
"""

import select
import socket
import time
from dataclasses import dataclass

from fmofp_bus.command_word import CommandWord, encode_command_word
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, DEFAULT_PORT_BASE, LOOPBACK
from fmofp_bus.status import Status
from fmofp_bus.transport import MAX_FRAME_BYTES, Frame, FrameType, decode_frame, encode_frame

ACK_WORDS = 4            # the least an acknowledgement carries; the number given is a fifth word since v1.24
FIRST_CLIENT_NUMBER = 101
LAST_CLIENT_NUMBER = 200
MAX_DATA_WORDS = 32
NUMBER_BITS = 8

_PLACES = {}  # message class -> (word index, lowest bit) of its cmd_seq, or None


def sequence_place(cls):
    """Where a command message's cmd_seq lies in its data words: (word index, lowest bit), or None for a message
    without one. Found by encoding the message with cmd_seq 0 and with 255 and looking at what changed, so it
    follows the ICD's generated layout without a table of its own."""
    if cls in _PLACES:
        return _PLACES[cls]
    place = None
    low, high = cls(), cls()
    if hasattr(low, "cmd_seq"):
        high.cmd_seq = (1 << NUMBER_BITS) - 1
        (status_low, words_low), (status_high, words_high) = low.encode(), high.encode()
        accepted = (Status.OK, Status.CLAMPED)
        if status_low in accepted and status_high in accepted and len(words_low) == len(words_high):
            changed = [(index, a ^ b) for index, (a, b) in enumerate(zip(words_low, words_high)) if a != b]
            if len(changed) == 1:
                index, bits = changed[0]
                lowest = (bits & -bits).bit_length() - 1
                if bits == ((1 << NUMBER_BITS) - 1) << lowest:
                    place = (index, lowest)
    _PLACES[cls] = place
    return place


@dataclass
class Acknowledgement:
    """What the controller said: OK means queued for the next frame's aperiodic slot; NOT_READY its queue was
    full; INVALID_ARGUMENT the command was not a receive to a terminal's subaddress; TIMEOUT no controller
    answered; IO_ERROR the port refused the datagram (no controller there); MALFORMED it could not read the
    frame (a controller built before ICD v1.24 answers a numbered command so)."""
    status: Status
    frame: int = 0         # the controller's frame count when it answered: the frame the command goes out in
    command_word: int = 0  # the command word as the controller read it
    cmd_seq: int = 0       # the number the command carries: the controller's, or the caller's own (0: it has none)

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

    def send(self, message, rt=None):
        """Queues an ICD command message (any receive message class of fmofp_bus.icd.messages). A cmd_seq left at
        0 is numbered by the controller and the number comes back in the acknowledgement; one set by the caller
        is sent as it is (a terminal ignores it if it is the number of the last command it took). The message is
        not changed. A message defined for every terminal (TERM_CMD) needs the terminal's address in `rt`."""
        rt = message.RT if rt is None else rt
        own_number = getattr(message, "cmd_seq", 0)
        place = None
        if hasattr(message, "cmd_seq") and own_number == 0:
            place = sequence_place(type(message))
            if place is None:
                return Acknowledgement(Status.INVALID_ARGUMENT)  # a cmd_seq that is not eight bits of one word
        status, words = message.encode()
        if status not in (Status.OK, Status.CLAMPED):
            return Acknowledgement(status, cmd_seq=own_number)
        ack = self.send_words(rt, message.SUBADDRESS, words, number_at=place)
        if place is None:
            ack.cmd_seq = own_number
        return ack

    def send_words(self, rt, subaddress, words, number_at=None):
        """Queues raw data words to a terminal's subaddress and waits for the acknowledgement. With `number_at`
        (word index, lowest bit) the controller writes its next sequence number for that destination there."""
        if not 1 <= len(words) <= MAX_DATA_WORDS:
            return Acknowledgement(Status.INVALID_ARGUMENT)
        status, command_word = encode_command_word(CommandWord(rt=rt, transmit=False, subaddress=subaddress,
                                                               count_or_mode=len(words)))
        if status != Status.OK:
            return Acknowledgement(status)
        return self.send_command_word(command_word, words, number_at=number_at)

    def send_command_word(self, command_word, words, number_at=None):
        """The datagram as the controller reads it: the command word to send, where the number goes if it is to
        give one, then the data words. The command port refuses anything but a receive to a terminal's
        subaddress (a test can ask for a transmit and see)."""
        if self._sock is None:
            return Acknowledgement(Status.NOT_READY)
        self._transaction = self._transaction % 0xFFFF + 1
        frame_type, head = FrameType.COMMAND, [command_word]
        if number_at is not None:
            frame_type = FrameType.COMMAND_NUMBERED
            head.append(((number_at[0] & 0xFF) << 8) | (number_at[1] & 0xFF))
        status, data = encode_frame(Frame(frame_type, 0, self._transaction, head + list(words)))
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
            number = frame.words[4] if len(frame.words) > ACK_WORDS else 0
            return Acknowledgement(outcome, (frame.words[2] << 16) | frame.words[3], frame.words[0], number)
