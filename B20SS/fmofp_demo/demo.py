"""One command that runs the whole aircraft and shows what crosses the bus.

    py -m fmofp_demo [--seconds S] [--port-base N] [--build DIR] [--headless] [--no-displays]
                     [--no-events] [--hold name=value,...] [--seed N] [--log-dir DIR] [--settle S]

It starts, in this order: the plant (the simulated aircraft with its weather,
terrain, engines and RF environment, RT 27), the ported partitions (flight
control RT 5, navigation RT 7, flight management RT 12, the radar computer RT 9,
engine management RT 3, the mission computer RT 6, communications RT 2, defensive systems RT 22, sensor management RT 10,
power management RT 8, the flight surfaces RT 21, environmental control RT 4, hydraulics RT 19, the airframe
RT 20, flight data monitoring RT 23, avionics RT 1), the
six display programs (the radar display RT 15, the PFD
RT 11, the MFD RT 13, the EICAS RT 14, the TSD RT 16 and the SMS RT 17, each in its own window), and
finally the bus
controller, which drives the bus in real time. Every program writes its own
log under logs/demo/. The console shows one line a second with what is
crossing the bus, read from the controller's monitor port: altitude, airspeed
and heading from the FMS flight data, the ground collision avoidance state,
the engines' N1 and the fuel, the radars' modes, the terrain clearance and the
targeting tracks, the navigation fix, the mission's phase and route progress, the
radio and satcom links, the countermeasures and the radar warning receiver, the sensors' health, the
electrical system, the control surfaces, the hydraulics, the cabin, the landing gear and the flight data
recorder, the avionics health (the line replaceable units and the built-in tests), and which terminals are
answering.

Unless --no-events is given, a short scripted flight runs: the radars are
switched on (the targeting and AEWC radars search, the SAR images the strip
beside the track and then spotlights the lake, the targeting radar later
locks on a track), the thrust
lever moves, the autothrottle holds 500 kt, the flight
mode changes, one engine is throttled back, fuel is transferred; a route is loaded
and flown waypoint by waypoint, a target is designated, engaged and assessed, an
enemy unit appears on the TSD, the radio is tuned and a satellite acquired, a SAM paints the radar
warning receiver (two flares go out by themselves, and again every 3 s while it lasts), the jammer
goes active and chaff is dispensed, the LIDAR is switched off and on again, the generator is switched off
and back on (the EICAS shows GEN 1 and GEN 2 FAIL while the main battery discharges), the flaps and the
speedbrake go out and come back in, the backup hydraulic system is switched in, the oxygen generation rate is
raised, the landing gear goes down and up, a recorder card is ejected, the emergency power comes on, a scenario
failure is forced on the flight control computer and cleared, and the crew runs the built-in tests. Each
event is
announced as it happens. The radar display window's own buttons keep working
throughout: it is the radars' control panel.

Stop with Ctrl-C, or let --seconds run out. Closing a display window stops
only that display.
"""

import argparse
import os
import subprocess
import sys
import time
from collections import namedtuple

from fmofp_bus.avionics import key_fields
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (Affiliation, AvionicsCommand, LruHealth, CommsCommand, DefensiveCommand, EcmMode, MissionCommand, MissionPhase,
                                 PowerCommand, RadioMode, SensorCommand, SensorId, SurfaceCommand, EcsCommand,
                                 FdmCommand, GearPosition, HydraulicCommand,
                                 RwrBand, TargetKind, ThreatType, UnitKind, WaypointType, Weapon, AewcMode, EngineCommand, EngineSelect, FmsFlightMode, FuelTank, LockStatus, SarMode,
                                 Ssm,
                                 TargetingMode, TerminalState, TfrMode, TrackFilter, WeatherMode)
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status

SYNC_HZ = 50
SYNC_MODE_CODE = 17  # SYNCHRONIZE_WITH_DATA, broadcast by the controller once per minor frame
MSYS2_BIN = r"C:\msys64\ucrt64\bin"  # the MinGW runtime the Windows binaries need on PATH
B20SS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANSWER_WINDOW_S = 2.5  # a terminal is "answering" if it answered a poll this recently (1 Hz polls included)

PLANT_RT = m.PlantSensors.RT
# (executable name, RT) of each ported partition.
PARTITIONS = (("fcs", m.FcsStatus.RT), ("nav", m.NavSolution.RT), ("fms", m.FmsStatus.RT),
              ("radar", m.RdrWxStatus.RT), ("engine", m.EngStatus.RT), ("mission", m.MsnStatus.RT),
              ("comms", m.ComStatus.RT), ("defensive", m.DefStatus.RT), ("sensor", m.SnsStatus.RT),
              ("power", m.PwrStatus.RT), ("surfaces", m.FsfStatus.RT), ("ecs", m.EcsStatus.RT),
              ("hydraulics", m.HydStatus.RT), ("airframe", m.AfrStatus.RT), ("fdm", m.FdmStatus.RT),
              ("avionics", m.AvnStatus.RT))
# (fmofp_display argument, RT) of each display program.
DISPLAYS = (("radar", m.DspRadarStatus.RT), ("pfd", m.DspPfdStatus.RT), ("mfd", m.DspMfdStatus.RT),
            ("eicas", m.DspEicasStatus.RT), ("tsd", m.DspTsdStatus.RT), ("sms", m.DspSmsStatus.RT))
