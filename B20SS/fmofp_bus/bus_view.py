"""A live picture of the bus, read from the controller's monitor stream: the frame count (the controller's
synchronise mode codes), the latest decoded message of every kind, each terminal's last TERM_STATUS and when it
last answered. The scenario engine takes its clock from it and the debug CLI its status; the demo's dashboard does
the same job its own way.

Since v1.24 the view asks the controller for its own copy of the stream (fmofp_bus.monitor), so it runs beside the
demo's dashboard, which holds the one fixed monitor port, and beside other views. Its frame count is the
controller's own, the number an acknowledgement from the command port carries, whenever the view joined: each
synchronise word carries the count's low part and the controller's answers to the view's requests the rest."""

import threading
import time

from fmofp_bus.icd import messages as m
from fmofp_bus.monitor import Monitor
from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.status import Status

SYNC_MODE_CODE = 17  # SYNCHRONIZE_WITH_DATA, broadcast once per minor frame
SYNC_HZ = 50
# The synchronise word (bc/schedule.cpp): the major frame's low ten bits above the minor frame's six.
SYNC_MINOR_BITS = 6
SYNC_MAJOR_MODULUS = 1024
SYNC_MODULUS = SYNC_MAJOR_MODULUS * SYNC_HZ  # the frame counts a synchronise word can tell apart


def sync_frame(word):
    """The frame count a synchronise word carries, modulo SYNC_MODULUS."""
    return ((word >> SYNC_MINOR_BITS) % SYNC_MAJOR_MODULUS) * SYNC_HZ + (word & ((1 << SYNC_MINOR_BITS) - 1))


def nearest_frame(count, reference):
    """The frame number nearest `reference` that a synchronise word carrying `count` can mean."""
    half = SYNC_MODULUS // 2
    return max(0, reference + (count - reference + half) % SYNC_MODULUS - half)

# The ICD's terminal table (fmofp_icd.xml <terminals>), for the CLI's status lines.
TERMINAL_NAMES = {1: "avionics", 2: "comms", 3: "engine", 4: "ecs", 5: "fcs", 6: "mission", 7: "nav", 8: "power",
                  9: "radar", 10: "sensors", 11: "pfd", 12: "fms", 13: "mfd", 14: "eicas", 15: "radar display",
                  16: "tsd", 17: "sms", 18: "hud", 19: "hydraulics", 20: "airframe", 21: "surfaces", 22: "defensive",
                  23: "fdm", 26: "cas", 27: "plant", 28: "stores", 31: "broadcast"}

# Transmit messages by address: (rt, subaddress) -> class; TERM_STATUS is every terminal's.
BY_ADDRESS = {(info.rt, info.subaddress): info.cls for info in m.MESSAGES if info.direction == "T"}


def terminal_name(rt):
    return TERMINAL_NAMES.get(rt, f"rt {rt}")


def terminal_address(text):
    """An address from a number or a name in the terminal table; None for neither."""
    try:
        return int(text, 0)
    except ValueError:
        pass
    wanted = text.strip().lower()
    for rt, name in TERMINAL_NAMES.items():
        if name == wanted:
            return rt
    return None


class BusView(threading.Thread):
    """Drains the monitor on its own thread; read `frame`, `latest`, `term_status` and `last_answer` under `lock`,
    or through `snapshot()`."""

    def __init__(self, port_base=DEFAULT_PORT_BASE, subscribe=True):
        """`subscribe=False` listens on the fixed monitor port instead of asking for a copy: for a controller
        whose command port is closed, and only while nobody else holds that port."""
        super().__init__(daemon=True, name="BusView")
        self.monitor = Monitor(port_base, subscribe=subscribe)
        self.lock = threading.Lock()
        self.frame = -1            # the controller's frame count at the last synchronise seen; -1 before the first
        self.frames_seen = 0       # the synchronise codes seen: how long the view has been watching, in frames
        self._answers = 0          # the controller's answers already used to place the frame count
        self.records = 0
        self.latest = {}           # message class (or (TermStatus, rt)) -> the last decoded message
        self.term_status = {}      # rt -> the last TERM_STATUS
        self.last_answer = {}      # rt -> time.monotonic() of the last answered poll
        self.last_poll = {}        # rt -> time.monotonic() of the last poll, answered or not
        self._halt = threading.Event()  # not `_stop`: Thread has a method of that name

    def open(self):
        return self.monitor.open()

    def close(self):
        self._halt.set()
        if self.is_alive():
            self.join(timeout=2.0)
        self.monitor.close()

    def run(self):
        while not self._halt.is_set():
            record = self.monitor.read(0.02)
            if record is not None:
                self.take(record, time.monotonic())

    def take(self, record, now):
        """One monitor record into the picture."""
        cw = record.command
        with self.lock:
            self.records += 1
            if cw.is_mode_code:
                if cw.count_or_mode == SYNC_MODE_CODE:
                    self._count_frame(record)
                return
            if cw.is_broadcast:
                return
            self.last_poll[cw.rt] = now
            if not record.answered:
                return
            self.last_answer[cw.rt] = now
            if not cw.transmit:
                return
            cls = BY_ADDRESS.get((cw.rt, cw.subaddress))
            if cls is None and cw.subaddress == m.TermStatus.SUBADDRESS:
                cls = m.TermStatus
            if cls is None:
                return
            status, message = cls.decode(record.received)
            if status != Status.OK:
                return
            if cls is m.TermStatus:
                self.term_status[cw.rt] = message
                self.latest[(m.TermStatus, cw.rt)] = message
            else:
                self.latest[cls] = message

    def _count_frame(self, record):
        """A synchronise code: a new frame. Its word says which, give or take a whole turn of the word's count
        (about seventeen minutes of bus time); the controller's last answer to this view, or the frame before,
        says which turn. Called under the lock."""
        self.frames_seen += 1
        if not record.sent:
            self.frame += 1  # a synchronise without its word: count it
            return
        count = sync_frame(record.sent[0])
        if self.monitor.answers != self._answers and self.monitor.controller_frame is not None:
            self._answers = self.monitor.answers
            reference = self.monitor.controller_frame
        else:
            reference = self.frame + 1 if self.frame >= 0 else count
        self.frame = nearest_frame(count, reference)

    def snapshot(self):
        with self.lock:
            return dict(frame=self.frame, frames_seen=self.frames_seen, records=self.records,
                        latest=dict(self.latest),
                        term_status=dict(self.term_status), last_answer=dict(self.last_answer),
                        last_poll=dict(self.last_poll))

    def current_frame(self):
        with self.lock:
            return self.frame

    def wait_for_frame(self, frame, timeout_s):
        """True once the bus has reached `frame`, False after timeout_s."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.current_frame() >= frame:
                return True
            time.sleep(0.005)
        return self.current_frame() >= frame

    def frames_watched(self):
        with self.lock:
            return self.frames_seen

    def wait_until_watched(self, frames, timeout_s):
        """True once the view has seen `frames` frames go by, False after timeout_s. A view that has just joined
        knows nothing yet: every terminal's TERM_STATUS comes round once a second, the slowest messages too, so
        a picture of the whole bus takes a major frame (50 frames)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.frames_watched() >= frames:
                return True
            time.sleep(0.005)
        return self.frames_watched() >= frames
