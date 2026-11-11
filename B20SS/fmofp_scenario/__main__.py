"""Run a scenario against the aircraft on the bus.

    py -m fmofp_scenario FMOFP/Interfaces/scenarios/trainingScenario.xml [--port-base 51000] [--speed 1] [--wait 10]

Start the aircraft first (`py -m fmofp_demo`, or the processes by hand); the engine finds the bus controller's
monitor at port_base + 33 for its clock and its command port at port_base + 34 for the commands. Prints a line
per event as it fires and a summary; exits 0 when every event fired and every command was queued, 1 otherwise, 2
when the bus was not there.
"""

import argparse
import sys

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import CommandClient
from fmofp_bus.rt_process import DEFAULT_PORT_BASE
from fmofp_bus.status import Status
from fmofp_scenario.engine import ScenarioEngine, describe


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
            print("scenario: cannot open the monitor or a socket", file=sys.stderr)
            return 2
        view.start()
        if not view.wait_for_frame(0, args.wait):
            print(f"scenario: no bus controller on port {args.port_base + 33} within {args.wait:g} s", file=sys.stderr)
            return 2
        engine.on_fire = lambda firing: print(describe(firing), flush=True)
        engine.run(view, stall_s=args.stall)
        status = engine.status()
        print(f"scenario: '{scenario.name}' {'complete' if engine.complete else 'stopped'}: "
              f"{status['events_fired']}/{status['events_total']} events fired, "
              f"{status['commands_queued']} commands queued, {status['commands_failed']} not acknowledged",
              flush=True)
        return 0 if engine.complete and status["commands_failed"] == 0 else 1
    finally:
        client.close()
        view.close()


if __name__ == "__main__":
    sys.exit(main())