NAMES = {PLANT_RT: "plant", m.FcsStatus.RT: "FCS", m.NavSolution.RT: "nav", m.FmsStatus.RT: "FMS",
         m.RdrWxStatus.RT: "radar", m.EngStatus.RT: "engine", m.DspRadarStatus.RT: "radar display",
         m.DspPfdStatus.RT: "PFD", m.DspMfdStatus.RT: "MFD", m.DspEicasStatus.RT: "EICAS",
         m.DspTsdStatus.RT: "TSD", m.DspSmsStatus.RT: "SMS", m.MsnStatus.RT: "mission",
         m.ComStatus.RT: "comms", m.DefStatus.RT: "defensive", m.SnsStatus.RT: "sensors", m.PwrStatus.RT: "power",
         m.FsfStatus.RT: "surfaces", m.EcsStatus.RT: "ECS", m.HydStatus.RT: "hydraulics", m.AfrStatus.RT: "airframe",
         m.FdmStatus.RT: "FDM", m.AvnStatus.RT: "avionics"}

Event = namedtuple("Event", "seconds what message")


def name_words(text):
    """An eight-character waypoint name in the four words of MSN_CMD (the first of each pair in the high byte)."""
    data = text.encode("ascii", "replace")[:8].ljust(8, b"\0")
    return [(data[2 * i] << 8) | data[2 * i + 1] for i in range(4)]


def waypoint(seq, name, lat, lon, alt_ft, kind=WaypointType.NAV):
    words = name_words(name)
    return m.MsnCmd(cmd_seq=seq, command=MissionCommand.ADD_WAYPOINT, waypoint_type=kind, fly_over=True,
                    latitude=lat, longitude=lon, altitude=alt_ft, name_0=words[0], name_1=words[1], name_2=words[2],
                    name_3=words[3])


