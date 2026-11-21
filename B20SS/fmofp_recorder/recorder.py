"""The recorder: the monitor stream into the Python services' SQLite tables, at their rates in bus frames."""

import os
import sqlite3
import time

from fmofp_display.systems_feed import SystemsFeed
from fmofp_display.terminal import STALE_AFTER_S
from fmofp_recorder import tables as t

B20SS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(B20SS, "logs", "recorder")


class Recorder:
    """Writes `tables.TABLES` from a view that answers the display feeds' calls (`RecordingView`, or a fake)."""

    def __init__(self, view, out_dir=DEFAULT_OUT, stale_after_s=STALE_AFTER_S, wall_clock=time.time):
        self.view = view
        self.out_dir = out_dir
        self.stale_after_s = stale_after_s
        self.wall_clock = wall_clock
        self.feed = SystemsFeed(view, stale_after_s=stale_after_s, clock=wall_clock)
        self.connections = {}
        self.slots = {}               # table name -> the last period slot written
        self.last_frame = None
        self.rows_written = {table.name: 0 for table in t.TABLES}
        # Per-table state the Python services kept.
        self.defensive_last = None
        self.fuel_set_up = False
        self.mission_position = dict(t.MISSION_START_POSITION)

    def open(self):
        os.makedirs(self.out_dir, exist_ok=True)
        for database in t.DATABASES:
            # One writer, but `open()` and the loop may run on different threads (a test opens, a thread steps).
            conn = sqlite3.connect(os.path.join(self.out_dir, database), check_same_thread=False)
            self.connections[database] = conn
        for table in t.TABLES:
            self.connections[table.database].execute(t.create_sql(table))
        for conn in self.connections.values():
            conn.commit()

    def close(self):
        for conn in self.connections.values():
            conn.commit()
            conn.close()
        self.connections = {}

    def step(self, frame):
        """One look at the bus at the controller's frame `frame`: every table due in it writes. Returns the rows."""
        if frame is None or frame < 0 or frame == self.last_frame:
            return 0
        if self.last_frame is not None and frame < self.last_frame:
            self.slots.clear()      # the controller started again: its frame count with it
        self.last_frame = frame
        now = self.wall_clock()
        written = 0
        for table in t.TABLES:
            if table.rows is None:
                continue
            if table.period_frames:
                slot = frame // table.period_frames
                if self.slots.get(table.name) == slot:
                    continue
                self.slots[table.name] = slot
            written += self._write(table.rows(self, now))
        if written:
            for conn in self.connections.values():
                conn.commit()
        return written

    def _write(self, rows):
        for row in rows:
            sql, params = t.row_sql(row)
            self.connections[t.TABLE_BY_NAME[row.table].database].execute(sql, params)
            self.rows_written[row.table] += 1
        return len(rows)


# ---- reading back, for the prompt ----

def list_tables(out_dir=DEFAULT_OUT):
    """[(database file, table, row count)] of every database in `out_dir`, in file and table order."""
    out = []
    if not os.path.isdir(out_dir):
        return out
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".db"):
            continue
        conn = sqlite3.connect(f"file:{os.path.join(out_dir, name)}?mode=ro", uri=True)
        try:
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE "
                                         "'sqlite_%' ORDER BY name"):
                count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                out.append((name, table, count))
        finally:
            conn.close()
    return out


def read_table(name, last=10, out_dir=DEFAULT_OUT):
    """(columns, rows) of the table `name`'s last `last` rows, oldest first, or None when no database has it."""
    for database, table, _ in list_tables(out_dir):
        if table != name:
            continue
        conn = sqlite3.connect(f"file:{os.path.join(out_dir, database)}?mode=ro", uri=True)
        try:
            cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT ?', (max(1, int(last)),))
            rows = cursor.fetchall()
            columns = [d[0] for d in cursor.description]
        finally:
            conn.close()
        return columns, list(reversed(rows))
    return None
