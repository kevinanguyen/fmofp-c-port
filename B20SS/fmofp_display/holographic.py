"""The holographic PFD and MFD fed from the bus (unit 34, ICD v1.27).

Upstream chose these two displays for the MODERN theme (`visual/theme_manager.py`'s `display_types`) but never fed
them: the holographic PFD had no data source at all (`PROVIDES_FLIGHT_DATA = False`, and upstream's own factory
refused to build it), and the holographic MFD drew an empty tactical picture beside panels of fixed values (fuel 85 %,
THRUST 92 %, AIM-120C x4, UHF 1 243.000 ACTIVE, MESSAGES: 2 NEW). The frozen files are not edited; this module

* builds, from what the display terminals hear on the bus, the values each display draws (`pfd_picture`,
  `mfd_picture`: plain functions of the feeds, tested without Qt);
* subclasses the two frozen classes (`BusHolographicPFD`, `BusHolographicMFD`) to apply those values once a tick, and
  marks a picture invalid (data_validity's amber cross) instead of drawing a number the bus has not vouched for;
* rebuilds seven of the frozen MFD's panel methods with their fixed lists, strings and one number replaced by calls
  that read the bus picture (`rewrite_methods`: the frozen source, changed in its syntax tree at import, every
  replacement counted, so that a change of the frozen file fails loudly instead of drawing a fixed value again).

What the bus does not carry is said, not invented: the INS (never carried, unit 5), the encryption and IFF rows of the
comms status (no such systems), the MFD's weather radar page (the holographic weather display has no bus feed; the
radar window draws the weather). ICD README section 2 has a row for each departure.
"""
import ast
import inspect
import math

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import TerminalState
from fmofp_display.systems_feed import STATIONS, STORE_KINDS
from fmofp_display.terminal import STALE_AFTER_S

M_PER_NM = 1852.0
FT_PER_M = 3.28084
KT_PER_MPS = 1.943844
NM_PER_DEG_LAT = 60.0
PICTURE_RADIUS_NM = 100.0  # the tactical picture's scale: the frozen MFD places x and y in percent of its radius
TARGETING_RANGE_NM = 100.0 / 1.852  # the targeting radar's 100 km
FUEL_CAPACITY_KG = 40000.0  # the engine computer's three tanks (kTankCapacityKg: 10000, 10000, 20000)
CENTER_CAPACITY_KG = 20000.0
GONE_STATES = ("EXPENDED", "JETTISONED", "EMPTY")

# The frozen MFD's target symbols know FIGHTER, UAV, BOMBER and MISSILE; the radar's classes map onto them.
SYMBOL_TYPE = {"FIGHTER": "FIGHTER", "BOMBER": "BOMBER", "MISSILE": "MISSILE", "DRONE": "UAV", "HIGH_ALT": "HIGH_ALT",
               "HELICOPTER": "HELICOPTER", "STEALTH": "STEALTH", "UNKNOWN": "UNKNOWN"}
# The frozen display colours a target by a threat level of 0-10 (8 and over critical, 5 and over warning).
THREAT_LEVEL = {"HOSTILE": 8, "UNKNOWN": 4, "FRIENDLY": 1}
# The PFD's threat ring is drawn above level 2: the radar warning receiver's priority 1 (the most urgent) to 4.
PRIORITY_LEVEL = {1: 9, 2: 6, 3: 4, 4: 3}


class Unknown(int):
    """A number the bus has not vouched for. It prints as '--' and compares as 100, so that the frozen colour rules
    (fuel under 20 % critical, under 40 % warning) draw it in their normal colour rather than alarm on a value that
    does not exist."""

    def __new__(cls):
        return super().__new__(cls, 100)

    def __format__(self, spec):
        return "--"

    def __str__(self):
        return "--"

    __repr__ = __str__


def _flight(terminal, stale=STALE_AFTER_S):
    message = terminal.fresh(m.BcastFmsFlightData, stale)
    return None if message is None else message.payload


