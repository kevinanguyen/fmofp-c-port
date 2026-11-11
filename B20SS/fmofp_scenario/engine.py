"""The scenario engine on the bus (unit 28, ICD v1.23).

scenarioEngine.py sorted a scenario's events by time and, on a thread of its own, fired each one into a live Python
object: a target written into a radar's table, a cell pushed to the display bridge, a contact written into the
radar warning receiver's table, a waypoint or a phase through the mission service, a forced fault on the LRU
monitor. Here every event becomes a bus command through the bus controller's command port
(fmofp_bus.command_port): the world events go to the plant (PLANT_INJECT_CONTACT, PLANT_INJECT_WEATHER), the
threat to the defensive terminal (DEF_CMD INJECT_THREAT), the waypoint and the phase to the mission computer
(MSN_CMD ADD_WAYPOINT, SET_PHASE), the failure to the avionics terminal (AVN_CMD FORCE_FAULT, CLEAR_FAULT,
CLEAR_ALL_FAULTS) and an instructor message is printed. The clock is the bus frame (50 a second), read from the
controller's monitor, so an event at time_s fires at the first frame where time_s * 50 / speed frames have passed
since the start; `speed` runs a ten-minute scenario in a minute for a test. The defaults the Python's injectors
used for a missing parameter are the defaults here.
"""

import time
from dataclasses import dataclass

from fmofp_bus.avionics import key_fields
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (AvionicsCommand, DefensiveCommand, IffIdentity, LruHealth, MissionCommand,
                                 MissionPhase, RwrBand, TargetClass, ThreatType, WaypointType, WeatherCategory)
from fmofp_scenario.scenario import load_scenario

FRAMES_PER_SECOND = 50
FIRST_ANONYMOUS_CONTACT = 200  # radar contacts whose track_id has no digits are numbered from here


def name_words(text):
    """An eight-character waypoint name in the four words of MSN_CMD (the first of each pair in the high byte)."""
    data = str(text).encode("ascii", "replace")[:8].ljust(8, b"\0")
    return [(data[2 * i] << 8) | data[2 * i + 1] for i in range(4)]


def enum_by_name(enum_type, value, default):
    """The enum member named `value` (case-insensitive), `default` for any other value."""
    try:
        return enum_type[str(value).strip().upper()]
    except KeyError:
        return default


@dataclass
class Firing:
    """One event fired: what it became on the bus and what the controller said."""
    event: object
    frame: int
    message: object = None  # the ICD message sent; None for an instructor message or a skipped event
    note: str = ""          # the human line
    ack: object = None      # fmofp_bus.command_port.Acknowledgement, None when nothing was sent

    @property
    def queued(self):
        return self.ack is not None and self.ack.queued

    def as_dict(self):
        """The Python's replay log entry (ts, event_id, event_type, params), with the frame and the outcome."""
        return {"ts": time.time(), "frame": self.frame, "event_id": self.event.event_id,
                "event_type": self.event.event_type, "params": dict(self.event.params), "note": self.note,
                "status": None if self.ack is None else self.ack.status.name,
                "cmd_seq": 0 if self.ack is None else self.ack.cmd_seq}


