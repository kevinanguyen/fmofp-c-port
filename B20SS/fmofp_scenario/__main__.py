"""Run a scenario against the aircraft on the bus.

    py -m fmofp_scenario FMOFP/Interfaces/scenarios/trainingScenario.xml [--port-base 51000] [--speed 1] [--wait 10]

Start the aircraft first (`py -m fmofp_demo`, or the processes by hand). The engine reaches the bus controller
through its command port at port_base + 34 alone: its commands go there, and so does its request for a copy of
the monitor stream, which gives it its clock (ICD README section 7). It runs beside the demo's dashboard, the
debug prompt and another engine. Prints a line per event as it fires and a summary; exits 0 when every event
fired and every command was queued, 1 otherwise, 2 when the bus was not there.
"""

import argparse
import sys

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, DEFAULT_PORT_BASE
from fmofp_bus.status import Status
from fmofp_scenario.engine import ScenarioEngine, describe


def no_bus(view, port_base, wait_s):
    """Why no frame came: the controller serves as many listeners as it can, or it is not there (or has no
    command port: one built before ICD v1.24, or started with --no-command-port)."""
    if view.monitor.granted == Status.NOT_READY:
        return "the bus controller already serves as many monitor listeners as it can: close another client"
    if view.monitor.granted is not None and view.monitor.granted != Status.OK:
        return (f"the bus controller refused the monitor request ({view.monitor.granted.name}): "
                f"is it built for ICD v1.24 or later?")
    return (f"no bus controller answered on its command port {port_base + COMMAND_PORT_OFFSET} within "
            f"{wait_s:g} s (not started, another port base, or started with --no-command-port)")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="py -m fmofp_scenario", description=__doc__.split("\n\n")[0])
    parser.add_argument("file", help="the scenario XML (a path, or a name in FMOFP/Interfaces/scenarios)")
    parser.add_argument("--port-base", type=int, default=DEFAULT_PORT_BASE)
    parser.add_argument("--speed", type=float, default=1.0, help="time factor: 10 runs a 500 s scenario in 50 s")
    parser.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the bus controller")
    parser.add_argument("--stall", type=float, default=5.0, help="give up after this many seconds without a frame")
    args = parser.parse_args(argv)

    view = BusView(args.port_base)
    client = CommandClient(args.port_base)
    try:
        engine = ScenarioEngine(client, speed=args.speed)
        try:
            scenario = engine.load(args.file)
        except (OSError, SyntaxError) as error:  # xml.etree's ParseError is a SyntaxError
            print(f"scenario: cannot load {args.file}: {error}", file=sys.stderr)
            return 2
        print(f"scenario: '{scenario.name}', {len(scenario.events)} events, speed x{args.speed:g}, "
              f"port base {args.port_base}", flush=True)
        if view.open() != Status.OK or client.open() != Status.OK:
            print("scenario: cannot open a socket", file=sys.stderr)
            return 2
        view.start()
        if not view.wait_for_frame(0, args.wait):
            print(f"scenario: {no_bus(view, args.port_base, args.wait)}", file=sys.stderr)
            return 2
        engine.on_fire = lambda firing: print(describe(firing), flush=True)
        engine.run(view, stall_s=args.stall)
        status = engine.status()
        outcome = "complete" if engine.complete else "stopped" + (f" ({engine.stop_reason})" if engine.stop_reason
                                                                   else "")
        print(f"scenario: '{scenario.name}' {outcome}: "
              f"{status['events_fired']}/{status['events_total']} events fired, "
              f"{status['commands_queued']} commands queued, {status['commands_failed']} not acknowledged",
              flush=True)
        return 0 if engine.complete and status["commands_failed"] == 0 else 1
    finally:
        client.close()
        view.close()


if __name__ == "__main__":
    sys.exit(main())
