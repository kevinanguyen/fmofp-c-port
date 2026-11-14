"""Reading the bus controller's monitor stream (ICD README section 7).

The controller copies every completed transaction to port_base + 33 as a
frame of type MONITOR: the command words as sent, then the reply words
(status word first) if there was one. This is what a bus recorder, and the
tests, listen to.

That port has room for one listener, and while the demo runs its dashboard is
the one. Since v1.24 a client asks the controller's command port for a copy of
the stream on a port of its own instead (Monitor(port_base, subscribe=True)):
the scenario engine and the debug prompt listen that way, beside the dashboard
and beside each other.
"""

import select
import socket
import time
from dataclasses import dataclass, field
from typing import List, Optional

from fmofp_bus.command_word import CommandWord, StatusWord, decode_command_word, decode_status_word
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, LOOPBACK, MONITOR_PORT_OFFSET
from fmofp_bus.status import Status
from fmofp_bus.transport import MAX_FRAME_BYTES, Frame, FrameType, decode_frame, encode_frame

MONITOR_STOP = 0   # the one word of a MONITOR_REQUEST frame
MONITOR_START = 1
RENEW_S = 1.0      # a request holds three seconds at the controller: asked again every second while reading
RETRY_S = 0.1      # and ten times a second until the controller has granted one (it may not be up yet)


@dataclass
class MonitorRecord:
    transaction: int
    command: CommandWord
    sent: List[int] = field(default_factory=list)      # data words the BC sent with the command
    status: Optional[StatusWord] = None                # None when nobody answered (or broadcast)
    received: List[int] = field(default_factory=list)  # data words that came back after the status

    @property
    def answered(self):
        return self.status is not None


def parse_record(frame):
    """A MonitorRecord from a MONITOR frame, or None if the frame is not one."""
    if frame.type != FrameType.MONITOR or frame.word_count < 1:
        return None
    cw = decode_command_word(frame.words[0])
    sent_count = 0
    if cw.is_mode_code:
        sent_count = 1 if (not cw.transmit and frame.word_count >= 2) else 0
    elif not cw.transmit:
        sent_count = cw.count_or_mode
    sent = frame.words[1:1 + sent_count]
    rest = frame.words[1 + sent_count:]
    record = MonitorRecord(frame.transaction, cw, sent)
    if rest:
        _, record.status = decode_status_word(rest[0])
        record.received = rest[1:]
    return record


class Monitor:
    """A listener to the monitor stream.

    Monitor(port_base) binds the fixed monitor port: one listener at a time.
    Monitor(port_base, subscribe=True) binds a port of its own and asks the
    controller's command port to copy the stream there (v1.24); the controller
    serves a few such listeners at once. The request holds three seconds and
    read() repeats it every second, so a subscriber has to keep reading (after
    a pause it misses what went by and picks the stream up again).
    """

    def __init__(self, port_base=51000, subscribe=False):
        self.port = port_base + MONITOR_PORT_OFFSET
        self.subscribe = subscribe
        self.command_port = port_base + COMMAND_PORT_OFFSET
        self.granted = None           # the controller's last answer to a request (a Status); None before the first
        self.controller_frame = None  # its frame count in that answer: the frame it was about to run
        self.answers = 0              # how many answers have come
        self._sock = None
        self._asked = 0.0
        self._transaction = 0

    def open(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((LOOPBACK, 0 if self.subscribe else self.port))
        except OSError:
            sock.close()
            return Status.IO_ERROR
        sock.setblocking(False)
        # As much room as the system allows: a free-running bus produces
        # records faster than a reader that only drains afterwards can take
        # them (Linux caps this at net.core.rmem_max; see read_until).
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        except OSError:
            pass
        self._sock = sock
        if self.subscribe:
            self._ask(MONITOR_START)
        return Status.OK

    def close(self):
        if self._sock is not None:
            if self.subscribe:
                self._ask(MONITOR_STOP)  # the controller stops sending at once rather than three seconds on
            self._sock.close()
            self._sock = None

    def _ask(self, word):
        """One MONITOR_REQUEST to the controller's command port. No controller there yet is no error: the next
        request, a second later, finds it."""
        self._asked = time.monotonic()
        self._transaction = self._transaction % 0xFFFF + 1
        status, data = encode_frame(Frame(FrameType.MONITOR_REQUEST, 0, self._transaction, [word]))
        if status != Status.OK:
            return
        try:
            self._sock.sendto(data, (LOOPBACK, self.command_port))
        except OSError:
            pass

    def _take_answer(self, frame):
        """The controller's answer to a request: its outcome (OK, or NOT_READY when it serves as many listeners
        as it can) and its frame count."""
        if len(frame.words) < 4:
            return
        try:
            self.granted = Status(frame.words[1])
        except ValueError:
            self.granted = Status.MALFORMED
        self.controller_frame = (frame.words[2] << 16) | frame.words[3]
        self.answers += 1

    def read(self, timeout_s):
        """The next record within timeout_s, or None."""
        if self._sock is None:
            return None
        if not self.subscribe:
            ready, _, _ = select.select([self._sock], [], [], max(0.0, timeout_s))
            if not ready:
                return None
            try:
                data, _ = self._sock.recvfrom(MAX_FRAME_BYTES * 2)
            except OSError:
                return None
            status, frame = decode_frame(data)
            if status != Status.OK:
                return None
            return parse_record(frame)
        # A subscriber's port also takes the controller's answers to its requests, which are no records.
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if time.monotonic() - self._asked >= (RENEW_S if self.granted == Status.OK else RETRY_S):
                self._ask(MONITOR_START)
            ready, _, _ = select.select([self._sock], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                return None
            try:
                data, _ = self._sock.recvfrom(MAX_FRAME_BYTES * 2)
            except OSError:
                data = None  # Windows: the last request found nobody on the command port
            status, frame = decode_frame(data) if data is not None else (Status.IO_ERROR, None)
            if status == Status.OK and frame.type == FrameType.COMMAND_ACK:
                self._take_answer(frame)
            elif status == Status.OK:
                return parse_record(frame)
            if time.monotonic() >= deadline:
                return None

    def read_until(self, done, idle_s=0.05):
        """Every record until done() is true and the port has then been quiet for idle_s.

        Reading while the bus runs is what keeps a long free-running run from
        overflowing the socket's receive buffer.
        """
        records = []
        while not done():
            record = self.read(0.01)
            if record is not None:
                records.append(record)
        records.extend(self.drain(idle_s))
        return records

    def drain(self, idle_s=0.05):
        """Every record until the port has been quiet for idle_s."""
        records = []
        while True:
            record = self.read(idle_s)
            if record is None:
                return records
            records.append(record)
