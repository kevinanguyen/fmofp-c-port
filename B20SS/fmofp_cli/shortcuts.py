"""Upstream's canned messages as named shortcuts on the bus (unit 35).

`Interfaces/predefinedMessages` (deleted in unit 29) built canned requests for the five radars, the FMS and the FCS,
each a free-form dictionary carried by the old messaging. On the bus each request is one ICD command message, so a
shortcut is a name, the canned builder it stands for, the message, the fields it fixes and the fields its arguments
fill: `do wx SURVEILLANCE 200` is `send RDR_WX_MODE_CMD requested_state=NORMAL requested_mode=SURVEILLANCE
range_km=200`. Arguments after the positional ones may name any field of the message (`do wx MAPPING tilt=2`).

The canned *requests for data* (precipitation, VIL, echo top, elevation, imagery) asked a radar to compute and send a
product; on the bus every product is published periodically, so those shortcuts read the message that carries it
(the prompt's `msg`).
"""

import dataclasses
from collections import namedtuple

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import TerminalState

# name; the canned builder it stands for; the message; the fields it sets first (a mode it stands for, or the radar
# window's defaults: 200 km, 1000 ft, 1 m; an argument for the same field overrides them); the positional arguments
# (field names; a trailing '?' marks one that may be left out); fields whose `<field>_present` flag a value sets;
# one line of help.
Shortcut = namedtuple("Shortcut", "name origin cls fixed positional present help")
# name; the canned builder; the message id read; one line of help.
Reading = namedtuple("Reading", "name origin message_id help")

ATTITUDE_FIELDS = ("roll", "pitch", "yaw", "roll_rate", "pitch_rate", "yaw_rate")
TARGET_FIELDS = ("altitude", "airspeed", "heading", "vertical_speed")

SHORTCUTS = (
    Shortcut("wx", "WeatherRadarMessages.create_weather_radar_mode_change_request", m.RdrWxModeCmd, {"range_km": "200"},
             ("requested_mode", "range_km?", "tilt?"), (), "the weather radar's mode [range km] [tilt deg]"),
    Shortcut("tfr", "TFRRadarMessages.create_tfr_elevation_data_request", m.RdrTfrModeCmd, {"set_clearance": "1000"},
             ("requested_mode", "set_clearance?"), (), "the terrain-following radar's mode [set clearance ft]"),
    Shortcut("sar", "SARRadarMessages.create_sar_imagery_request", m.RdrSarModeCmd, {"resolution": "1"},
             ("requested_mode", "resolution?"), (), "the SAR's mode [resolution m]"),
    Shortcut("tgt", "TargetingRadarMessages.create_targeting_radar_track_request", m.RdrTgtModeCmd, {},
             ("requested_mode", "track_filter?"), (), "the targeting radar's mode [track filter]"),
    Shortcut("tgt-lock", "TargetingRadarMessages.create_targeting_radar_lock_request", m.RdrTgtModeCmd,
             {"requested_mode": "TARGET_TRACK"}, ("lock_track_id",), (),
             "lock the targeting radar on a track id (TARGET_TRACK: the radar takes a lock in no other mode)"),
    Shortcut("aewc", "AEWCRadarMessages.create_aewc_radar_track_request", m.RdrAewcModeCmd, {},
             ("requested_mode",), (), "the AEWC radar's mode"),
    Shortcut("aewc-sector", "AEWCRadarMessages.create_aewc_radar_sector_scan_request", m.RdrAewcModeCmd,
             {"requested_mode": "SECTOR_SCAN"}, ("azimuth_start", "azimuth_end", "elevation?"), (),
             "the AEWC radar's sector scan: start and end azimuth deg [elevation deg]"),
    Shortcut("attitude", "FMSMessages.create_attitude_update_request", m.FmsAttitudeCmd, {}, (), ATTITUDE_FIELDS,
             "the FMS's attitude update: roll= pitch= yaw= roll_rate= pitch_rate= yaw_rate= (deg, deg/s)"),
    Shortcut("nav", "FMSMessages.create_navigation_update_request", m.FmsNavUpdateCmd, {}, (), TARGET_FIELDS,
             "the FMS's navigation targets: altitude= airspeed= heading= vertical_speed="),
    Shortcut("autopilot", "FCSMessages.create_autopilot_request", m.FmsNavUpdateCmd, {}, (), TARGET_FIELDS,
             "the autopilot's targets (the FMS's SET_AUTOPILOT, the same message as nav)"),
    Shortcut("maneuver", "FMSMessages.create_maneuver_request", m.FmsManeuverCmd, {},
             ("maneuver", "dive_angle?"), (), "an FMS maneuver [dive angle deg]"),
    Shortcut("surface", "FCSMessages.create_control_surface_request", m.FcsSurfaceCmd, {},
             ("surface", "position"), (), "a control surface command: the surface and its position (% of travel)"),
    Shortcut("flight-mode", "FCSMessages.create_flight_mode_request", m.FmsFlightModeCmd, {},
             ("flight_mode",), (), "the FMS's flight mode"),
)