def _valid(ssm):
    return ssm.name == "NORMAL"


def fuel_percent(fuel):
    """The total fuel as a whole percent of the three tanks, or Unknown while the engine computer is silent."""
    if not fuel:
        return Unknown()
    return int(round(fuel["total"] / FUEL_CAPACITY_KG * 100.0))


# ---- the PFD ---------------------------------------------------------------------------------------------------

def pfd_picture(flight_feed, systems_feed):
    """What the holographic PFD draws, from the PFD terminal: the FMS's flight data (v1.2), its status, the engine
    computer's fuel and the radar warning receiver's contacts (both heard by the PFD since v1.27). `valid` is False
    while any of the five numbers the picture is built on (altitude, airspeed, heading, pitch, roll) is missing or
    stale: the display then crosses the picture out."""
    data = flight_feed.get_flight_data()
    attitude = data.get("attitude", {})
    velocity = data.get("velocity", {})
    navigation = data.get("navigation", {})
    tactical = data.get("tactical", {})
    valid = (all(k in attitude for k in ("pitch", "roll")) and "airspeed" in velocity
             and all(k in navigation for k in ("altitude", "heading")))
    heading = navigation.get("heading", 0.0)
    out = {"valid": valid,
           "altitude": navigation.get("altitude", 0.0), "vertical_speed": velocity.get("vertical_speed", 0.0),
           "airspeed": velocity.get("airspeed", 0.0), "mach": velocity.get("mach", 0.0), "heading": heading,
           "pitch": attitude.get("pitch", 0.0), "roll": attitude.get("roll", 0.0),
           "g_force": tactical.get("g_force", 1.0), "aoa": tactical.get("aoa", 0.0),
           "energy_state": int(round(tactical["energy_state"])) if "energy_state" in tactical else Unknown(),
           "flight_mode": data.get("status", {}).get("mode", "NO FMS DATA")}
    status = systems_feed.terminal.fresh(m.BcastFmsStatus, systems_feed.stale_after_s)
    weapons = status.payload.weapons.name if status is not None else "NO DATA"
    hostile = [c for c in systems_feed.rwr_contacts() if c["hostile"]]
    threat_level, threat_direction = 0, 0.0
    if hostile:
        first = min(hostile, key=lambda c: c["priority"])  # the block is by priority; min keeps the first of the best
        threat_level = PRIORITY_LEVEL.get(first["priority"], 3)
        # The ring is drawn clockwise from the nose: the contact's true bearing less the heading.
        threat_direction = (first["bearing_deg"] - heading) % 360.0 if "heading" in navigation else first["bearing_deg"]
    out["tactical"] = {"threat_level": threat_level, "threat_direction": threat_direction, "weapon_status": weapons,
                       "fuel_state": fuel_percent(systems_feed.fuel_data()), "threat_count": len(hostile)}
    return out


# ---- the MFD ---------------------------------------------------------------------------------------------------

def _track(record, prefix, own_altitude_ft):
    """One radar track as the frozen MFD's target dictionary: x east and y south of the aircraft in nautical miles
    (the picture's 100 NM radius makes them its percent), heading and speed of the track's velocity relative to the
    aircraft (what the radar measures), altitude the aircraft's plus the track's height above it."""
    east, north = record.x / M_PER_NM, record.y / M_PER_NM
    speed = math.hypot(record.velocity_east, record.velocity_north) * KT_PER_MPS
    heading = math.degrees(math.atan2(record.velocity_east, record.velocity_north)) % 360.0
    level = min(10, THREAT_LEVEL.get(record.threat.name, 4) + (1 if getattr(record, "locked", False) else 0))
    return {"id": f"{prefix}{record.track_id}", "x": east, "y": -north, "heading": heading, "speed": speed,
            "altitude": own_altitude_ft + record.z * FT_PER_M, "type": SYMBOL_TYPE.get(record.classification.name,
                                                                                      "UNKNOWN"),
            "threat_level": level, "threat": record.threat.name, "identity": record.identity.name}


