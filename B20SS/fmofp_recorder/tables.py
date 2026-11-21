"""The tables upstream's Python services wrote, rebuilt from what the bus carries.

Each `Table` names its database file (the one `dbConfig.xml` gave the service's system), its columns (the
service's own `create_table` fields, as written) and how a row is made. The rows are the services' own
dictionaries: where a display feed already rebuilds a service's `get_data()` from the bus (held to the frozen
Python by the feed tests), the recorder uses that feed. A table is written at the service's own rate, counted in bus
frames (50 a second), and only from data the bus vouches for: where the Python wrote its defaults while it had no
reading, the recorder writes nothing (ICD README section 2).

Not here, because upstream never wrote them: `satcom_data`, `radio_data` and `datalink_data` (their classes asked
`dbConfig.xml` for a system, `comms`, it does not configure, and nothing built them), and the tables of the old
messaging's request services (the radar's precipitation, VIL and echo-top data, the FMS's attitude, navigation,
tactical and velocity data, the display commands), deleted in unit 29.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import Ssm

FRAMES_PER_SECOND = 50

# dbConfig.xml: the services' systems and their files.
COMMUNICATION_DB = "communication_data.db"   # system "radio" (CommsService)
DEFAULT_DB = "default.db"                    # system "default" (DefensiveService, FuelSystem)
FLIGHT_CONTROL_DB = "flight_control_data.db"  # system "flight_control_computer" (the FCC, the ECU, the surfaces)
MISSION_DB = "mission_data.db"               # system "mission_management_system"
POWER_DB = "power_data.db"                   # system "power_management_system"

# powerManagementSystem.monitor()'s pms_data, in its order: what the table stored (the feed adds component states).
PMS_KEYS = ("main_battery_charge", "emergency_battery_charge", "apu_battery_charge", "generator_output",
            "total_power_consumption", "power_balance", "main_bus_voltage", "aux_bus_voltage", "generator_frequency",
            "power_factor", "coolant_temp_c", "cabin_temp_c")
# FlightSurfaceService._all's names, FSF_POSITIONS's fields.
SURFACES = ("aileron_l", "aileron_r", "elevator_l", "elevator_r", "rudder", "flap_l", "flap_r", "slat_l", "slat_r",
            "speedbrake")
# fuelControl.setup_aircraft: the tanks (capacity, kg), the engines (max thrust) and the lines (transfer rate).
TANKS = (("Main Left", 10000.0), ("Main Right", 10000.0), ("Center", 20000.0))
ENGINES = (("Engine 1", 50000.0), ("Engine 2", 50000.0))
FUEL_LINES = (("Main Left", "Engine 1", 100.0), ("Main Right", "Engine 2", 100.0), ("Center", "Engine 1", 50.0),
              ("Center", "Engine 2", 50.0))
# MissionService's starting position (until the FMS reports a fix that is not zero).
MISSION_START_POSITION = {"lat": 35.4147, "lon": -97.3866, "alt_ft": 1290.6}


@dataclass
class Row:
    """One SQL statement's worth: an INSERT (or an INSERT OR REPLACE, or an UPDATE with `where`)."""
    table: str
    values: Dict[str, object]
    replace: bool = False
    where: Optional[Dict[str, object]] = None


@dataclass
class Table:
    name: str
    database: str
    columns: Dict[str, str]
    period_frames: int                 # 0: every frame (event tables decide for themselves)
    rows: Callable                     # rows(recorder, now) -> list of Row
    writer: str = ""                   # the Python that wrote it, for the documents and the prompt


def _valid(ssm):
    return ssm == Ssm.NORMAL


def comms_rows(rec, now):
    """CommsService._persist: a row each for the radio, the satcom and the data link, once a second."""
    data = rec.feed.comms_data()
    if not data:
        return []
    return [Row("comms_data", {"timestamp": now, "subsystem": name, "data": json.dumps(data[name])})
            for name in ("radio", "satcom", "datalink")]


def ecu_rows(rec, now):
    """EngineControlUnit._persist: its snapshot, twice a second (engine 1: the ECU modelled one engine)."""
    data = rec.feed.engine_data()
    if not data:
        return []
    data = dict(data, timestamp=now)
    return [Row("ecu_data", {"timestamp": now, "data": json.dumps(data)})]


