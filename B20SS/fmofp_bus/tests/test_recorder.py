"""The data recorder against upstream's Python: the tables, their columns and files, and the rows.

The frozen services' own `create_table` calls (read from their source with `ast`) are the schemas the recorder must
create, column for column and in order; `dbConfig.xml` says which file each service's system wrote to. The rows are
made from a fake bus picture frame by frame: the rates in bus frames, the defensive events from the counters, the
fuel system's setup and updates, power's `pms_data` keys (the frozen `monitor()`'s dictionary). The prompt's `tables`
and `table` read the files back.
"""

import ast
import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import EcmMode, GearPosition, MissionPhase, Ssm, TerminalState
from fmofp_recorder import recorder as r
from fmofp_recorder import tables as t
from fmofp_recorder.view import producer_block, producer_class

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FROZEN = os.path.join(B20SS, "FMOFP")

# The Python that wrote each table, and the system it asked dbConfig.xml for.
WRITERS = {
    "comms_data": ("Systems/comms/messaging_service.py", "radio"),
    "defensive_events": ("Systems/defensiveSys/defensiveService.py", "default"),
    "fuel_tanks": ("Systems/engineManagement/fuelManagement/fuelControl.py", "default"),
    "engines": ("Systems/engineManagement/fuelManagement/fuelControl.py", "default"),
    "fuel_lines": ("Systems/engineManagement/fuelManagement/fuelControl.py", "default"),
    "ecu_data": ("Systems/engineManagement/ecu/engineControlUnit.py", "flight_control_computer"),
    "fcs_data": ("Systems/flightControlSys/flightControlComputer/flightControlComputer.py", "flight_control_computer"),
    "surface_data": ("Systems/flightSurfaces/flightSurfaceService.py", "flight_control_computer"),
    "mission_data": ("Systems/missionPlanning/missionService.py", "mission_management_system"),
    "pms_data": ("Systems/powerManagement/elec/powerManagementSystem.py", "power_management_system"),
}


def frozen_source(rel):
    with open(os.path.join(FROZEN, rel), encoding="utf-8") as f:
        return f.read()


def frozen_tree(rel):
    return ast.parse(frozen_source(rel))


def frozen_schemas(rel):
    """{table: {column: type}} of every create_table(name, {...}) in a frozen file; a name or a dict held in a local
    variable (powerManagementSystem's `table_name` and `field_data_dict`) is followed to its assignment."""
    tree = frozen_tree(rel)
    assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                assigned[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    out = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_table"
                and len(node.args) == 2):
            name, fields = node.args
            name = assigned.get(name.id) if isinstance(name, ast.Name) else ast.literal_eval(name)
            fields = assigned.get(fields.id) if isinstance(fields, ast.Name) else ast.literal_eval(fields)
            out[name] = fields
    return out


def db_files():
    """dbConfig.xml: system name -> database file."""
    root = ET.parse(os.path.join(FROZEN, "dbConfig.xml")).getroot()
    return {s.get("name"): s.get("db_name") for s in root.iter("system") if s.get("name")}