def default_events():
    """The scripted flight. The cmd_seq values start at 201 so they never collide with the radar display
    window's own numbering, which starts at 1 (a command with the same cmd_seq as the last one is ignored)."""
    return [
        # The route runs up the northbound track the plant flies (home 0 N 0 E, 450 kt, heading 0): the
        # crossroad bridge 5 km out is a designated target, the initial point is at 8 km, the turn at 16 km,
        # the egress at 30 km; each is reached within 0.5 nm as the aircraft passes.
        Event(1.0, "mission: route loaded (IP at 8 km, TURN at 16 km, EGRESS at 30 km up the track)",
              waypoint(201, "IP", 0.0719, 0.0, 10000.0, WaypointType.IP)),
        Event(1.2, "mission: waypoint TURN", waypoint(202, "TURN", 0.1438, 0.0, 10000.0)),
        Event(1.4, "mission: waypoint EGRESS", waypoint(203, "EGRESS", 0.2697, 0.0, 10000.0, WaypointType.EGR)),
        Event(1.6, "mission: phase INGRESS",
              m.MsnCmd(cmd_seq=204, command=MissionCommand.SET_PHASE, phase=MissionPhase.INGRESS)),
        Event(2.0, "weather radar on: SURVEILLANCE at 200 km",
              m.RdrWxModeCmd(cmd_seq=201, requested_state=TerminalState.NORMAL,
                             requested_mode=WeatherMode.SURVEILLANCE, range_km=200.0, tilt=0.0)),
        Event(3.0, "terrain-following radar on, set clearance 1000 ft",
              m.RdrTfrModeCmd(cmd_seq=201, requested_state=TerminalState.NORMAL,
                              requested_mode=TfrMode.TERRAIN_FOLLOWING, set_clearance=1000.0)),
        Event(6.0, "targeting radar on: TARGET_SEARCH (the plant flies twelve aircraft around us)",
              m.RdrTgtModeCmd(cmd_seq=201, requested_state=TerminalState.NORMAL,
                              requested_mode=TargetingMode.TARGET_SEARCH, track_filter=TrackFilter.ALL)),
        Event(7.0, "comms: radio to 243.000 MHz (the MFD COMMS page)",
              m.ComCmd(cmd_seq=201, command=CommsCommand.SET_RADIO_FREQUENCY, frequency=243.0)),
        Event(8.0, "AEWC radar on: AEWC_SEARCH (the far aircraft, out to 400 km)",
              m.RdrAewcModeCmd(cmd_seq=201, requested_state=TerminalState.NORMAL,
                               requested_mode=AewcMode.AEWC_SEARCH, azimuth_start=0.0, azimuth_end=90.0,
                               elevation=0.0)),
        Event(9.0, "comms: acquire a satellite (connected once one comes into view: a 1 % chance a second)",
              m.ComCmd(cmd_seq=202, command=CommsCommand.ACQUIRE_SATELLITE)),
        Event(10.0, "FMS thrust lever to 80 %", m.FmsControlCmd(cmd_seq=201, thrust_present=True, thrust=0.8)),
        Event(12.0, "SAR on: STRIPMAP at 1 m (the strip 2 km to the right: the road beside the track, then the town)",
              m.RdrSarModeCmd(cmd_seq=201, requested_state=TerminalState.NORMAL, requested_mode=SarMode.STRIPMAP,
                              resolution=1.0)),
        Event(14.0, "mission: designate the bridge at the crossroad as target 1 (a TGT waypoint goes in before IP)",
              m.MsnCmd(cmd_seq=205, command=MissionCommand.DESIGNATE_TARGET, target_kind=TargetKind.BRIDGE,
                       priority=1, latitude=0.0450, longitude=0.0, altitude=0.0)),
        Event(16.0, "mission: an enemy SAM site 1.3 km east of the track (the TSD shows a hostile contact)",
              m.MsnCmd(cmd_seq=206, command=MissionCommand.ADD_UNIT, unit_kind=UnitKind.SAM_SITE,
                       affiliation=Affiliation.ENEMY, threat_level=4, latitude=0.13, longitude=0.012, altitude=0.0)),
        Event(17.0, "mission: a friendly tanker to the north-west",
              m.MsnCmd(cmd_seq=207, command=MissionCommand.ADD_UNIT, unit_kind=UnitKind.TANKER,
                       affiliation=Affiliation.FRIENDLY, latitude=0.25, longitude=-0.05, altitude=25000.0)),
        Event(18.0, "defensive: an SA-10 paints the radar warning receiver at 030/25 nm (priority 1: two flares go out by "
              "themselves within half a second, and again every 3 s until it fades after 10 s; the EICAS warns)",
              m.DefCmd(cmd_seq=201, command=DefensiveCommand.INJECT_THREAT, threat_id=1, bearing=30.0, range=25.0,
                       band=RwrBand.X, threat_type=ThreatType.SAM, priority=1)),
        Event(19.0, "defensive: ECM ACTIVE (the jammer is on: the EICAS ECM cell goes cyan)",
              m.DefCmd(cmd_seq=202, command=DefensiveCommand.SET_ECM_MODE, ecm_mode=EcmMode.ACTIVE)),
        Event(20.0, "autothrottle engaged: hold 500 kt",
              m.EngCmd(cmd_seq=201, command=EngineCommand.AUTOTHROTTLE_ENGAGE, target_airspeed=500.0)),
        Event(24.0, "avionics: a scenario failure on the flight control computer (FCC-1 forced to FAULT: AVN reads FAULT)",
              m.AvnCmd(cmd_seq=201, command=AvionicsCommand.FORCE_FAULT, health=LruHealth.FAULT,
                       **key_fields("flight_control_computer"))),
        Event(30.0, "flight mode COMBAT (the SMS's master arm goes ARMED)",
              m.FmsFlightModeCmd(cmd_seq=201, flight_mode=FmsFlightMode.COMBAT)),
        Event(34.0, "mission: acquire target 1, then engage it with a JDAM",
              m.MsnCmd(cmd_seq=208, command=MissionCommand.ACQUIRE_TARGET, id=1)),
        Event(35.0, "mission: engage target 1 (JDAM)",
              m.MsnCmd(cmd_seq=209, command=MissionCommand.ENGAGE_TARGET, id=1, weapon=Weapon.JDAM)),
        Event(36.0, "mission: phase OBJECTIVE", m.MsnCmd(cmd_seq=210, command=MissionCommand.ADVANCE_PHASE)),
        Event(38.0, "autothrottle disengaged", m.EngCmd(cmd_seq=202, command=EngineCommand.AUTOTHROTTLE_DISENGAGE)),
        Event(40.0, "engine 2 alone to 40 %: asymmetric thrust",
              m.EngCmd(cmd_seq=203, command=EngineCommand.SET_THRUST, engine=EngineSelect.ENGINE_2, thrust=40.0)),
        Event(42.0, "flight surfaces: flaps to 15 deg (they travel at 5 deg/s: three seconds on the FSF line)",
              m.FsfCmd(cmd_seq=201, command=SurfaceCommand.SET_FLAPS, value=15.0)),
        Event(42.0, "avionics: the failure is cleared (FCC-1 is UNKNOWN until the next bus report, then NOMINAL)",
              m.AvnCmd(cmd_seq=202, command=AvionicsCommand.CLEAR_FAULT, **key_fields("flight_control_computer"))),
        Event(45.0, "defensive: four chaff cartridges dispensed (the DEF line counts down)",
              m.DefCmd(cmd_seq=203, command=DefensiveCommand.DISPENSE_CHAFF, count=4)),
        Event(47.0, "flight surfaces: speedbrake 50 % (30 deg, out within a second)",
              m.FsfCmd(cmd_seq=202, command=SurfaceCommand.SET_SPEEDBRAKE, value=50.0)),
        Event(48.0, "sensors: LIDAR off (the EICAS SENSORS health goes DEGRADED; its points leave the fusion)",
              m.SnsCmd(cmd_seq=201, command=SensorCommand.DEACTIVATE, sensor=SensorId.LIDAR)),
        Event(50.0, "1000 kg from the Center tank to Main Left (it takes what fits)",
              m.EngCmd(cmd_seq=204, command=EngineCommand.FUEL_TRANSFER, source=FuelTank.CENTER,
                       destination=FuelTank.MAIN_LEFT, amount=1000.0)),
        Event(52.0, "power: generator off (the EICAS shows GEN 1 and GEN 2 FAIL; the main battery carries the load, see PWR)",
              m.PwrCmd(cmd_seq=201, command=PowerCommand.SET_GENERATOR_OUTPUT, value=0.0)),
        Event(55.0, "targeting radar to TARGET_TRACK, lock on track 1",
              m.RdrTgtModeCmd(cmd_seq=202, requested_state=TerminalState.NORMAL,
                              requested_mode=TargetingMode.TARGET_TRACK, track_filter=TrackFilter.ALL,
                              lock_track_id=1)),
        Event(56.0, "hydraulics: backup system switched in by hand (HYD BACKUP on the systems line)",
              m.HydCmd(cmd_seq=201, command=HydraulicCommand.ACTIVATE_BACKUP)),
        Event(57.0, "avionics: an initiated built-in test (fifteen probes: ibit 15/15 on the AVN line)",
              m.AvnCmd(cmd_seq=203, command=AvionicsCommand.RUN_INITIATED_BIT)),
        Event(58.0, "sensors: LIDAR back on (NOMINAL)",
              m.SnsCmd(cmd_seq=202, command=SensorCommand.ACTIVATE, sensor=SensorId.LIDAR)),
        Event(60.0, "weather radar to MAPPING",
              m.RdrWxModeCmd(cmd_seq=202, requested_state=TerminalState.NORMAL,
                             requested_mode=WeatherMode.MAPPING, range_km=200.0, tilt=0.0)),
        Event(61.0, "power: generator back to automatic (the surplus recharges the main battery)",
              m.PwrCmd(cmd_seq=202, command=PowerCommand.GENERATOR_AUTO)),
        Event(62.0, "ECS: oxygen generation rate to 1.5 L/min (reported; the level climbs 0.1 a pass regardless)",
              m.EcsCmd(cmd_seq=201, command=EcsCommand.SET_OXYGEN_RATE, value=1.5)),
        Event(65.0, "SAR to SPOTLIGHT at 0.3 m: the lake abeam, a ship under way (a picture every 3 s)",
              m.RdrSarModeCmd(cmd_seq=202, requested_state=TerminalState.NORMAL, requested_mode=SarMode.SPOTLIGHT,
                              resolution=0.3)),
        Event(68.0, "flight surfaces: flaps up",
              m.FsfCmd(cmd_seq=203, command=SurfaceCommand.SET_FLAPS, value=0.0)),
        Event(69.0, "flight surfaces: speedbrake in",
              m.FsfCmd(cmd_seq=204, command=SurfaceCommand.SET_SPEEDBRAKE, value=0.0)),
        Event(70.0, "mission: target 1 assessed destroyed (it leaves the targets tab); phase EGRESS",
              m.MsnCmd(cmd_seq=211, command=MissionCommand.ASSESS_DAMAGE, id=1, destroyed=True)),
        Event(71.0, "mission: phase EGRESS", m.MsnCmd(cmd_seq=212, command=MissionCommand.ADVANCE_PHASE)),
        Event(72.0, "FMS: landing gear down (the airframe terminal's gear goes DEPLOYED)",
              m.FmsControlCmd(cmd_seq=202, gear_present=True, gear=GearPosition.DOWN)),
        Event(75.0, "both engines back to 70 %",
              m.EngCmd(cmd_seq=205, command=EngineCommand.SET_THRUST, engine=EngineSelect.ALL, thrust=70.0)),
        Event(78.0, "FMS: landing gear up",
              m.FmsControlCmd(cmd_seq=203, gear_present=True, gear=GearPosition.UP)),
        Event(80.0, "power: emergency power on (the emergency battery carries the critical load; EMERG on the PWR line)",
              m.PwrCmd(cmd_seq=203, command=PowerCommand.EMERGENCY_POWER_ON)),
        Event(83.0, "FDM: the cockpit voice recorder's card ejected (CVR card out on the systems line)",
              m.FdmCmd(cmd_seq=201, command=FdmCommand.EJECT_STORAGE, slot=2)),
        Event(85.0, "comms: send a data-link message (ACCEPTED only with a satellite; see the COM line)",
              m.ComCmd(cmd_seq=203, command=CommsCommand.DATALINK_SEND, message_id=1, priority=2)),
        Event(86.0, "comms: a radio transmission (FAILED while the field strength is under 20 %)",
              m.ComCmd(cmd_seq=204, command=CommsCommand.RADIO_TRANSMIT, message_id=2)),
    ]


