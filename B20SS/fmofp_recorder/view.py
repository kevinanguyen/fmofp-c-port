"""The recorder's picture of the bus: the monitor stream as the display feeds read a terminal.

`RecordingView` is a `BusView` (it subscribes to a copy of the monitor stream, so it runs beside the demo) that also
keeps when each producer's message was last seen and collects the producers' blocks from their descriptor and
segment transmits. It answers the two calls the display feeds make of a terminal, `fresh(cls, stale_after_s)` and
`latest_block(cls)`, for the consumer's class (a relay or a broadcast copy, as the feeds name it) by returning the
producer's message: a relay copies the producer's words, so the two are the same data.
"""

import time
from types import SimpleNamespace

from fmofp_bus.block import DESCRIPTOR_WORDS, SEGMENT_WORDS, BlockReceiver
from fmofp_bus.bus_view import BY_ADDRESS, BusView
from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.status import Status

# Consumer message id -> producer message id, for every relay and broadcast copy.
_PRODUCER_OF = {r.to_id: r.from_id for r in m.RELAYS}
_MESSAGE_ID = {info.cls: info.id for info in m.MESSAGES}
# The blocks terminals transmit: (rt, descriptor sa) and (rt, segment sa) -> the block's info.
_TRANSMIT_BLOCKS = [info for info in b.BLOCKS if info.direction == "T"]
_BY_DESCRIPTOR = {(info.rt, info.descriptor_subaddress): info for info in _TRANSMIT_BLOCKS}
_BY_SEGMENT = {(info.rt, info.segment_subaddress): info for info in _TRANSMIT_BLOCKS}


def producer_class(cls):
    """The class whose transmit carries `cls`'s data: `cls` itself for a producer's message, the producer's for a
    relayed or broadcast copy."""
    message_id = _MESSAGE_ID.get(cls)
    while message_id in _PRODUCER_OF:
        message_id = _PRODUCER_OF[message_id]
    return m.MESSAGE_CLASSES.get(message_id, cls)


def producer_block(cls):
    """The layout class a block's transmits decode to: a relayed copy's `LAYOUT` (the producer's), or `cls`."""
    return getattr(cls, "LAYOUT", cls)


class RecordingView(BusView):
    def __init__(self, port_base=DEFAULT_PORT_BASE, subscribe=True, clock=time.monotonic):
        super().__init__(port_base, subscribe=subscribe)
        self.clock = clock
        self.latest_at = {}   # producer class -> clock() when its message was last decoded
        self.blocks = {}      # producer block class -> (decoded block, version, clock() when completed)
        self._receivers = {info.cls: BlockReceiver(info.max_payload_words) for info in _TRANSMIT_BLOCKS}

    def take(self, record, now):
        super().take(record, now)
        cw = record.command
        if cw.is_mode_code or cw.is_broadcast or not cw.transmit or not record.answered:
            return
        stamp = self.clock()
        cls = BY_ADDRESS.get((cw.rt, cw.subaddress))
        if cls is not None:
            with self.lock:
                if cls in self.latest:
                    self.latest_at[cls] = stamp
            return
        info = _BY_DESCRIPTOR.get((cw.rt, cw.subaddress))
        if info is not None and len(record.received) == DESCRIPTOR_WORDS:
            self._block_words(info, record.received, descriptor=True, stamp=stamp)
            return
        info = _BY_SEGMENT.get((cw.rt, cw.subaddress))
        if info is not None and len(record.received) == SEGMENT_WORDS:
            self._block_words(info, record.received, descriptor=False, stamp=stamp)

    def _block_words(self, info, words, descriptor, stamp):
        rx = self._receivers[info.cls]
        done = rx.feed_descriptor(words) if descriptor else rx.feed_segment(words)
        if not done:
            return
        status, block = info.cls.decode(rx.payload)
        if status == Status.OK and block is not None:
            with self.lock:
                self.blocks[info.cls] = (block, rx.version, stamp)

    # ---- the terminal calls the display feeds make ----

    def fresh(self, cls, stale_after_s):
        producer = producer_class(cls)
        with self.lock:
            message = self.latest.get(producer)
            stamp = self.latest_at.get(producer)
        if message is None or stamp is None or self.clock() - stamp > stale_after_s:
            return None
        # A consumer's class wraps the producer's layout in `payload`; the producer's own class is the layout.
        return SimpleNamespace(payload=message) if producer is not cls else message

    def latest_block(self, cls):
        with self.lock:
            entry = self.blocks.get(producer_block(cls))
        if entry is None:
            return None, None, None
        block, version, stamp = entry
        return block, version, self.clock() - stamp
