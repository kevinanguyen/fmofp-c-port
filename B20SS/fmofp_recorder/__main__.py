"""py -m fmofp_recorder: record the Python services' tables from the bus until Ctrl-C (or --seconds)."""

import argparse
import sys
import time

from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.status import Status
from fmofp_recorder.recorder import DEFAULT_OUT, Recorder
from fmofp_recorder.view import RecordingView

REPORT_S = 10.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-base", type=int, default=DEFAULT_PORT_BASE)
    parser.add_argument("--out", default=DEFAULT_OUT, help="the folder for the database files (default logs/recorder)")
    parser.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until Ctrl-C)")
    parser.add_argument("--fixed-monitor", action="store_true",
                        help="listen on the fixed monitor port (a controller without a command port)")
    args = parser.parse_args(argv)

    view = RecordingView(args.port_base, subscribe=not args.fixed_monitor)
    if view.open() != Status.OK:
        print(f"recorder: cannot open the monitor (port base {args.port_base})", file=sys.stderr)
        return 2
    recorder = Recorder(view, args.out)
    recorder.open()
    view.start()
    print(f"recorder: writing {len(recorder.rows_written)} tables to {args.out}")
    started = time.monotonic()
    next_report = started + REPORT_S
    try:
        while args.seconds <= 0 or time.monotonic() - started < args.seconds:
            recorder.step(view.current_frame())
            time.sleep(0.004)
            if time.monotonic() >= next_report:
                next_report += REPORT_S
                total = sum(recorder.rows_written.values())
                print(f"recorder: frame {view.current_frame()}, {total} rows")
    except KeyboardInterrupt:
        pass
    finally:
        view.close()
        recorder.close()
    print("recorder: " + ", ".join(f"{name} {n}" for name, n in recorder.rows_written.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