def _tracks(terminal, stale, own_altitude_ft):
    """The targeting radar's tracks (T1...) and the AEWC radar's (A1...) within the picture."""
    out = []
    for cls, prefix in ((b.MfdRdrTgtTracks, "T"), (b.MfdRdrAewcTracks, "A")):
        block, _, age = terminal.latest_block(cls)
        if block is None or age is None or age > stale:
            continue
        for record in block.track:
            track = _track(record, prefix, own_altitude_ft)
            if math.hypot(track["x"], track["y"]) <= PICTURE_RADIUS_NM:
                out.append(track)
    return out


def _waypoints(systems, flight):
    """The mission route's waypoints within the picture, placed from the aircraft's position (flat earth)."""
    if flight is None or not _valid(flight.position_ssm):
        return []
    out = []
    coslat = math.cos(math.radians(flight.latitude))
    for w in systems.route_data()["route"]:
        east = (w["lon"] - flight.longitude) * NM_PER_DEG_LAT * coslat
        north = (w["lat"] - flight.latitude) * NM_PER_DEG_LAT
        if math.hypot(east, north) <= PICTURE_RADIUS_NM:
            out.append({"id": w["name"] or str(w["id"]), "x": east, "y": -north, "altitude": w["alt_ft"]})
    return out


def _stores(systems):
    """The MFD's weapons rows from the stores management terminal (MFD_SMS_STORES): the inventory by store, the
    selected station's store, the avionics panel's weapons rows; None while the terminal is not heard."""
    p = systems.stores_status()
    stations = systems.stores_stations()
    if p is None or stations is None:
        return None
    inventory = {}
    for station in stations:
        if station is None:
            continue
        name, _, qty, state, store_type = station
        if state in GONE_STATES or qty <= 0:
            continue
        entry = inventory.setdefault(name, {"name": name, "count": 0, "type": store_type})
        entry["count"] += qty
    selected = stations[p.selected_station - 1] if 1 <= p.selected_station <= STATIONS else None
    selected_name = selected[0] if selected is not None and selected[3] not in GONE_STATES else "EMPTY"
    return {"master_arm": p.master_arm.name, "selected_station": p.selected_station, "selected_name": selected_name,
            "inventory": [dict(e, count=str(e["count"])) for e in inventory.values()],
            "armed_count": p.armed_count, "total_weight": p.total_weight, "released": p.stores_released}


def _terrain(radar):
    """A 20 by 20 height grid for the navigation page's terrain from the terrain-following radar's profile ahead
    (the far end at the top, the same height across a row: the radar sees one line), each height between 0.1 and
    0.9 of the profile's span; None without a profile."""
    profile = radar.tfr_data()["tfr_data"] if radar is not None else []
    if len(profile) < 2:
        return None
    heights = [p["elevation"] for p in profile]
    low, high = min(heights), max(heights)
    span = high - low
    rows = []
    for row in range(20):
        index = round((19 - row) / 19 * (len(heights) - 1))
        value = 0.5 if span <= 0.0 else 0.1 + 0.8 * (heights[index] - low) / span
        rows.append([value] * 20)
    return rows