def fcs_rows(rec, now):
    """FlightControlComputer._persist: the flight state, ten times a second. That computer was the random walk the
    plant now is, so its snapshot is the plant's PLANT_SENSORS."""
    sensors = rec.view.fresh(m.PlantSensors, rec.stale_after_s)
    if sensors is None:
        return []
    s = sensors
    data = {"altitude": round(s.altitude, 2), "speed": round(s.airspeed, 2), "heading": round(s.heading, 2),
            "pitch": round(s.pitch, 2), "roll": round(s.roll, 2), "vertical_speed": round(s.vertical_speed, 2),
            "angle_of_attack": round(s.angle_of_attack, 2), "g_force": round(s.g_force, 3), "flaps": s.flaps,
            "landing_gear": s.gear.name.lower(), "timestamp": now}
    return [Row("fcs_data", {"timestamp": now, "data": json.dumps(data)})]


def surface_rows(rec, now):
    """FlightSurfaceService._persist: every surface's position, rounded to 0.01 degree. The Python wrote 50 times a
    second; FSF_POSITIONS is a 10 Hz message, so the recorder writes each new one (ICD README section 2)."""
    positions = rec.view.fresh(m.FsfPositions, rec.stale_after_s)
    if positions is None:
        return []
    data = {name: round(getattr(positions, name), 2) for name in SURFACES}
    return [Row("surface_data", {"timestamp": now, "data": json.dumps(data)})]


def mission_rows(rec, now):
    """MissionService._persist: the phase and {position, waypoints, targets, threats}, once a second. The waypoints
    and targets are the mission computer's route and targets (the Python's service kept a list of its own beside
    them, which the bus does not carry); the threats are the service's list, which nothing filled."""
    data = rec.feed.mission_data()
    if "phase" not in data:
        return []
    flight = rec.view.fresh(m.BcastFmsFlightData, rec.stale_after_s)
    if flight is not None and _valid(flight.payload.position_ssm):
        f = flight.payload
        if f.latitude != 0 or f.longitude != 0:   # the Python's has_real_fix
            rec.mission_position = {"lat": f.latitude, "lon": f.longitude,
                                    "alt_ft": f.altitude if _valid(f.altitude_ssm) else
                                    rec.mission_position["alt_ft"]}
    snapshot = {"position": rec.mission_position, "waypoints": data.get("waypoints", []),
                "targets": data.get("targets", []), "threats": []}
    return [Row("mission_data", {"timestamp": now, "phase": data["phase"], "data": json.dumps(snapshot)})]


def pms_rows(rec, now):
    """PowerManagementSystem.update: monitor()'s snapshot, once a second, with no timestamp column."""
    data = rec.feed.power_data()
    if not data:
        return []
    return [Row("pms_data", {"data": json.dumps({key: data[key] for key in PMS_KEYS})})]


def defensive_rows(rec, now):
    """DefensiveService._log_event, on each event: an automatic flare salvo ({released, threats}), manual chaff and
    manual flares ({released}), an ECM mode change ({mode}). Read from DEF_STATUS's counters as they move; a mode
    set to the one already set, which the Python also logged, leaves nothing on the bus to see."""
    status = rec.view.fresh(m.DefStatus, rec.stale_after_s)
    if status is None:
        return []
    s = status
    last = rec.defensive_last
    rec.defensive_last = (s.chaff_released, s.flares_released, s.auto_salvos, s.ecm_mode)
    if last is None:
        return []
    chaff, flares, salvos, ecm = last
    rows = []
    auto = 0
    if s.auto_salvos != salvos:
        auto = min((s.auto_salvos - salvos) % 256 * 2, (s.flares_released - flares) % 256)
        rows.append(("auto_flare", {"released": auto, "threats": s.high_priority_count}))
    manual = (s.flares_released - flares) % 256 - auto
    if manual > 0:
        rows.append(("manual_flare", {"released": manual}))
    if s.chaff_released != chaff:
        rows.append(("manual_chaff", {"released": (s.chaff_released - chaff) % 256}))
    if s.ecm_mode != ecm:
        rows.append(("ecm_mode_change", {"mode": s.ecm_mode.name}))
    return [Row("defensive_events", {"timestamp": now, "event": event, "data": json.dumps(data)})
            for event, data in rows]