def event_frame(event):
    return int(round(event.seconds * SYNC_HZ))


def script_lines(events):
    """The bus controller's --script file: 'frame rt sa hexwords' per event."""
    lines = ["# frame rt sa words (hex) - the scripted flight of fmofp_demo"]
    for event in events:
        status, words = event.message.encode()
        if status != Status.OK:
            raise ValueError(f"event {event.what!r} does not encode: {status.name}")
        lines.append(f"{event_frame(event)} {event.message.RT} {event.message.SUBADDRESS} "
                     + " ".join(f"{w:04X}" for w in words))
    return lines


def write_script(path, events):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(script_lines(events)) + "\n")


# ---- the binaries -------------------------------------------------------------------------

def shown(path):
    """A path relative to B20SS when it is under it, else as given (relpath fails across Windows drives)."""
    try:
        relative = os.path.relpath(path, B20SS)
    except ValueError:
        return path
    return path if relative.startswith("..") else relative


def default_build_dir():
    preset = "windows-ucrt64" if sys.platform == "win32" else "linux-gcc"
    return os.path.join(B20SS, "ofp", "build", preset)


def binaries(build_dir):
    """name -> path of every C++ program the demo runs."""
    exe = ".exe" if sys.platform == "win32" else ""
    paths = {"bc": os.path.join(build_dir, "bc", "fmofp_bc" + exe)}
    for name, _ in PARTITIONS:
        paths[name] = os.path.join(build_dir, "partitions", f"fmofp_{name}{exe}")
    return paths