def mfd_picture(systems, radar=None):
    """What the holographic MFD draws, from the MFD terminal: `tactical` (its tactical_data), `system_status`, the
    panels' `rows`, `texts` and `numbers` (read by the rewritten panel methods), and `terrain` (None: crossed out)."""
    terminal, stale = systems.terminal, systems.stale_after_s
    flight = _flight(terminal, stale)
    altitude_ok = flight is not None and _valid(flight.altitude_ssm)
    tracks = _tracks(terminal, stale, flight.altitude) if altitude_ok else []
    targets = [t for t in tracks if t["identity"] != "FRIENDLY"]
    friendlies = [{k: t[k] for k in ("id", "x", "y", "heading", "type")} for t in tracks if t["identity"] == "FRIENDLY"]
    threats = [{k: t[k] for k in ("id", "x", "y", "threat_level")} for t in targets if t["threat"] == "HOSTILE"]
    tactical = {"targets": targets, "friendlies": friendlies, "waypoints": _waypoints(systems, flight),
                "threats": threats, "terrain_features": []}

    tgt = terminal.fresh(m.BcastRdrTgtStatus, stale)
    if tgt is None:
        radar_status = "NO DATA"
    elif tgt.payload.state == TerminalState.NORMAL:
        radar_status = tgt.payload.mode.name
    else:
        radar_status = tgt.payload.state.name
    comms = systems.comms_data()
    engine = systems.engine_data()
    fuel = systems.fuel_data()
    stores = _stores(systems)
    fms_status = terminal.fresh(m.BcastFmsStatus, stale)
    system_status = {
        "radar": radar_status,
        "comms": ("ACTIVE" if comms["radio"]["active"] else "INACTIVE") if comms else "NO DATA",
        "weapons": stores["master_arm"] if stores is not None else "NO DATA",
        "navigation": "NOMINAL" if flight is not None and _valid(flight.position_ssm) else "NO FIX",
        "fuel": fuel_percent(fuel),
        "engine": "NOMINAL" if engine else "NO DATA",
        "stealth": ("ACTIVE" if fms_status.payload.stealth_mode else "INACTIVE") if fms_status is not None else "NO DATA",
    }

    no_data = [{"name": "NO DATA", "value": "--", "color": "warning"}]
    rows = {}
    if engine:
        rows["engine"] = [{"name": "THRUST", "value": f"{engine['thrust_pct']:.0f}%", "color": "system_normal"},
                          {"name": "EGT", "value": f"{engine['egt_c']:.0f}°C", "color": "system_normal"},
                          {"name": "N1", "value": f"{engine['n1_pct']:.0f}%", "color": "system_normal"},
                          {"name": "OIL PRESS", "value": f"{engine['oil_psi']:.0f} PSI", "color": "system_normal"}]
    else:
        rows["engine"] = no_data
    if fuel:
        pct = fuel_percent(fuel)
        colour = "critical" if pct < 20 or fuel["critical"] else ("warning" if pct < 40 or fuel["low"] else
                                                                  "system_normal")
        burn = fuel["burn_rate_kgh"]
        endurance = "--"
        if burn > 0.0:
            minutes = int(fuel["total"] / burn * 60.0)
            endurance = f"{minutes // 60}:{minutes % 60:02d}"
        rows["fuel"] = [{"name": "TOTAL", "value": f"{pct}%", "color": colour},
                        {"name": "CENTER", "value": f"{fuel['Center'] / CENTER_CAPACITY_KG * 100.0:.0f}%",
                         "color": "system_normal"},
                        {"name": "FLOW RATE", "value": f"{burn:.0f} KG/H", "color": "system_normal"},
                        {"name": "ENDURANCE", "value": endurance, "color": "system_normal"}]
        if fuel["leak_suspected"]:
            rows["fuel"].append({"name": "LEAK", "value": "SUSPECTED", "color": "critical"})
    else:
        rows["fuel"] = no_data
    rows["radar"] = [{"name": "MODE", "value": radar_status, "color": "data_primary"},
                     {"name": "RANGE", "value": f"{TARGETING_RANGE_NM:.0f} NM", "color": "data_primary"},
                     {"name": "TARGETS", "value": str(len(targets)), "color": "data_primary"}]
    if stores is not None:
        rows["weapons"] = [{"name": "STATUS", "value": stores["master_arm"],
                            "color": "warning" if stores["master_arm"] == "ARMED" else "system_normal"},
                           {"name": "ARMED STA", "value": str(stores["armed_count"]), "color": "data_primary"},
                           {"name": "LOAD", "value": f"{stores['total_weight']:.0f} KG", "color": "data_primary"},
                           {"name": "RELEASED", "value": str(stores["released"]), "color": "data_primary"}]
        rows["inventory"] = stores["inventory"]
    else:
        rows["weapons"] = no_data
        rows["inventory"] = []
    if comms:
        radio, satcom, link = comms["radio"], comms["satcom"], comms["datalink"]
        rows["channels"] = [
            {"name": "RADIO", "freq": f"{radio['frequency']:.3f}", "mode": radio["mode"],
             "status": "ACTIVE" if radio["active"] else "STANDBY"},
            {"name": "SATCOM", "freq": str(satcom["satellite_id"]) if satcom["satellite_id"] else "--", "mode": "DATA",
             "status": satcom["connection_status"].upper()},
            {"name": "DATALINK", "freq": f"CH {link['channel']}", "mode": link["mode"],
             "status": link["link_status"].upper()}]
        rows["comm_status"] = [
            {"name": "RADIO", "status": "ACTIVE" if radio["active"] else "INACTIVE",
             "color": "system_normal" if radio["active"] else "warning"},
            {"name": "SATCOM", "status": satcom["connection_status"].upper(),
             "color": "system_normal" if satcom["connection_status"] == "connected" else "warning"},
            {"name": "DATALINK", "status": link["link_status"].upper(),
             "color": "system_normal" if link["link_status"] == "active" else "warning"}]
    else:
        rows["channels"] = []
        rows["comm_status"] = [{"name": "COMMS", "status": "NO DATA", "color": "warning"}]
    if stores is None:
        selected, weapon = "SELECTED: NO DATA", "WEAPON: NO DATA"
    else:
        selected = f"SELECTED: STA {stores['selected_station']} {stores['selected_name']}"
        weapon = f"WEAPON: {stores['selected_name']}"
    texts = {"selected": selected, "weapon": weapon, "ins": "INS: NOT CARRIED",
             "messages": f"DATALINK RX: {comms['datalink']['packets_received']}" if comms else "DATALINK: NO DATA"}
    numbers = {"signal": comms["radio"]["signal_strength"] / 100.0 if comms else 0.0}
    return {"tactical": tactical, "system_status": system_status, "rows": rows, "texts": texts, "numbers": numbers,
            "terrain": _terrain(radar)}