class SchemaTest(unittest.TestCase):
    def test_every_table_is_the_frozen_create_table_in_the_frozen_file(self):
        files = db_files()
        self.assertEqual(set(WRITERS), set(t.TABLE_BY_NAME), "the recorder writes exactly the tables upstream wrote")
        for name, (rel, system) in WRITERS.items():
            table = t.TABLE_BY_NAME[name]
            self.assertEqual(list(frozen_schemas(rel)[name].items()), list(table.columns.items()), name)
            self.assertEqual(files[system], table.database, name)
            self.assertIn(f"get_system_db('{system}')", frozen_source(rel), name)

    def test_the_tables_upstream_never_wrote(self):
        """satCom, radio and data_Link asked for a system dbConfig.xml does not configure: get_system_db raised in
        their constructors, so their tables never existed (and radio and data_Link called create_table with four
        arguments besides). The recorder writes none of them."""
        self.assertNotIn("comms", db_files())
        for rel in ("Systems/comms/satcom/satCom.py", "Systems/comms/radios/radio.py",
                    "Systems/comms/dataLink/data_Link.py"):
            self.assertIn("get_system_db('comms')", frozen_source(rel))
        for name in ("satcom_data", "radio_data", "datalink_data"):
            self.assertNotIn(name, t.TABLE_BY_NAME)

    def test_the_rows_carry_the_frozen_dictionaries_keys(self):
        tree = frozen_tree("Systems/powerManagement/elec/powerManagementSystem.py")
        keys = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "pms_data" and isinstance(node.value, ast.Dict) and node.value.keys):
                keys = tuple(k.value for k in node.value.keys)
        self.assertEqual(keys, t.PMS_KEYS)
        tree = frozen_tree("Systems/flightControlSys/flightControlComputer/flightControlComputer.py")
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "_fcs_data" and isinstance(node.value, ast.Dict)):
                self.assertEqual(["altitude", "speed", "heading", "pitch", "roll", "vertical_speed",
                                  "angle_of_attack", "g_force", "flaps", "landing_gear", "timestamp"],
                                 [k.value for k in node.value.keys])

    def test_a_consumer_class_reads_its_producer(self):
        self.assertIs(m.PwrStatus, producer_class(m.EicasPwrStatus))
        self.assertIs(m.FmsFlightData, producer_class(m.BcastFmsFlightData))
        self.assertIs(m.PlantSensors, producer_class(m.PlantSensors))
        from fmofp_bus.icd import blocks as b
        self.assertIs(b.MsnPlan, producer_block(b.BcastMsnPlan))


class FakeView:
    """The calls the recorder and the feeds make of a RecordingView, over messages the test sets."""

    def __init__(self):
        self.messages = {}

    def put(self, message):
        """A producer's message, or a consumer's copy (stored as its producer's, as the monitor sees it)."""
        if hasattr(message, "payload"):
            self.messages[producer_class(type(message))] = message.payload
        else:
            self.messages[type(message)] = message

    def fresh(self, cls, stale_after_s):
        producer = producer_class(cls)
        message = self.messages.get(producer)
        if message is None:
            return None
        return SimpleNamespace(payload=message) if producer is not cls else message

    def latest_block(self, cls):
        return None, None, None