def missing_binaries(paths):
    return [path for path in paths.values() if not os.path.isfile(path)]


def source_newer_than_binaries(paths):
    """A C++ or ICD source file newer than the oldest binary (the build is stale), or None."""
    oldest = min(os.path.getmtime(path) for path in paths.values())
    newest, newest_path = oldest, None
    for root in (os.path.join(B20SS, "ofp"), os.path.join(B20SS, "icd")):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("build", "tests") and not d.startswith(".")]
            for name in filenames:
                if name.endswith((".cpp", ".hpp", ".txt", ".cmake", ".xml", ".py")):
                    path = os.path.join(dirpath, name)
                    modified = os.path.getmtime(path)
                    if modified > newest:
                        newest, newest_path = modified, path
    return newest_path


def child_env(headless):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if sys.platform == "win32" and os.path.isdir(MSYS2_BIN):
        env["PATH"] = MSYS2_BIN + os.pathsep + env.get("PATH", "")
    if headless:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def spawn_kwargs():
    """Children in their own process group, so a Ctrl-C in this console reaches only the launcher, which then
    stops them in order."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class Programs:
    """The child processes, each with its own log file."""

    def __init__(self, log_dir, env):
        self.log_dir = log_dir
        self.env = env
        self.children = []  # (name, Popen, log file, log path)
        self.stopped = set()  # the names this launcher terminated itself

    def start(self, name, argv):
        path = os.path.join(self.log_dir, f"{name}.log")
        log = open(path, "w", encoding="utf-8")
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, cwd=B20SS, env=self.env,
                                **spawn_kwargs())
        self.children.append((name, proc, log, path))
        return proc

    def exited(self):
        """[(name, exit code)] of the children that are no longer running."""
        return [(name, proc.returncode) for name, proc, _, _ in self.children if proc.poll() is not None]

    def stop_all(self):
        for name, proc, _, _ in reversed(self.children):
            if proc.poll() is None:
                self.stopped.add(name)
                proc.terminate()
        for name, proc, log, _ in self.children:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            log.close()

    def tail(self, name, lines=4):
        for child, _, _, path in self.children:
            if child == name:
                with open(path, encoding="utf-8", errors="replace") as f:
                    return [line.rstrip() for line in f.readlines()[-lines:]]
        return []


# ---- the dashboard ------------------------------------------------------------------------

class Dashboard:
    """What the monitor port shows, summarised one line at a time."""

    def __init__(self, terminals):
        self.terminals = list(terminals)
        self.frame = -1
        self.latest = {}       # message class -> the newest decoded message
        self.last_answer = {}  # rt -> monotonic time of its last answered poll
        self.last_poll = {}    # rt -> monotonic time of its last poll
        self.classes = {(info.rt, info.subaddress): info.cls for info in m.MESSAGES
                        if info.direction == "T" and info.rt != m.EVERY_TERMINAL}

    def take(self, record, now):
        cw = record.command
        if cw.is_mode_code:
            if cw.count_or_mode == SYNC_MODE_CODE:
                self.frame += 1
            return
        if not cw.transmit:
            return
        self.last_poll[cw.rt] = now
        if not record.answered:
            return
        self.last_answer[cw.rt] = now
        cls = m.TermStatus if cw.subaddress == m.TermStatus.SUBADDRESS else self.classes.get((cw.rt, cw.subaddress))
        if cls is None or len(record.received) != cls.WORDS:
            return
        status, message = cls.decode(record.received)
        if status == Status.OK:
            self.latest[(cls, cw.rt) if cls is m.TermStatus else cls] = message

    def answering(self, now):
        return [rt for rt in self.terminals if now - self.last_answer.get(rt, -1e9) <= ANSWER_WINDOW_S]

    def line(self, elapsed_s, now):
        parts = [f"t={elapsed_s:4.0f}s", f"frame {max(self.frame, 0):5d}"]
        fd = self.latest.get(m.FmsFlightData)
        if fd is not None:
            text = f"alt {fd.altitude:5.0f} ft  ias {fd.airspeed:3.0f} kt  hdg {fd.heading:03.0f}  {fd.flight_mode.name}"
            fms = self.latest.get(m.FmsStatus)
            if fms is not None:
                text += f" weapons {fms.weapons.name}"
            parts.append(text)
        gcas = self.latest.get(m.FcsGcasAlerts)
        if gcas is not None:
            codes = [code for bit, code in (("pullup", "PULLUP"), ("sink_rate", "SINK RATE"), ("terrain", "TERRAIN"),
                                            ("alt_low", "ALT LOW")) if getattr(gcas, bit)]
            parts.append("GCAS " + gcas.status.name + (" " + ",".join(codes) if codes else ""))
        engines = self.latest.get(m.EngEngineStatus)
        if engines is not None:
            text = f"N1 {engines.n1_1:3.0f}/{engines.n1_2:3.0f} %"
            status = self.latest.get(m.EngStatus)
            if status is not None and status.autothrottle_engaged:
                text += " AT"
            if status is not None and status.asymmetric_thrust:
                text += " ASYM"
            fuel = self.latest.get(m.EngFuelStatus)
            if fuel is not None:
                text += f"  fuel {fuel.total:5.0f} kg"
            parts.append(text)
        wx = self.latest.get(m.RdrWxStatus)
        if wx is not None:
            text = "WX " + (wx.mode.name if wx.state == TerminalState.NORMAL else wx.state.name)
            scan = self.latest.get(m.RdrWxScan)
            if scan is not None and scan.scan_id:
                text += f" scan {scan.scan_id}"
            parts.append(text)
        tfr = self.latest.get(m.RdrTfrGuidance)
        if tfr is not None:
            if tfr.clearance_ssm == Ssm.NORMAL:
                parts.append(f"TFR {tfr.mode.name} clr {tfr.min_clearance:5.0f} ft {tfr.level.name}")
            else:
                parts.append("TFR " + ("off" if tfr.mode == TfrMode.NONE else tfr.mode.name))
        tgt = self.latest.get(m.RdrTgtStatus)
        if tgt is not None:
            if tgt.state == TerminalState.NORMAL and tgt.mode != TargetingMode.NONE:
                text = f"TGT {tgt.mode.name} {tgt.track_count} trk"
                if tgt.lock_status != LockStatus.NONE:
                    text += f" lock {tgt.locked_track_id} {tgt.lock_status.name}"
            else:
                text = "TGT " + ("off" if tgt.state == TerminalState.NORMAL else tgt.state.name)
            parts.append(text)
        aewc = self.latest.get(m.RdrAewcStatus)
        if aewc is not None:
            if aewc.state == TerminalState.NORMAL and aewc.mode != AewcMode.NONE:
                text = f"AEWC {aewc.track_count} trk"
                if aewc.stealth_tracks:
                    text += f" ({aewc.stealth_tracks} stealth)"
                if aewc.jammed_sectors:
                    text += " JAM"
            else:
                text = "AEWC " + ("off" if aewc.state == TerminalState.NORMAL else aewc.state.name)
            parts.append(text)
        sar = self.latest.get(m.RdrSarStatus)
        if sar is not None:
            if sar.state == TerminalState.NORMAL and sar.mode != SarMode.NONE:
                text = f"SAR {sar.mode.name} img {sar.image_seq}"
                if not sar.scene_valid:
                    text += " no scene"
                if not sar.nav_valid:
                    text += " no fix"
            else:
                text = "SAR " + ("off" if sar.state == TerminalState.NORMAL else sar.state.name)
            parts.append(text)
        msn = self.latest.get(m.MsnStatus)
        if msn is not None:
            text = f"MSN {msn.phase.name}"
            if msn.route_active:
                text += (f" wp {msn.active_index + 1}/{msn.waypoint_count} {msn.distance_to_next:.1f}nm "
                         f"{msn.bearing_to_next:03.0f}")
            elif msn.waypoint_count:
                text += f" route flown ({msn.waypoint_count} wp)"
            if msn.target_count:
                text += f" tgt {msn.target_count}"
            if msn.enemy_units:
                text += f" hostile {msn.enemy_units}"
            parts.append(text)
        com = self.latest.get(m.ComLinkStatus)
        if com is not None:
            text = f"COM {com.frequency:.3f} {'ACTIVE' if com.radio_active else 'SQUELCH'} sat {com.satcom_state.name}"
            if com.datalink_state.name == "ACTIVE":
                text += f" dl {com.packets_sent}/{com.packets_received}"
            status = self.latest.get(m.ComStatus)
            if status is not None and status.comms_cmd_status.name not in ("NONE", "ACCEPTED"):
                text += f" cmd {status.comms_cmd_status.name}"
            parts.append(text)
        defensive = self.latest.get(m.DefStatus)
        if defensive is not None:
            text = (f"DEF chaff {defensive.chaff_remaining} flares {defensive.flares_remaining} "
                    f"ECM {defensive.ecm_mode.name} rwr {defensive.contact_count}")
            if defensive.high_priority_count:
                text += f" ({defensive.high_priority_count} pri-1)"
            if defensive.auto_salvos:
                text += f" salvos {defensive.auto_salvos}"
            if defensive.defensive_cmd_status.name not in ("NONE", "ACCEPTED"):
                text += f" cmd {defensive.defensive_cmd_status.name}"
            parts.append(text)
        sns = self.latest.get(m.SnsStatus)
        if sns is not None:
            text = f"SNS {sns.health.name} {sns.contact_count} ctc"
            off = [letter for letter, on in (("R", sns.main_radar_active), ("T", sns.tfr_radar_active),
                                             ("L", sns.lidar_active), ("F", sns.flir_active),
                                             ("M", sns.maws_active), ("E", sns.esm_active)) if not on]
            if off:
                text += " off " + "".join(off)
            if sns.sensor_cmd_status.name not in ("NONE", "ACCEPTED"):
                text += f" cmd {sns.sensor_cmd_status.name}"
            parts.append(text)
        pwr = self.latest.get(m.PwrStatus)
        if pwr is not None and pwr.electrical_valid:
            text = (f"PWR gen {pwr.generator_output:3.0f} kW bal {pwr.power_balance:+3.0f} "
                    f"main {pwr.main_battery_charge:5.1f}% cool {pwr.coolant_temp:4.1f}C")
            if not pwr.generator_online:
                text += " GEN OFF"
            if pwr.emergency_mode_active:
                text += " EMERG"
            if pwr.apu_running:
                text += " APU"
            if pwr.power_cmd_status.name not in ("NONE", "ACCEPTED"):
                text += f" cmd {pwr.power_cmd_status.name}"
            parts.append(text)
        fsf = self.latest.get(m.FsfPositions)
        if fsf is not None:
            text = (f"FSF ail {fsf.aileron_l:+.1f}/{fsf.aileron_r:+.1f} el {fsf.elevator_l:+.1f} rud {fsf.rudder:+.1f} "
                    f"flaps {fsf.flap_l:.0f} slats {fsf.slat_l:.0f} sb {fsf.speedbrake:.0f}")
            status = self.latest.get(m.FsfStatus)
            if status is not None:
                if status.flap_cmd != fsf.flap_l:
                    text += f" (flaps to {status.flap_cmd:.0f})"
                if not status.sensors_valid:
                    text += " NO SENSORS"
                if status.surface_cmd_status.name not in ("NONE", "ACCEPTED"):
                    text += f" cmd {status.surface_cmd_status.name}"
            parts.append(text)
        hyd = self.latest.get(m.HydStatus)
        ecs = self.latest.get(m.EcsStatus)
        afr = self.latest.get(m.AfrStatus)
        fdm = self.latest.get(m.FdmStatus)
        bits = []
        if hyd is not None and hyd.pressures_valid:
            bits.append(f"HYD {hyd.primary_psi:.0f}/{hyd.backup_psi:.0f} psi {hyd.active_system.name} "
                        f"{hyd.pressure_status.name}")
        if ecs is not None and ecs.sensors_valid:
            bits.append(f"ECS {ecs.temperature:.1f}C {ecs.pressure:.1f}kPa O2 {ecs.oxygen_level:.1f}%")
        if afr is not None:
            bits.append(f"gear {afr.gear_state.name}")
        if fdm is not None:
            bits.append(f"FDR {fdm.records:.0f} rec" + ("" if fdm.slot_2_present else " CVR card out"))
        if bits:
            parts.append(" ".join(bits))
        avn = self.latest.get(m.AvnStatus)
        if avn is not None and avn.bus_health_valid:
            text = f"AVN {avn.overall_health.name} {avn.fault_count}/{avn.lru_count} faults"
            if avn.forced_count:
                text += f" ({avn.forced_count} forced)"
            if avn.ibit_runs:
                text += f" ibit {avn.ibit_pass}/{avn.ibit_pass + avn.ibit_fail + avn.ibit_abort}"
            if avn.avionics_cmd_status.name not in ("NONE", "ACCEPTED"):
                text += f" cmd {avn.avionics_cmd_status.name}"
            parts.append(text)
        nav = self.latest.get(m.NavSolution)
        if nav is not None and nav.position_ssm == Ssm.NORMAL:
            parts.append(f"nav {nav.latitude:+.4f} {nav.longitude:+.4f} ({nav.sats_used} sats)")
        answering = self.answering(now)
        text = f"{len(answering)}/{len(self.terminals)} answering"
        silent = [NAMES.get(rt, str(rt)) for rt in self.terminals if rt not in answering and rt in self.last_poll]
        if silent:
            text += " (silent: " + ", ".join(silent) + ")"
        parts.append(text)
        return " | ".join(parts)


# ---- the run ------------------------------------------------------------------------------

def banner(args, terminals, events, log_dir, paths):
    print(f"fmofp_demo: {len(terminals)} terminals on port base {args.port_base}, binaries from "
          f"{shown(os.path.dirname(paths['bc']))}, logs in {shown(log_dir)}")
    if not args.no_displays and not args.headless:
        print("  radar display window: weather picture left, terrain picture right; its WX, TFR, TGT, AEWC and SAR buttons\n"
              "    set the radars' modes, the spinboxes the terrain-following set clearance, the track to lock and the\n"
              "    SAR resolution.\n"
              "  PFD window: attitude, airspeed, altitude and heading from the FMS flight data.\n"
              "  MFD window: RADAR shows the radars' pictures (Targeting Radar and AEWC Radar: their tracks; Synthetic\n"
              "    Aperture: its picture of the ground, a new one every 3 s), SYSTEMS the GCAS alerts,\n"
              "    exceedances and engine\n"
              "    rows, COMMS the radio, satcom and data link, MISSION the route (the active waypoint marked),\n"
              "    the targets and the order of battle.\n"
              "  EICAS window: the engine readings, the fuel quantity and balance, the FCS alerts and the crew alert\n"
              "    list, the countermeasures and the radar warning ring, the sensors' health and fused track count,\n"
              "    the electrical rows (main and essential bus, the generators: FAIL during the generator-off event)\n"
              "    the BITS rows (the power-on self tests, from the avionics terminal)\n"
              "    (hydraulics and ECS read unknown until their terminals exist).\n"
              "  TSD window: the fused air tracks around the aircraft (bearing and range), the route's waypoints,\n"
              "    the enemy unit as a hostile contact, the radar warning contacts on the ring's edge (red dots with\n"
              "    their band), the energy metrics and the tactical systems strip.\n"
              "  SMS window: the weapon stations, colour-coded by state, and the signature strip; MASTER ARM follows\n"
              "    the FMS's weapons state (ARMED from the COMBAT event at 30 s).")
    if events:
        print("  scripted flight: " + "; ".join(f"{e.seconds:.0f} s {e.what}" for e in events))
    print("  stop with Ctrl-C" + (f"; runs for {args.seconds:.0f} s" if args.seconds > 0 else ""))
    print()


def run(monitor, bc, programs, terminals, events):
    """The dashboard loop until the controller exits (a timed run) or a core program dies. Returns the exit code."""
    dash = Dashboard(terminals)
    start = time.monotonic()
    next_line = start + 1.0
    fired = set()
    closed = set()
    while True:
        record = monitor.read(0.02)
        now = time.monotonic()
        if record is not None:
            dash.take(record, now)
        for index, event in enumerate(events):
            if index not in fired and dash.frame >= event_frame(event):
                fired.add(index)
                print(f"  >> t={event.seconds:.0f} s: {event.what}")
        if now >= next_line:
            print(dash.line(now - start, now), flush=True)
            next_line += 1.0
        if bc.poll() is not None:
            return 0 if bc.returncode == 0 else 1
        for name, code in programs.exited():
            if name == "bc" or name in closed:
                continue
            closed.add(name)
            if name.startswith("display_"):
                print(f"  (the {name[len('display_'):]} display window closed)")
            else:
                print(f"\n{name} exited with code {code}:")
                for line in programs.tail(name):
                    print("    " + line)
                return 1


def summary(programs, log_dir):
    print(f"\nlogs: {log_dir}")
    bc_log = os.path.join(log_dir, "bc.log")
    if os.path.isfile(bc_log):
        with open(bc_log, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(("bc: frames=", "  rt ", "bc: script")):
                    print("  " + line.rstrip())
    print("  " + ", ".join(f"{name} {'stopped' if name in programs.stopped else f'exit {proc.returncode}'}"
                           for name, proc, _, _ in programs.children))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=0.0, help="run this long (0 = until Ctrl-C)")
    parser.add_argument("--port-base", type=int, default=51000)
    parser.add_argument("--build", default=None, help="the C++ build directory (default: ofp/build/<preset>)")
    parser.add_argument("--headless", action="store_true", help="displays without windows (offscreen Qt)")
    parser.add_argument("--no-displays", action="store_true", help="only the plant, the partitions and the bus")
    parser.add_argument("--no-events", action="store_true", help="no scripted flight")
    parser.add_argument("--hold", default="heading=0,speed=450",
                        help="plant quantities held constant (default heading=0,speed=450: the SAR's ground scene lies "
                             "along the northbound track from home, the lake abeam at 65 s; give '' to free them)")
    parser.add_argument("--seed", type=int, default=None, help="the plant's random seed")
    parser.add_argument("--log-dir", default=None, help="where the programs' logs go (default: logs/demo)")
    parser.add_argument("--settle", type=float, default=4.0, help="seconds to let the programs start before the bus")
    args = parser.parse_args(argv)

    paths = binaries(args.build or default_build_dir())
    missing = missing_binaries(paths)
    if missing:
        print("fmofp_demo: the C++ programs are not built:", file=sys.stderr)
        for path in missing:
            print("  " + path, file=sys.stderr)
        print("  build them first: see ofp/README.md (cmake --preset ... && cmake --build --preset ...)", file=sys.stderr)
        return 2
    stale = source_newer_than_binaries(paths)
    if stale is not None:
        print(f"fmofp_demo: note: {shown(stale)} is newer than the binaries; rebuild if the C++ or the ICD changed")
    log_dir = args.log_dir or os.path.join(B20SS, "logs", "demo")
    os.makedirs(log_dir, exist_ok=True)
    events = [] if args.no_events else default_events()
    if args.seconds > 0.0:
        events = [event for event in events if event.seconds < args.seconds]
    script = os.path.join(log_dir, "events.txt")
    if events:
        write_script(script, events)
    terminals = [PLANT_RT] + [rt for _, rt in PARTITIONS]
    if not args.no_displays:
        terminals += [rt for _, rt in DISPLAYS]

    monitor = Monitor(args.port_base)
    if monitor.open() != Status.OK:
        print(f"fmofp_demo: the monitor port {args.port_base + 33} is in use: is another bus running? "
              f"(try --port-base)", file=sys.stderr)
        return 2
    programs = Programs(log_dir, child_env(args.headless))
    banner(args, terminals, events, log_dir, paths)
    code = 1
    try:
        plant = [sys.executable, "-m", "fmofp_plant", "--port-base", str(args.port_base), "--quiet"]
        if args.seed is not None:
            plant += ["--seed", str(args.seed)]
        if args.hold:
            plant += ["--hold", args.hold]
        programs.start("plant", plant)
        for name, _ in PARTITIONS:
            programs.start(name, [paths[name], "--port-base", str(args.port_base), "--quiet"])
        if not args.no_displays:
            for name, _ in DISPLAYS:
                programs.start(f"display_{name}",
                               [sys.executable, "-m", "fmofp_display", name, "--port-base", str(args.port_base)])
        time.sleep(args.settle)
        dead = programs.exited()
        if dead:
            for name, exit_code in dead:
                print(f"{name} exited with code {exit_code} before the bus started:")
                for line in programs.tail(name):
                    print("    " + line)
            return 1
        bc = [paths["bc"]]
        for rt in terminals:
            bc += ["--rt", str(rt)]
        bc += ["--port-base", str(args.port_base), "--report", "--timeout-ms", "20"]
        if args.seconds > 0.0:
            bc += ["--frames", str(int(args.seconds * SYNC_HZ))]
        if events:
            bc += ["--script", script]
        code = run(monitor, programs.start("bc", bc), programs, terminals, events)
    except KeyboardInterrupt:
        print("\nstopping")
        code = 0
    finally:
        programs.stop_all()
        monitor.close()
        summary(programs, log_dir)
    return code


if __name__ == "__main__":
    sys.exit(main())