# ---- the frozen panels rebuilt -----------------------------------------------------------------------------------

# Per frozen method: the list assignments replaced in source order (variable, rows key), the string constants
# replaced (text, texts key), the number assignments replaced (variable, numbers key).
MFD_REWRITES = {
    "draw_propulsion_panel": {"lists": [("params", "engine"), ("params", "fuel")]},
    "draw_avionics_panel": {"lists": [("params", "radar"), ("params", "weapons")]},
    "draw_weapons_status_panel": {"lists": [("weapons", "inventory")], "texts": {"SELECTED: AIM-120C": "selected"}},
    "draw_comm_channels": {"lists": [("channels", "channels")]},
    "draw_comm_status_panel": {"lists": [("status_items", "comm_status")], "texts": {"MESSAGES: 2 NEW": "messages"},
                               "numbers": {"signal_strength": "signal"}},
    "draw_navigation_data_panel": {"texts": {"INS: ALIGNED": "ins"}},
    "draw_targeting_display": {"texts": {"WEAPON: AIM-120C": "weapon"}},
}


class RewriteError(RuntimeError):
    """The frozen source no longer has what a rewrite replaces."""


class _Rewriter(ast.NodeTransformer):
    def __init__(self, spec):
        self.lists = list(spec.get("lists", ()))
        self.texts = dict(spec.get("texts", {}))
        self.numbers = dict(spec.get("numbers", {}))
        self.done = []

    @staticmethod
    def _call(method, key):
        return ast.Call(func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()), attr=method, ctx=ast.Load()),
                        args=[ast.Constant(value=key)], keywords=[])

    def visit_Assign(self, node):
        self.generic_visit(node)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, ast.List) and self.lists and self.lists[0][0] == name:
                node.value = self._call("_bus_rows", self.lists.pop(0)[1])
                self.done.append(name)
            elif isinstance(node.value, ast.Constant) and name in self.numbers:
                node.value = self._call("_bus_number", self.numbers.pop(name))
                self.done.append(name)
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value in self.texts:
            self.done.append(node.value)
            return self._call("_bus_text", self.texts.pop(node.value))
        return node


