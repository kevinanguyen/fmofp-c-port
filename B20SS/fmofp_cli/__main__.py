"""The debug CLI.

    py -m fmofp_cli [--port-base 51000] [--wait 5] [-c COMMAND ...]

Without -c, a prompt; with -c, each command in order and then exit (the scenario commands need the REPL, or
`py -m fmofp_scenario`, to see the scenario through). Start the aircraft first (`py -m fmofp_demo`).
"""

import argparse
import sys

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.status import Status
from fmofp_cli.cli import HELP, DebugCli


def main(argv=None):
    parser = argparse.ArgumentParser(prog="py -m fmofp_cli", description=__doc__.split("\n\n")[0])
    parser.add_argument("--port-base", type=int, default=DEFAULT_PORT_BASE)
    parser.add_argument("--wait", type=float, default=5.0, help="seconds to wait for the bus controller's first frame")
    parser.add_argument("-c", "--command", action="append", default=[], help="a command to run (repeatable), then exit")
    args = parser.parse_args(argv)

    view = BusView(args.port_base)
    client = CommandClient(args.port_base)
    if view.open() != Status.OK:
        print(f"cli: cannot open the monitor port {args.port_base + 33} (another listener on it?)", file=sys.stderr)
        return 2
    if client.open() != Status.OK:
        print("cli: cannot open a socket", file=sys.stderr)
        view.close()
        return 2
    view.start()
    cli = DebugCli(view, client)
    try:
        if not view.wait_for_frame(0, args.wait):
            print(f"cli: no bus controller on port base {args.port_base} yet; status stays empty until one runs")
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
