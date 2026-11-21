"""The debug CLI.

    py -m fmofp_cli [--port-base 51000] [--wait 5] [--fixed-monitor] [-c COMMAND ...]

Without -c, a prompt; with -c, each command in order and then exit (the scenario commands need the REPL, or
`py -m fmofp_scenario`, to see the scenario through). Start the aircraft first (`py -m fmofp_demo`): the prompt
asks the bus controller for its own copy of the monitor stream, so it runs beside the demo's dashboard, a
scenario and another prompt. --fixed-monitor listens on the one fixed monitor port instead, for a controller
started with --no-command-port (status only, and only while nobody else holds that port).
"""

import argparse
import sys

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, DEFAULT_PORT_BASE, MONITOR_PORT_OFFSET
from fmofp_bus.status import Status
from fmofp_cli.cli import HELP, DebugCli


def no_bus(view, args):
    """Why no frame has come yet."""
    if args.fixed_monitor:
        return f"no bus controller seen on the monitor port {args.port_base + MONITOR_PORT_OFFSET} yet"
    if view.monitor.granted == Status.NOT_READY:
        return "the bus controller already serves as many monitor listeners as it can: close another client"
    if view.monitor.granted is not None and view.monitor.granted != Status.OK:
        return (f"the bus controller refused the monitor request ({view.monitor.granted.name}): is it built for "
                f"ICD v1.24 or later?")
    return (f"no bus controller answers on its command port {args.port_base + COMMAND_PORT_OFFSET} yet (not "
            f"started, another port base, or started with --no-command-port: try --fixed-monitor)")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="py -m fmofp_cli", description=__doc__.split("\n\n")[0])
    parser.add_argument("--port-base", type=int, default=DEFAULT_PORT_BASE)
    parser.add_argument("--wait", type=float, default=5.0, help="seconds to wait for the bus controller's first frame")
    parser.add_argument("--fixed-monitor", action="store_true",
                        help="listen on the fixed monitor port (port base + 33) instead of asking the controller "
                             "for a copy of the stream")
    parser.add_argument("-c", "--command", action="append", default=[], help="a command to run (repeatable), then exit")
    parser.add_argument("--recorder-dir", default=None,
                        help="where `tables` and `table` read the recorder's databases (default logs/recorder)")
    args = parser.parse_args(argv)

    view = BusView(args.port_base, subscribe=not args.fixed_monitor)
    client = CommandClient(args.port_base)
    if view.open() != Status.OK:
        if args.fixed_monitor:
            print(f"cli: cannot open the monitor port {args.port_base + MONITOR_PORT_OFFSET}: another listener "
                  f"holds it (the demo's dashboard does while the demo runs); run without --fixed-monitor",
                  file=sys.stderr)
        else:
            print("cli: cannot open a socket", file=sys.stderr)
        return 2
    if client.open() != Status.OK:
        print("cli: cannot open a socket", file=sys.stderr)
        view.close()
        return 2
    view.start()
    cli = DebugCli(view, client, recorder_dir=args.recorder_dir)
    try:
        if not view.wait_for_frame(0, args.wait):
            print(f"cli: {no_bus(view, args)}; status stays empty until one runs")
        if args.command:
            for command in args.command:
                print(DebugCli.PROMPT + command)
                if not cli.execute(command):
                    break
            return 0
        print(f"FMOFP debug CLI on port base {args.port_base}. 'help' lists the commands, 'quit' leaves.")
        while True:
            try:
                line = input(DebugCli.PROMPT)
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not cli.execute(line):
                break
        return 0
    finally:
        cli.close()
        client.close()
        view.close()


if __name__ == "__main__":
    sys.exit(main())