def rewrite_methods(cls, rewrites):
    """The frozen methods of `cls` named in `rewrites`, rebuilt from its source with the replacements made, as
    functions in a copy of the frozen module's globals. Raises RewriteError when any replacement is not found once."""
    module = inspect.getmodule(cls)
    filename = inspect.getsourcefile(cls)
    with open(filename, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls.__name__)
    functions = {n.name: n for n in class_node.body if isinstance(n, ast.FunctionDef)}
    namespace = dict(vars(module))
    out = {}
    for name, spec in rewrites.items():
        node = functions.get(name)
        if node is None:
            raise RewriteError(f"{cls.__name__}.{name} is gone from {filename}")
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in ("super", "__class__"):
                raise RewriteError(f"{cls.__name__}.{name} uses {inner.id}(): it cannot be rebuilt outside its class")
        rewriter = _Rewriter(spec)
        node = rewriter.visit(node)
        if rewriter.lists or rewriter.texts or rewriter.numbers:
            raise RewriteError(f"{cls.__name__}.{name}: not found in the frozen source: "
                               f"{rewriter.lists or ''} {list(rewriter.texts) or ''} {list(rewriter.numbers) or ''}")
        ast.fix_missing_locations(node)
        exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
        out[name] = namespace[name]
    return out


# ---- the displays ------------------------------------------------------------------------------------------------

def _holographic_pfd_class():
    from FMOFP.Interfaces.userInterface.displays.holographic_pfd import HolographicPFD
    return HolographicPFD


def _holographic_mfd_class():
    from FMOFP.Interfaces.userInterface.displays.holographic_mfd import HolographicMFD
    return HolographicMFD


_classes = {}


def bus_holographic_pfd_class():
    """BusHolographicPFD, built on first need (the frozen module imports Qt and the display tree)."""
    if "pfd" in _classes:
        return _classes["pfd"]
    from PyQt6.QtCore import QRectF
    from FMOFP.Interfaces.userInterface.displays.data_validity import draw_invalid_overlay
    base = _holographic_pfd_class()

    class BusHolographicPFD(base):
        """The holographic PFD with the FMS's numbers: crossed out whenever they are missing or stale."""
        PROVIDES_FLIGHT_DATA = True

        def __init__(self, flight_feed, systems_feed, parent=None):
            super().__init__(parent=parent)
            self.flight_feed = flight_feed
            self.systems_feed = systems_feed
            self.picture_valid = False
            self.flight_mode = "NO FMS DATA"
            self.lighting_mode = None
            self.apply_bus()

        def apply_bus(self):
            picture = pfd_picture(self.flight_feed, self.systems_feed)
            for name in ("altitude", "vertical_speed", "airspeed", "mach", "heading", "pitch", "roll", "g_force",
                         "aoa", "energy_state", "flight_mode"):
                setattr(self, name, picture[name])
            # No autopilot target reaches the PFD: the bugs sit on the present value, where the frozen tapes hide them.
            self.target_altitude = self.altitude
            self.target_airspeed = self.airspeed
            self.tactical_data.update(picture["tactical"])
            self.picture_valid = picture["valid"]
            self.update()
            return picture

        def set_mode(self, mode):
            """The bus's day, night and NVG modes: the holographic displays have none; the request is kept."""
            self.lighting_mode = mode

        def draw_flight_mode_indicator(self, painter):
            from PyQt6.QtCore import Qt
            rect = QRectF(self.width() / 2 - 100, 10, 200, 20)
            self._visual_effects.draw_enhanced_text(painter, rect, Qt.AlignmentFlag.AlignCenter,
                                                    f"FMS {self.flight_mode}", glow=True,
                                                    glow_color=self._theme_manager.get_color("data_primary"))

        def _draw_system_status(self, painter, rect):
            """The frozen corner said SYS OK whatever the systems did: here, whether the FMS's data is live."""
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QColor
            painter.fillRect(rect, QColor(self._theme_manager.get_color("overlay_background")))
            self._visual_effects.draw_angular_frame(painter, rect, color=self._theme_manager.get_color("hud"),
                                                    corner_style="angular", glow=False)
            ok = self.picture_valid
            self._visual_effects.draw_enhanced_text(
                painter, rect.adjusted(5, 5, -5, -5), Qt.AlignmentFlag.AlignCenter, "FMS OK" if ok else "NO FMS",
                glow=True, glow_color=self._theme_manager.get_color("system_normal" if ok else "warning"))

        def paint_display(self, painter):
            super().paint_display(painter)
            if not self.picture_valid:
                draw_invalid_overlay(painter, QRectF(self.rect()), "NO FMS DATA")

    _classes["pfd"] = BusHolographicPFD
    return BusHolographicPFD


