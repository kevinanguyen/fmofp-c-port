"""The debug CLI's commands.

Utils/debug/userCLI.py was a click REPL on four threads that reached into the Python objects of the running
program: `status` printed each subsystem's getters, `send` and `msg` pushed messages through the old messaging
stack, `test` ran assertion suites against the live program, `scenario` drove the scenario engine. On the bus a
program has no objects to reach into: everything a terminal says is on the monitor port, and everything an
operator can do is a command through the controller's command port. So `status` decodes the latest TERM_STATUS
and status messages the monitor has shown, `send` builds any ICD command message from `field=value` pairs and
queues it, and `scenario` runs fmofp_scenario's engine. The test suites went where the tests are
(fmofp_bus/tests); `test_1553b` is the bus itself now.
"""

import dataclasses
import enum
import threading
import time

from fmofp_bus.bus_view import SYNC_HZ, TERMINAL_NAMES, terminal_address, terminal_name
from fmofp_bus.icd import messages as m
from fmofp_scenario.engine import ScenarioEngine, describe

BY_ID = {info.id: info.cls for info in m.MESSAGES}
BY_CLASS_NAME = {info.cls.__name__: info.cls for info in m.MESSAGES}
ID_BY_CLASS = {info.cls: info.id for info in m.MESSAGES}

HELP = """\
Commands (the bus controller must be running at this port base; status comes from its monitor port, commands go
through its command port):
  frame                      the bus frame count and the seconds on the bus
  terminals                  every terminal seen: its state, health and when it last answered
  status [RT|name]           one terminal's TERM_STATUS and the latest of each message it transmits
  msgs                       the message ids seen on the bus so far
  msg ID [RT]                the latest message with that id, field by field (TERM_STATUS needs the RT)
  send ID [field=value ...]  a command message to its terminal: fields by name, enums by name or number,
                             booleans as 1/0, cmd_seq numbered for you; rt=N for a message of every terminal
  scenario load FILE         read a scenario (a path, or a name in FMOFP/Interfaces/scenarios)
  scenario events            list its events
  scenario start [speed]     fire it from the present frame, at a time factor (10 runs it ten times faster)
  scenario stop              stop it
  scenario status            where it stands
  help                       this text
  quit                       leave"""

TRUE_WORDS = ("1", "true", "on", "yes")
FALSE_WORDS = ("0", "false", "off", "no")


def fmt(value):
    """A field value for a status line: enums by name, booleans as 1/0, floats short."""
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.4g}" if abs(value) < 1e6 else f"{value:.1f}"
    return str(value)


def fields_line(message):
    return " ".join(f"{f.name}={fmt(getattr(message, f.name))}" for f in dataclasses.fields(message))


def message_id(cls):
    return ID_BY_CLASS.get(cls, cls.__name__)


def resolve_message(text):
    """The message class for an ICD id (MSN_CMD) or a class name (MsnCmd); None for neither."""
    return BY_ID.get(text.upper()) or BY_CLASS_NAME.get(text)


def parse_field(cls, name, text):
    """`text` as the type of the dataclass field `name` of `cls` (from its default): an enum by name or number, a
    bool, an int (0x allowed), a float. ValueError with a usable message otherwise."""
    by_name = {f.name: f for f in dataclasses.fields(cls)}
    field = by_name.get(name)
    if field is None:
        raise ValueError(f"{message_id(cls)} has no field {name!r}; its fields: {', '.join(by_name)}")
    default = field.default
    if isinstance(default, enum.Enum):
        kind = type(default)
        try:
            return kind[text.strip().upper()]
        except KeyError:
            pass
        try:
            return kind(int(text, 0))
        except ValueError:
            raise ValueError(f"{name}: {text!r} is not one of {', '.join(e.name for e in kind)}") from None
    if isinstance(default, bool):
        if text.strip().lower() in TRUE_WORDS:
            return True
        if text.strip().lower() in FALSE_WORDS:
            return False
        raise ValueError(f"{name}: {text!r} is not a boolean (1/0, true/false, on/off)")
    if isinstance(default, int):
        try:
            return int(text, 0)
        except ValueError:
            raise ValueError(f"{name}: {text!r} is not an integer") from None
    if isinstance(default, float):
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{name}: {text!r} is not a number") from None
    raise ValueError(f"{name}: cannot set a field of type {type(default).__name__}")