def sensors():
    return m.PlantSensors(altitude_ssm=Ssm.NORMAL, airspeed_ssm=Ssm.NORMAL, pitch_ssm=Ssm.NORMAL, roll_ssm=Ssm.NORMAL,
                          heading_ssm=Ssm.NORMAL, vertical_speed_ssm=Ssm.NORMAL, aoa_ssm=Ssm.NORMAL, g_ssm=Ssm.NORMAL,
                          flaps_ssm=Ssm.NORMAL, gear=GearPosition.DOWN, altitude=5000.0, airspeed=450.0,
                          vertical_speed=-120.0, pitch=2.5, roll=-3.25, heading=90.0, angle_of_attack=4.0,
                          g_force=1.125, flaps=15.0)


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="fmofp_recorder_")
        self.view = FakeView()
        self.clock = [1000.0]
        self.rec = r.Recorder(self.view, self.out, wall_clock=lambda: self.clock[0])
        self.rec.open()

    def tearDown(self):
        self.rec.close()
        shutil.rmtree(self.out, ignore_errors=True)

    def run_frames(self, first, last):
        for frame in range(first, last):
            self.clock[0] += 0.02
            self.rec.step(frame)

    def rows(self, table):
        return r.read_table(table, 10000, self.out)[1]

    def test_nothing_heard_nothing_written_and_every_file_made(self):
        self.run_frames(0, 100)
        self.assertEqual({"comms_data", "defensive_events", "engines", "fuel_lines", "fuel_tanks", "ecu_data",
                          "fcs_data", "surface_data", "mission_data", "pms_data"},
                         {table for _, table, _ in r.list_tables(self.out)})
        self.assertEqual(sorted(t.DATABASES), sorted(name for name in os.listdir(self.out)))
        self.assertEqual(0, sum(self.rec.rows_written.values()))

    def test_the_rates_are_the_pythons_in_bus_frames(self):
        self.view.put(sensors())
        self.view.put(m.FsfPositions(aileron_l=1.234, speedbrake=30.0))
        self.run_frames(0, 100)
        self.assertEqual(20, len(self.rows("fcs_data")), "10 Hz: two seconds")
        self.assertEqual(20, len(self.rows("surface_data")), "each 10 Hz FSF_POSITIONS")
        fcs = json.loads(self.rows("fcs_data")[-1][2])
        self.assertEqual({"altitude": 5000.0, "speed": 450.0, "heading": 90.0, "pitch": 2.5, "roll": -3.25,
                          "vertical_speed": -120.0, "angle_of_attack": 4.0, "g_force": 1.125, "flaps": 15.0,
                          "landing_gear": "down"}, {k: v for k, v in fcs.items() if k != "timestamp"})
        surfaces = json.loads(self.rows("surface_data")[-1][2])
        self.assertEqual(list(t.SURFACES), list(surfaces))
        self.assertEqual((1.23, 30.0), (surfaces["aileron_l"], surfaces["speedbrake"]))

    def test_the_defensive_events_follow_the_counters(self):
        s = m.DefStatus(state=TerminalState.NORMAL, chaff_remaining=60, flares_remaining=30)
        self.view.put(s)
        self.run_frames(0, 5)
        self.view.put(m.DefStatus(state=TerminalState.NORMAL, chaff_released=4, ecm_mode=EcmMode.ACTIVE))
        self.run_frames(5, 6)
        self.view.put(m.DefStatus(state=TerminalState.NORMAL, chaff_released=4, ecm_mode=EcmMode.ACTIVE,
                                  auto_salvos=1, flares_released=2, high_priority_count=1))
        self.run_frames(6, 7)
        self.view.put(m.DefStatus(state=TerminalState.NORMAL, chaff_released=4, ecm_mode=EcmMode.ACTIVE,
                                  auto_salvos=1, flares_released=3, high_priority_count=1))
        self.run_frames(7, 20)
        events = [(row[2], json.loads(row[3])) for row in self.rows("defensive_events")]
        self.assertEqual([("manual_chaff", {"released": 4}), ("ecm_mode_change", {"mode": "ACTIVE"}),
                          ("auto_flare", {"released": 2, "threats": 1}), ("manual_flare", {"released": 1})], events)

    def test_the_fuel_system_sets_up_once_and_follows_the_tanks(self):
        self.view.put(m.BcastEngFuelStatus(payload=m.EngFuelStatus(main_left=9000.0, main_right=8000.0,
                                                                   center=19000.0, total=36000.0)))
        self.view.put(m.BcastEngEngineStatus(payload=m.EngEngineStatus(engine_1_ssm=Ssm.NORMAL, thrust_1=80.0,
                                                                       engine_2_ssm=Ssm.NO_COMPUTED_DATA)))
        self.run_frames(0, 120)
        self.assertEqual([("Center", 20000.0, 19000.0), ("Main Left", 10000.0, 9000.0),
                          ("Main Right", 10000.0, 8000.0)], sorted(self.rows("fuel_tanks")))
        self.assertEqual([("Engine 1", 50000.0, 40000.0), ("Engine 2", 50000.0, None)], sorted(self.rows("engines")))
        self.assertEqual([(1, "Main Left", "Engine 1", 100.0), (2, "Main Right", "Engine 2", 100.0),
                          (3, "Center", "Engine 1", 50.0), (4, "Center", "Engine 2", 50.0)], self.rows("fuel_lines"))

    def test_power_comms_engine_and_mission_rows(self):
        self.view.put(m.EicasPwrStatus(payload=m.PwrStatus(state=TerminalState.NORMAL, electrical_valid=True,
                                                           generator_output=220.0, main_bus_voltage=115.5)))
        self.view.put(m.MfdComLinkStatus(payload=m.ComLinkStatus(frequency=243.0)))
        self.view.put(m.BcastEngEngineStatus(payload=m.EngEngineStatus(engine_1_ssm=Ssm.NORMAL, n1_1=82.0)))
        self.view.put(m.BcastMsnStatus(payload=m.MsnStatus(state=TerminalState.NORMAL, phase=MissionPhase.INGRESS)))
        self.view.put(m.BcastFmsFlightData(payload=m.FmsFlightData(position_ssm=Ssm.NORMAL, altitude_ssm=Ssm.NORMAL,
                                                                   latitude=1.5, longitude=2.5, altitude=5000.0)))
        self.run_frames(0, 100)
        pms = self.rows("pms_data")
        self.assertEqual(2, len(pms))
        self.assertEqual(list(t.PMS_KEYS), list(json.loads(pms[-1][1])))
        comms = self.rows("comms_data")
        self.assertEqual(["radio", "satcom", "datalink"] * 2, [row[2] for row in comms])
        self.assertEqual(243.0, json.loads(comms[0][3])["frequency"])
        self.assertEqual(4, len(self.rows("ecu_data")), "2 Hz")
        self.assertEqual(82.0, json.loads(self.rows("ecu_data")[-1][2])["n1_pct"])
        mission = self.rows("mission_data")[-1]
        self.assertEqual("INGRESS", mission[2])
        self.assertEqual({"position": {"lat": 1.5, "lon": 2.5, "alt_ft": 5000.0}, "waypoints": [], "targets": [],
                          "threats": []}, json.loads(mission[3]))

    def test_a_restarted_controller_and_the_read_back(self):
        self.view.put(sensors())
        self.run_frames(0, 10)
        self.run_frames(0, 10)   # the frame count starts over: the slots with it
        self.assertEqual(4, len(self.rows("fcs_data")))
        columns, rows = r.read_table("fcs_data", 3, self.out)
        self.assertEqual(["id", "timestamp", "data"], columns)
        self.assertEqual([2, 3, 4], [row[0] for row in rows])
        self.assertIsNone(r.read_table("no_such_table", 3, self.out))
        self.assertIn((t.FLIGHT_CONTROL_DB, "fcs_data", 4), r.list_tables(self.out))


class CliTablesTest(unittest.TestCase):
    def test_tables_and_table(self):
        from fmofp_cli.cli import DebugCli
        out_dir = tempfile.mkdtemp(prefix="fmofp_recorder_cli_")
        try:
            lines = []
            cli = DebugCli(SimpleNamespace(), SimpleNamespace(), out=lines.append, recorder_dir=out_dir)
            cli.execute("tables")
            self.assertIn("no recorded tables", lines[-1])
            view = FakeView()
            view.put(sensors())
            rec = r.Recorder(view, out_dir, wall_clock=lambda: 1000.0)
            rec.open()
            for frame in range(10):
                rec.step(frame)
            rec.close()
            lines.clear()
            cli.execute("tables")
            self.assertTrue(any("fcs_data" in line and "2 rows" in line for line in lines), lines)
            lines.clear()
            cli.execute("table fcs_data 1")
            self.assertEqual("  id | timestamp | data", lines[0])
            self.assertTrue(lines[1].startswith("  2 | 1000.0 | {"), lines)
            lines.clear()
            cli.execute("table nothing")
            self.assertIn("no recorded table 'nothing'", lines[0])
            lines.clear()
            cli.execute("table fcs_data x")
            self.assertIn("not a row count", lines[0])
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
