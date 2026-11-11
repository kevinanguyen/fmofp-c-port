"""A live picture of the bus, read from the controller's monitor port: the frame count (the controller's
synchronise mode codes), the latest decoded message of every kind, each terminal's last TERM_STATUS and when it
last answered. The scenario engine takes its clock from it and the debug CLI its status; the demo's dashboard does
the same job its own way."""

import threading
import time

from fmofp_bus.icd import messages as m
from fmofp_bus.monitor import Monitor
from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.status import Status

SYNC_MODE_CODE = 17  # SYNCHRONIZE_WITH_DATA, broadcast once per minor frame
SYNC_HZ = 50

# The ICD's terminal table (fmofp_icd.xml <terminals>), for the CLI's status lines.
TERMINAL_NAMES = {1: "avionics", 2: "comms", 3: "engine", 4: "ecs", 5: "fcs", 6: "mission", 7: "nav", 8: "power",
                  9: "radar", 10: "sensors", 11: "pfd", 12: "fms", 13: "mfd", 14: "eicas", 15: "radar display",
                  16: "tsd", 17: "sms", 18: "hud", 19: "hydraulics", 20: "airframe", 21: "surfaces", 22: "defensive",
                  23: "fdm", 27: "plant", 31: "broadcast"}

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

    def __init__(self, port_base=DEFAULT_PORT_BASE):
        super().__init__(daemon=True, name="BusView")
        self.monitor = Monitor(port_base)
        self.lock = threading.Lock()
        self.frame = -1            # the minor frames seen: the controller's count, from its first sync
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
                    self.frame += 1
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

    def snapshot(self):
        with self.lock:
            return dict(frame=self.frame, records=self.records, latest=dict(self.latest),
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