class DebugCli:
    """The commands over a BusView (status) and a CommandClient (commands). `out` takes each output line."""

    PROMPT = "fmofp> "

    def __init__(self, view, client, out=print):
        self.view = view
        self.client = client
        self.out = out
        self.engine = ScenarioEngine(client)
        self.engine.on_fire = lambda firing: self.out(describe(firing))
        self._scenario_thread = None

    def close(self):
        self.engine.stop()
        if self._scenario_thread is not None and self._scenario_thread.is_alive():
            self._scenario_thread.join(timeout=2.0)

    def execute(self, line):
        """One command line. False when the session should end."""
        words = line.split()
        if not words:
            return True
        command, args = words[0].lower(), words[1:]
        if command in ("quit", "exit", "q"):
            return False
        handler = {"help": self.cmd_help, "?": self.cmd_help, "frame": self.cmd_frame, "terminals": self.cmd_terminals,
                   "status": self.cmd_status, "msgs": self.cmd_msgs, "msg": self.cmd_msg, "send": self.cmd_send,
                   "scenario": self.cmd_scenario}.get(command)
        if handler is None:
            self.out(f"unknown command {words[0]!r}; 'help' lists them")
            return True
        try:
            if command == "scenario" and len(args) >= 2 and args[0].lower() == "load":
                # the file name as typed, spaces and all (a Windows path has backslashes shlex would eat)
                args = ["load", line.split(None, 2)[2].strip().strip('"').strip("'")]
            handler(args)
        except ValueError as error:
            self.out(f"error: {error}")
        return True

    # ---- status

    def cmd_help(self, args):
        self.out(HELP)

    def cmd_frame(self, args):
        frame = self.view.current_frame()
        if frame < 0:
            self.out("no bus controller seen yet (no frame on the monitor port)")
        else:
            self.out(f"frame {frame} ({frame / SYNC_HZ:.1f} s on the bus)")

    def cmd_terminals(self, args):
        snap = self.view.snapshot()
        now = time.monotonic()
        rts = sorted(set(snap["term_status"]) | set(snap["last_poll"]))
        if not rts:
            self.out("no terminal seen yet (is the bus controller running at this port base?)")
            return
        self.out(f"frame {snap['frame']}: {len(rts)} terminals")
        for rt in rts:
            term = snap["term_status"].get(rt)
            answered = snap["last_answer"].get(rt)
            age = f"answered {now - answered:.1f} s ago" if answered is not None else "never answered"
            if term is None:
                self.out(f"  RT {rt:2d} {terminal_name(rt):<14} (no TERM_STATUS yet)      {age}")
            else:
                self.out(f"  RT {rt:2d} {terminal_name(rt):<14} {term.state.name:<12} healthy={int(term.healthy)} "
                         f"faults={term.fault_count} icd={term.icd_major}.{term.icd_minor} "
                         f"last_cmd_seq={term.last_cmd_seq} {age}")

    def cmd_status(self, args):
        if not args:
            return self.cmd_terminals(args)
        rt = terminal_address(args[0])
        if rt is None:
            raise ValueError(f"no terminal {args[0]!r}: give a number, or one of "
                             f"{', '.join(sorted(TERMINAL_NAMES.values()))}")
        snap = self.view.snapshot()
        term = snap["term_status"].get(rt)
        if term is None:
            seen = "it answered a poll" if rt in snap["last_answer"] else "it has not answered a poll"
            self.out(f"RT {rt} ({terminal_name(rt)}): no TERM_STATUS seen; {seen}")
        else:
            self.out(f"RT {rt} ({terminal_name(rt)}) TERM_STATUS: {fields_line(term)}")
        shown = 0
        for key, message in snap["latest"].items():
            if isinstance(key, tuple) or key.RT != rt:
                continue
            self.out(f"  {message_id(key)}: {fields_line(message)}")
            shown += 1
        if shown == 0:
            self.out("  (no message of its own seen yet)")
        return None

    def cmd_msgs(self, args):
        snap = self.view.snapshot()
        ids = sorted(message_id(key) for key in snap["latest"] if not isinstance(key, tuple))
        terms = sorted(snap["term_status"])
        if not ids and not terms:
            self.out("no message seen yet")
            return
        if terms:
            self.out("TERM_STATUS from RT " + ", ".join(str(rt) for rt in terms))
        for message_name in ids:
            self.out(message_name)

    def cmd_msg(self, args):
        if not args:
            raise ValueError("msg ID [RT]")
        cls = resolve_message(args[0])
        if cls is None:
            raise ValueError(f"unknown message {args[0]!r} (the ids are in icd/ICD_TABLES.md; 'msgs' lists those seen)")
        snap = self.view.snapshot()
        if cls is m.TermStatus:
            if len(args) < 2:
                raise ValueError("msg TERM_STATUS RT: every terminal has one")
            rt = terminal_address(args[1])
            message = snap["term_status"].get(rt)
            label = f"TERM_STATUS of RT {rt}"
        else:
            message = snap["latest"].get(cls)
            label = message_id(cls)
        if message is None:
            self.out(f"no {label} seen yet" + ("" if cls.DIRECTION == "T" else
                                              " (a receive message: the monitor shows what terminals transmit)"))
            return
        self.out(f"{label}:")
        for field in dataclasses.fields(message):
            self.out(f"  {field.name} = {fmt(getattr(message, field.name))}")

    # ---- commands

    def cmd_send(self, args):
        if not args:
            raise ValueError("send ID [field=value ...] [rt=N]")
        cls = resolve_message(args[0])
        if cls is None:
            raise ValueError(f"unknown message {args[0]!r} (the ids are in icd/ICD_TABLES.md)")
        if cls.DIRECTION != "R":
            raise ValueError(f"{message_id(cls)} is a transmit message (its terminal publishes it); only receive "
                             f"messages can be sent")
        rt = cls.RT
        values = {}
        for arg in args[1:]:
            name, sep, text = arg.partition("=")
            if not sep:
                raise ValueError(f"{arg!r}: fields are given as name=value")
            if name == "rt":
                rt = terminal_address(text)
                if rt is None:
                    raise ValueError(f"rt={text!r} is no terminal")
                continue
            values[name] = parse_field(cls, name, text)
        if rt == m.EVERY_TERMINAL:
            raise ValueError(f"{message_id(cls)} is defined for every terminal: say which with rt=N")
        message = cls(**values)
        ack = self.client.send(message, rt=rt)
        line = f"{message_id(cls)} -> RT {rt} SA {cls.SUBADDRESS}: {ack.status.name}"
        if ack.queued:
            line += f", queued at frame {ack.frame}"
            if ack.cmd_seq:
                line += f" (cmd_seq {ack.cmd_seq})"
        self.out(line)

    # ---- the scenario engine

    def cmd_scenario(self, args):
        what = args[0].lower() if args else "status"
        engine = self.engine
        if what == "load":
            if len(args) < 2:
                raise ValueError("scenario load FILE")
            if engine.running:
                raise ValueError("a scenario is running: 'scenario stop' first")
            try:
                scenario = engine.load(args[1])
            except (OSError, SyntaxError) as error:
                raise ValueError(f"cannot load {args[1]}: {error}") from None
            last = scenario.events[-1].trigger_s if scenario.events else 0.0
            self.out(f"loaded '{scenario.name}': {len(scenario.events)} events over {last:g} s")
        elif what == "events":
            if engine.scenario is None:
                raise ValueError("no scenario loaded: 'scenario load FILE'")
            for event in engine.events:
                mark = "fired " if event.fired else "      "
                self.out(f"  {mark}T+{event.trigger_s:g}s  [{event.event_type}]  {event.event_id}  {event.params}")
        elif what == "start":
            if engine.scenario is None:
                raise ValueError("no scenario loaded: 'scenario load FILE'")
            if engine.running:
                raise ValueError("already running")
            if len(args) >= 2:
                try:
                    engine.speed = float(args[1])
                except ValueError:
                    raise ValueError(f"speed {args[1]!r} is not a number") from None
                if engine.speed <= 0:
                    raise ValueError("the speed must be positive")
            frame = self.view.current_frame()
            if frame < 0:
                raise ValueError("no bus controller seen yet: nothing to time the events against")
            self.out(f"started '{engine.name}' at frame {frame}, speed x{engine.speed:g}")
            self._scenario_thread = threading.Thread(target=engine.run, args=(self.view,), daemon=True,
                                                     name="ScenarioEngine")
            self._scenario_thread.start()
        elif what == "stop":
            was_running = engine.running
            engine.stop()
            if self._scenario_thread is not None:
                self._scenario_thread.join(timeout=2.0)
            self.out("stopped" if was_running else "nothing was running")
        elif what == "status":
            if engine.scenario is None:
                self.out("no scenario loaded")
                return
            status = engine.status()
            state = "running" if status["running"] else ("complete" if engine.complete else
                                                         ("not started" if engine.start_frame is None else "stopped"))
            self.out(f"'{status['scenario_name']}': {state}, {status['events_fired']}/{status['events_total']} events "
                     f"fired, T+{status['elapsed_s']:g} s at speed x{status['speed']:g}, "
                     f"{status['commands_queued']} commands queued, {status['commands_failed']} not acknowledged")
        else:
            raise ValueError("scenario load FILE | events | start [speed] | stop | status")