class Translator:
    """Each scenario event as the bus command the Python's injector amounts to."""

    def __init__(self):
        self.threats = 0    # DEF_CMD INJECT_THREAT's threat_id: the contact is SCEN-n (the Python named it SCEN-<name>)
        self.anonymous = 0  # radar contacts without a number in their track_id

    def translate(self, event):
        """(message, note): the ICD message to send (None for an instructor message or a skipped event) and the
        line to print."""
        p = event.params
        kind = event.event_type
        if kind == "message":
            return None, f"INSTRUCTOR: {p.get('text', p.get('message', ''))}"
        if kind == "waypoint":
            return self.waypoint(p)
        if kind == "phase_change":
            return self.phase(p)
        if kind == "radar_contact":
            return self.radar_contact(p)
        if kind == "weather_cell":
            return self.weather_cell(p)
        if kind == "threat_launch":
            return self.threat(p)
        if kind == "system_failure":
            return self.failure(p)
        return None, f"skipped: unknown event type {kind!r}"

    @staticmethod
    def waypoint(p):
        """_inject_waypoint: add_waypoint(lat, lon, alt_ft, name) with its defaults; a NAV waypoint, flown over."""
        name = str(p.get("name", "WP"))
        lat, lon, alt = float(p.get("lat", 35.0)), float(p.get("lon", -97.0)), float(p.get("alt_ft", 10000))
        words = name_words(name)
        message = m.MsnCmd(command=MissionCommand.ADD_WAYPOINT, waypoint_type=WaypointType.NAV, fly_over=True,
                           latitude=lat, longitude=lon, altitude=alt, name_0=words[0], name_1=words[1],
                           name_2=words[2], name_3=words[3])
        return message, f"MSN_CMD ADD_WAYPOINT {name} {lat:.4f} {lon:.4f} {alt:.0f} ft"

    @staticmethod
    def phase(p):
        """_inject_phase: set_phase(phase), INGRESS by default; a phase the ICD does not name is skipped (the
        Python's set_phase raised and the dispatcher logged the error)."""
        wanted = str(p.get("phase", "INGRESS"))
        phase = enum_by_name(MissionPhase, wanted, None)
        if phase is None:
            return None, f"skipped: unknown mission phase {wanted!r}"
        return m.MsnCmd(command=MissionCommand.SET_PHASE, phase=phase), f"MSN_CMD SET_PHASE {phase.name}"

    def radar_contact(self, p):
        """_inject_radar_contact: a target written into a radar's current_targets, position (x, y, alt_ft),
        velocity (vx, vy, vz), classification, identity, rcs, is_stealth; here an aircraft into the plant's
        traffic, x and y as km east and north of the aircraft, the velocity in m/s. The track_id's digits are the
        contact id (T01 is 1); an id without digits gets a number from 200."""
        track_id = str(p.get("track_id", ""))
        digits = "".join(ch for ch in track_id if ch.isdigit())
        if digits:
            contact_id = int(digits)
        else:
            self.anonymous += 1
            contact_id = FIRST_ANONYMOUS_CONTACT + self.anonymous - 1
        if not 1 <= contact_id <= 255:
            contact_id = contact_id % 255 or 255
        classification = enum_by_name(TargetClass, p.get("classification", "UNKNOWN"), TargetClass.UNKNOWN)
        identity = enum_by_name(IffIdentity, p.get("identity", "UNKNOWN"), IffIdentity.UNKNOWN)
        x, y, alt = float(p.get("x", 50.0)), float(p.get("y", 50.0)), float(p.get("alt_ft", 20000.0))
        message = m.PlantInjectContact(
            contact_id=contact_id, classification=classification, identity=identity,
            is_stealth=bool(p.get("is_stealth", False)),  # bool() of the parsed text, as the Python did
            x_km=x, y_km=y, alt_ft=alt, velocity_east=float(p.get("vx", 0.0)), velocity_north=float(p.get("vy", 0.0)),
            velocity_up=float(p.get("vz", 0.0)), rcs=float(p.get("rcs", 5.0)))
        return message, (f"PLANT_INJECT_CONTACT {track_id or '?'} as id {contact_id}: {x:g} km E {y:g} km N "
                         f"{alt:.0f} ft, {classification.name}/{identity.name}")

    @staticmethod
    def weather_cell(p):
        """_inject_weather: a cell at (x, y) with intensity, reflectivity, size and category, pushed to the display
        bridge; here a storm cell into the plant's sky at that offset."""
        category = enum_by_name(WeatherCategory, p.get("category", "MODERATE"), WeatherCategory.UNKNOWN)
        x, y = float(p.get("x", 0)), float(p.get("y", 0))
        size, intensity, dbz = float(p.get("size", 5.0)), float(p.get("intensity", 0.7)), float(p.get("reflectivity", 45))
        message = m.PlantInjectWeather(category=category, x_km=x, y_km=y, size=size, intensity=intensity,
                                       reflectivity=dbz)
        return message, f"PLANT_INJECT_WEATHER {x:g} km E {y:g} km N, {size:g} km, {dbz:g} dBZ, {category.name}"

    def threat(self, p):
        """_inject_threat: an RWRContact SCEN-<name> with bearing_deg, range_nm, band (X), threat_type (SAM) and
        priority (1), hostile; here DEF_CMD INJECT_THREAT, the contact SCEN-n."""
        self.threats += 1
        name = str(p.get("name", "THR"))
        band = enum_by_name(RwrBand, p.get("band", "X"), RwrBand.UNKNOWN)
        threat_type = enum_by_name(ThreatType, p.get("threat_type", "SAM"), ThreatType.UNK)
        bearing, range_nm, priority = float(p.get("bearing_deg", 0)), float(p.get("range_nm", 30)), int(p.get("priority", 1))
        message = m.DefCmd(command=DefensiveCommand.INJECT_THREAT, threat_id=self.threats, bearing=bearing,
                           range=range_nm, band=band, threat_type=threat_type, priority=priority)
        return message, (f"DEF_CMD INJECT_THREAT SCEN-{self.threats} ({name}) {bearing:g} deg {range_nm:g} nm "
                         f"{band.name} {threat_type.name} priority {priority}")

    @staticmethod
    def failure(p):
        """_inject_failure: force_fault(system, state) on the LRU monitor, FAULT by default; action clear or
        clear_all clears instead. The system key goes on the bus as written (fmofp_bus.avionics.key_fields)."""
        system = str(p.get("system", "unknown"))
        description = str(p.get("description", ""))
        action = str(p.get("action", "set")).strip().lower()
        if action == "clear_all":
            return m.AvnCmd(command=AvionicsCommand.CLEAR_ALL_FAULTS), "AVN_CMD CLEAR_ALL_FAULTS"
        if action == "clear":
            return m.AvnCmd(command=AvionicsCommand.CLEAR_FAULT, **key_fields(system)), f"AVN_CMD CLEAR_FAULT {system}"
        state = enum_by_name(LruHealth, p.get("state", "FAULT"), LruHealth.FAULT)
        message = m.AvnCmd(command=AvionicsCommand.FORCE_FAULT, health=state, **key_fields(system))
        return message, f"AVN_CMD FORCE_FAULT {state.name} {system}: {description}".rstrip(": ")