def fuel_rows(rec, now):
    """FuelSystem: setup_aircraft's tanks, engines and lines once (INSERT OR REPLACE for the tanks and engines, as
    the Python wrote them), then each tank's level and each engine's thrust (max_thrust x percent / 100, Engine.
    set_thrust) as the engine computer reports them, once a second."""
    fuel = rec.view.fresh(m.BcastEngFuelStatus, rec.stale_after_s)
    if fuel is None:
        return []
    rows = []
    if not rec.fuel_set_up:
        rec.fuel_set_up = True
        rows += [Row("fuel_tanks", {"name": n, "capacity": c, "current_level": c}, replace=True) for n, c in TANKS]
        rows += [Row("engines", {"name": n, "max_thrust": t}, replace=True) for n, t in ENGINES]
        rows += [Row("fuel_lines", {"tank_name": t, "engine_name": e, "transfer_rate": r}) for t, e, r in FUEL_LINES]
    f = fuel.payload
    for name, level in (("Main Left", f.main_left), ("Main Right", f.main_right), ("Center", f.center)):
        rows.append(Row("fuel_tanks", {"current_level": level}, where={"name": name}))
    engine = rec.view.fresh(m.BcastEngEngineStatus, rec.stale_after_s)
    if engine is not None:
        e = engine.payload
        for (name, max_thrust), thrust, ssm in ((ENGINES[0], e.thrust_1, e.engine_1_ssm),
                                                (ENGINES[1], e.thrust_2, e.engine_2_ssm)):
            if _valid(ssm):
                rows.append(Row("engines", {"current_thrust": max_thrust * (thrust / 100)}, where={"name": name}))
    return rows


TABLES: List[Table] = [
    Table("comms_data", COMMUNICATION_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "subsystem": "TEXT NOT NULL",
           "data": "TEXT NOT NULL"}, FRAMES_PER_SECOND, comms_rows, "Systems/comms/messaging_service.py"),
    Table("defensive_events", DEFAULT_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "event": "TEXT NOT NULL",
           "data": "TEXT NOT NULL"}, 0, defensive_rows, "Systems/defensiveSys/defensiveService.py"),
    Table("fuel_tanks", DEFAULT_DB, {"name": "TEXT PRIMARY KEY", "capacity": "REAL", "current_level": "REAL"},
          FRAMES_PER_SECOND, fuel_rows, "Systems/engineManagement/fuelManagement/fuelControl.py"),
    Table("engines", DEFAULT_DB, {"name": "TEXT PRIMARY KEY", "max_thrust": "REAL", "current_thrust": "REAL"},
          0, None, "Systems/engineManagement/fuelManagement/fuelControl.py"),
    Table("fuel_lines", DEFAULT_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "tank_name": "TEXT", "engine_name": "TEXT",
           "transfer_rate": "REAL"}, 0, None, "Systems/engineManagement/fuelManagement/fuelControl.py"),
    Table("ecu_data", FLIGHT_CONTROL_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "data": "TEXT NOT NULL"},
          FRAMES_PER_SECOND // 2, ecu_rows, "Systems/engineManagement/ecu/engineControlUnit.py"),
    Table("fcs_data", FLIGHT_CONTROL_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "data": "TEXT NOT NULL"},
          FRAMES_PER_SECOND // 10, fcs_rows, "Systems/flightControlSys/flightControlComputer/flightControlComputer.py"),
    Table("surface_data", FLIGHT_CONTROL_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "data": "TEXT NOT NULL"},
          FRAMES_PER_SECOND // 10, surface_rows, "Systems/flightSurfaces/flightSurfaceService.py"),
    Table("mission_data", MISSION_DB,
          {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "timestamp": "REAL NOT NULL", "phase": "TEXT NOT NULL",
           "data": "TEXT NOT NULL"}, FRAMES_PER_SECOND, mission_rows, "Systems/missionPlanning/missionService.py"),
    Table("pms_data", POWER_DB, {"id": "INTEGER PRIMARY KEY", "data": "TEXT"}, FRAMES_PER_SECOND, pms_rows,
          "Systems/powerManagement/elec/powerManagementSystem.py"),
]

TABLE_BY_NAME = {t.name: t for t in TABLES}
DATABASES = sorted({t.database for t in TABLES})


def create_sql(table):
    """SystemDatabase.create_table's statement."""
    fields = ", ".join(f'"{k}" {v}' for k, v in table.columns.items())
    return f'CREATE TABLE IF NOT EXISTS "{table.name}" ({fields})'


def row_sql(row):
    """The statement and its parameters: insert_into_table's INSERT, fuelControl's INSERT OR REPLACE, or
    update_table's UPDATE ... WHERE."""
    if row.where is not None:
        sets = ", ".join(f'"{k}" = ?' for k in row.values)
        conds = " AND ".join(f'"{k}" = ?' for k in row.where)
        return (f'UPDATE "{row.table}" SET {sets} WHERE {conds}',
                tuple(row.values.values()) + tuple(row.where.values()))
    verb = "INSERT OR REPLACE" if row.replace else "INSERT"
    fields = ", ".join(f'"{k}"' for k in row.values)
    marks = ", ".join("?" for _ in row.values)
    return f'{verb} INTO "{row.table}" ({fields}) VALUES ({marks})', tuple(row.values.values())