READINGS = (
    Reading("precipitation", "WeatherRadarMessages.create_precipitation_request", "RDR_WX_SCAN",
            "the weather radar's last scan (its precipitation products are drawn by the radar window)"),
    Reading("vil", "WeatherRadarMessages.create_vil_request", "RDR_WX_SCAN",
            "the weather radar's last scan: its VIL maximum"),
    Reading("echo-top", "WeatherRadarMessages.create_echo_top_request", "RDR_WX_SCAN",
            "the weather radar's last scan (echo tops are not computed: unit 7)"),
    Reading("elevation", "TFRRadarMessages.create_tfr_elevation_data_request (data)", "RDR_TFR_GUIDANCE",
            "the terrain-following radar's clearance and commands"),
    Reading("imagery", "SARRadarMessages.create_sar_imagery_request (data)", "RDR_SAR_STATUS",
            "the SAR's status and its last image's number"),
    Reading("tracks", "TargetingRadarMessages.create_targeting_radar_track_request (data)", "RDR_TGT_STATUS",
            "the targeting radar's status, track count and lock"),
)

BY_NAME = {s.name: s for s in SHORTCUTS}
READING_BY_NAME = {r.name: r for r in READINGS}

# The mission briefing (unit 37, MSN_BRIEF_CMD): MissionControl's set_objectives, set_roe and update_intelligence,
# one entry a command. name -> (command name, whether it takes a key, help).
BRIEFINGS = {
    "objective": ("ADD_OBJECTIVE", False, "add an objective: do objective TEXT (24 characters)"),
    "roe": ("ADD_ROE", False, "add a rule of engagement: do roe TEXT"),
    "intel": ("UPDATE_INTELLIGENCE", True, "set an intelligence item: do intel KEY TEXT (a key of 8 characters)"),
    "clear-objectives": ("CLEAR_OBJECTIVES", False, "empty the objectives"),
    "clear-roe": ("CLEAR_ROE", False, "empty the rules of engagement"),
    "clear-intel": ("CLEAR_INTELLIGENCE", False, "empty the intelligence"),
}


def briefing(name, args):
    """The MSN_BRIEF_CMD a briefing shortcut makes from its words."""
    from fmofp_bus.briefing import brief_command
    from fmofp_bus.icd.enums import BriefingCommand
    command, takes_key, help_text = BRIEFINGS[name]
    words = list(args)
    key = ""
    if takes_key:
        if not words:
            raise ValueError(f"do {name}: {help_text}")
        key = words.pop(0)
    text = " ".join(words)
    if command.startswith("ADD") or command.startswith("UPDATE"):
        if not text:
            raise ValueError(f"do {name}: {help_text}")
    return brief_command(BriefingCommand[command], text=text, key=key)