def bus_holographic_mfd_class():
    """BusHolographicMFD, built on first need, with the rewritten panel methods."""
    if "mfd" in _classes:
        return _classes["mfd"]
    from PyQt6.QtCore import QRectF, Qt
    from FMOFP.Interfaces.userInterface.displays.data_validity import draw_invalid_overlay
    base = _holographic_mfd_class()
    rebuilt = rewrite_methods(base, MFD_REWRITES)

    class BusHolographicMFD(base):
        """The holographic MFD with the bus's tracks, route, engine, fuel, stores and comms."""

        def __init__(self, systems_feed, radar_feed=None, parent=None):
            super().__init__(parent=parent)
            self.systems_feed = systems_feed
            self.radar_feed = radar_feed
            self.lighting_mode = None
            self.bus = None
            self.apply_bus()

        def apply_bus(self):
            self.bus = mfd_picture(self.systems_feed, self.radar_feed)
            self.tactical_data = self.bus["tactical"]
            self.system_status = self.bus["system_status"]
            if self.bus["terrain"] is not None:
                self.terrain_data = self.bus["terrain"]
            self.update()
            return self.bus

        def _bus_rows(self, key):
            return self.bus["rows"][key]

        def _bus_text(self, key):
            return self.bus["texts"][key]

        def _bus_number(self, key):
            return self.bus["numbers"][key]

        def set_mode(self, mode):
            """The bus's day, night and NVG modes: the holographic displays have none (their display_mode is the
            page); the request is kept."""
            self.lighting_mode = mode

        def draw_3d_terrain(self, painter, rect):
            super().draw_3d_terrain(painter, rect)
            if self.bus is None or self.bus["terrain"] is None:
                draw_invalid_overlay(painter, rect, "NO TERRAIN DATA")

        def draw_radar_display(self, painter):
            """The frozen page embedded a holographic weather display that nothing feeds (and emptied its data at
            every repaint): the page says so. The radar window draws the weather."""
            self._exclusive_mode_active = True
            rect = QRectF(10, 10, self.width() - 20, self.height() - 60)
            self._visual_effects.draw_angular_frame(painter, rect, color=self._theme_manager.get_color("hud"),
                                                    corner_style="angular", glow=True, depth=0.1)
            self.draw_holographic_text(painter, QRectF(rect.x() + 10, rect.y() + 10, rect.width() - 20, 30),
                                       Qt.AlignmentFlag.AlignCenter, "WEATHER RADAR", depth=0.2, color_name="hud")
            draw_invalid_overlay(painter, rect.adjusted(20, 60, -20, -40), "NOT FED: SEE THE RADAR WINDOW")

    for name, function in rebuilt.items():
        setattr(BusHolographicMFD, name, function)
    _classes["mfd"] = BusHolographicMFD
    return BusHolographicMFD