class ScenarioEngine:
    """Fires a scenario's events by the bus frame through a CommandClient."""

    def __init__(self, client, speed=1.0):
        self.client = client
        self.speed = float(speed) if speed and speed > 0 else 1.0
        self.translator = Translator()
        self.scenario = None
        self.start_frame = None
        self.frame = None      # the last frame stepped
        self.stopped = False
        self.log = []          # Firing, in firing order
        self.on_fire = None    # callable(Firing), if the caller wants each one as it happens

    def load(self, filename):
        """Reads the scenario (fmofp_scenario.scenario.load_scenario) and forgets the previous run."""
        self.scenario = load_scenario(filename)
        self.start_frame = None
        self.frame = None
        self.log = []
        return self.scenario

    @property
    def events(self):
        return self.scenario.events if self.scenario is not None else []

    @property
    def name(self):
        return self.scenario.name if self.scenario is not None else ""

    @property
    def complete(self):
        return bool(self.events) and all(e.fired for e in self.events)

    @property
    def running(self):
        return self.start_frame is not None and not self.stopped and not self.complete

    def start(self, frame):
        """Starts the scenario at bus frame `frame`: every event's time counts from here. False when nothing is
        loaded (the Python warned 'No events loaded')."""
        if not self.events:
            return False
        for event in self.events:
            event.fired = False
        self.translator = Translator()
        self.start_frame = frame
        self.frame = frame
        self.stopped = False
        self.log = []
        return True

    def stop(self):
        self.stopped = True

    def trigger_frames(self, event):
        """How many frames after the start the event is due."""
        return event.trigger_s * FRAMES_PER_SECOND / self.speed

    def step(self, frame):
        """Fires every event due by `frame`, in time order; returns the firings."""
        self.frame = frame
        if not self.running:
            return []
        elapsed = frame - self.start_frame
        fired = []
        for event in self.events:
            if not event.fired and elapsed >= self.trigger_frames(event):
                event.fired = True
                fired.append(self.fire(event, frame))
        return fired

    def fire(self, event, frame):
        message, note = self.translator.translate(event)
        firing = Firing(event, frame, message, note)
        if message is not None:
            firing.ack = self.client.send(message)
        self.log.append(firing)
        if self.on_fire is not None:
            self.on_fire(firing)
        return firing

    def elapsed_s(self):
        """Scenario seconds since the start (bus frames at the speed factor), as get_status's elapsed_s."""
        if self.start_frame is None or self.frame is None:
            return 0.0
        return round((self.frame - self.start_frame) * self.speed / FRAMES_PER_SECOND, 1)

    def status(self):
        """The Python's get_status dictionary, plus the speed and the commands' outcomes."""
        fired = sum(1 for e in self.events if e.fired)
        return {"running": self.running, "scenario_name": self.name, "events_total": len(self.events),
                "events_fired": fired, "elapsed_s": self.elapsed_s(), "speed": self.speed,
                "commands_queued": sum(1 for f in self.log if f.queued),
                "commands_failed": sum(1 for f in self.log if f.message is not None and not f.queued),
                "log": [f.as_dict() for f in self.log]}

    def run(self, view, stall_s=5.0, poll_s=0.002):
        """Starts at the bus's present frame and steps at every new frame until every event fired, stop() is
        called, or the bus stops advancing for stall_s. Returns the firings."""
        frame = view.current_frame()
        if not self.start(frame):
            return []
        self.step(frame)  # the events at T+0 go now
        last_change = time.monotonic()
        while self.running:
            now_frame = view.current_frame()
            if now_frame != frame:
                frame = now_frame
                last_change = time.monotonic()
                self.step(frame)
            elif time.monotonic() - last_change > stall_s:
                self.stop()
                break
            else:
                time.sleep(poll_s)
        return list(self.log)


def describe(firing):
    """One line per firing, in the Python's log format with the outcome added."""
    event = firing.event
    head = f"T+{event.trigger_s:.0f}s  [{event.event_type}]  id={event.event_id}  {firing.note}"
    if firing.message is None:
        return head
    if firing.ack is None:
        return head + "  -> not sent"
    if firing.ack.queued:
        return head + f"  -> queued at frame {firing.ack.frame} (cmd_seq {firing.ack.cmd_seq})"
    return head + f"  -> {firing.ack.status.name}"