# The six display terminals' mode commands (the HUD, RT 18, has none: unit 27 struck it).
DISPLAY_MODE_COMMANDS = {"radar": m.DspRadarModeCmd, "pfd": m.DspPfdModeCmd, "mfd": m.DspMfdModeCmd,
                         "eicas": m.DspEicasModeCmd, "tsd": m.DspTsdModeCmd, "sms": m.DspSmsModeCmd}


def listing():
    """The help lines of every shortcut and reading."""
    lines = []
    for s in SHORTCUTS:
        args = " ".join(p.rstrip("?").upper() if not p.endswith("?") else f"[{p.rstrip('?').upper()}]"
                        for p in s.positional)
        if s.present:
            args = (args + " " if args else "") + "[field=value ...]"
        lines.append(f"  do {s.name} {args}".rstrip())
        lines.append(f"      {s.help}; {s.cls.__name__} (was {s.origin})")
    for r in READINGS:
        lines.append(f"  do {r.name}")
        lines.append(f"      {r.help}: msg {r.message_id} (was {r.origin})")
    for name, (_, _, help_text) in BRIEFINGS.items():
        lines.append(f"  do {name}")
        lines.append(f"      {help_text}; MSN_BRIEF_CMD (was MissionControl's briefing)")
    return lines


def build(shortcut, args, parse_field):
    """The message a shortcut makes from its arguments. `parse_field(cls, name, text)` types a value (the prompt's
    own parser). ValueError for a missing or unknown argument."""
    cls = shortcut.cls
    names = {f.name for f in dataclasses.fields(cls)}
    values = {name: parse_field(cls, name, text) for name, text in shortcut.fixed.items()}
    positional = [a for a in args if "=" not in a]
    keyword = [a for a in args if "=" in a]
    if len(positional) > len(shortcut.positional):
        raise ValueError(f"do {shortcut.name}: too many arguments ({len(positional)} for "
                         f"{len(shortcut.positional)})")
    required = [p for p in shortcut.positional if not p.endswith("?")]
    if len(positional) < len(required):
        missing = ", ".join(p.upper() for p in required[len(positional):])
        raise ValueError(f"do {shortcut.name}: missing {missing} ({shortcut.help})")
    for spec, text in zip(shortcut.positional, positional):
        name = spec.rstrip("?")
        values[name] = parse_field(cls, name, text)
    for arg in keyword:
        name, _, text = arg.partition("=")
        if name not in names:
            raise ValueError(f"do {shortcut.name}: {cls.__name__} has no field {name!r}")
        values[name] = parse_field(cls, name, text)
    for name in shortcut.present:
        if name in values:
            values[f"{name}_present"] = True
    if shortcut.present and not any(name in values for name in shortcut.present):
        raise ValueError(f"do {shortcut.name}: give at least one of {', '.join(f'{n}=' for n in shortcut.present)}")
    if "requested_state" in names and "requested_state" not in values:
        # Mode 0 (NONE) asks the radar to stand by, as the radar window's OFF button does; any other mode operates.
        mode = values.get("requested_mode")
        values["requested_state"] = TerminalState.STANDBY if mode is not None and int(mode) == 0 else \
            TerminalState.NORMAL
    return cls(**values)


def display_mode_commands(mode, displays=None, cmd_seq=0):
    """(name, message) for each display asked (all six by default), each its DSP_*_MODE_CMD with the lighting mode;
    cmd_seq 0 lets the bus controller number it (the prompt), the demo's script gives its own (201)."""
    names = list(DISPLAY_MODE_COMMANDS) if not displays else [d.lower() for d in displays]
    out = []
    for name in names:
        cls = DISPLAY_MODE_COMMANDS.get(name)
        if cls is None:
            raise ValueError(f"no display {name!r}: one of {', '.join(DISPLAY_MODE_COMMANDS)}")
        out.append((name, cls(requested_state=TerminalState.NORMAL, requested_mode=mode, cmd_seq=cmd_seq)))
    return out
