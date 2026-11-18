"""The stores management terminal against the frozen sms.py, through fmofp_stores_tool.

The frozen StoresManagementDisplay had no armament system behind it: its stations were _build_default_loadout(),
its master arm followed the FMS's weapons state in _poll_data, and it computed the load (_total_weight_kg) and the
armed count (_armed_count) from the table. Those three are what the C++ ports; here they run on a stand-in `self`
beside the tool. The starting table is compared station for station; the master arm for every weapons state and for
an FMS that says nothing; and the two sums over the tables a random run of the tool's commands leaves (select, arm,
safe, the modes, release, jettison: new behaviour, held by the unit tests), each copied into the frozen display's own
station objects. The commands themselves have no Python to compare with (ICD README section 2).

Needs FMOFP_STORES_TOOL (CI sets it).
"""

import os
import random
import subprocess
import sys
import unittest
from types import SimpleNamespace

from fmofp_bus.tests._support import binary_env, needs
from fmofp_display.systems_feed import STORE_KINDS

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)

KIND_OF_NAME = {name: kind for kind, (name, _, _) in STORE_KINDS.items()}
WEAPONS = {"SAFE": 0, "ARMED": 1, "READY": 2}
RUNS = 60


def sms_module():
    import FMOFP.Interfaces.userInterface.displays.sms as sms
    return sms


@needs("FMOFP_STORES_TOOL")
class StoresOracleTest(unittest.TestCase):
    def run_tool(self, lines):
        result = subprocess.run([os.environ["FMOFP_STORES_TOOL"]], input="\n".join(lines) + "\n", capture_output=True,
                                text=True, timeout=120, env=binary_env())
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.splitlines()

    def test_the_starting_table_is_the_default_loadout(self):
        out = self.run_tool(["table", "sums"])
        frozen = sms_module()._build_default_loadout()
        self.assertEqual(11, len(frozen))
        for i, (station, line) in enumerate(zip(frozen, out[:11])):
            kind, state, qty = line.split()
            self.assertEqual((KIND_OF_NAME[station.store.name], station.store.state, station.store.qty),
                             (kind, state, int(qty)), f"station {i + 1}")
            name, weight_kg, store_type = STORE_KINDS[kind]
            self.assertEqual((name, weight_kg, store_type),
                             (station.store.name, station.store.weight_kg, station.store.store_type))
        weight, armed = out[11].split()
        fake = SimpleNamespace(_stations=frozen)
        display = sms_module().StoresManagementDisplay
        self.assertEqual((display._total_weight_kg(fake), display._armed_count(fake)), (float(weight), int(armed)))

    def test_the_master_arm_is_poll_data_s(self):
        display = sms_module().StoresManagementDisplay
        cases = [None] + list(WEAPONS)
        out = self.run_tool([f"arm {'none' if w is None else WEAPONS[w]}" for w in cases])
        for weapons, answer in zip(cases, out):
            tactical = {"mode": "NORMAL", "profile_limits": {}}
            if weapons is not None:
                tactical["tactical_systems"] = {"countermeasures": "STANDBY", "weapons": weapons, "stealth_mode": "OFF"}
            fake = SimpleNamespace(_fms=object(), _fms_control=SimpleNamespace(get_tactical_status=lambda t=tactical: t),
                                   _lazy_fms=lambda: None, _lock=sms_module().threading.Lock(),
                                   _stations=[], _cntm="STANDBY", _stealth="OFF", _flight_mode="NORMAL",
                                   _master_arm="SAFE", _safe_update=lambda: None)
            display._poll_data(fake)
            self.assertEqual(fake._master_arm, answer, weapons)

    def test_the_sums_over_the_tables_the_commands_leave(self):
        rng = random.Random(28)
        sms = sms_module()
        lines = []
        for _ in range(RUNS):
            lines.append("reset")
            lines.append(f"arm {rng.choice((0, 1, 1, 1, 2))}")
            for _ in range(rng.randint(1, 16)):
                # Mostly the commands that move stores (arm, release, the release mode), on real stations; now and
                # then a refusal (a station out of range, NONE) and, rarely, a jettison.
                command = rng.choice((4, 4, 6, 6, 6, 2, 5, 1, 3, 0) + ((7,) if rng.random() < 0.05 else ()))
                station = rng.randint(1, 11) if rng.random() < 0.9 else rng.choice((0, 12))
                lines.append(f"cmd {command} {station} {rng.randint(0, 2)} {rng.randint(0, 4)}")
                lines.append("table")
                lines.append("sums")
        out = iter(self.run_tool(lines))
        checked = 0
        weights = set()
        for line in lines:
            if line.startswith(("reset", "arm", "cmd")):
                next(out)
                continue
            if line == "table":
                table = [next(out).split() for _ in range(11)]
                continue
            weight, armed = next(out).split()
            stations = sms._build_default_loadout()
            for station, (kind, state, qty) in zip(stations, table):
                name, weight_kg, store_type = STORE_KINDS[kind]
                station.store = sms._Store(name, weight_kg, int(qty), state, store_type)
            fake = SimpleNamespace(_stations=stations)
            self.assertEqual(sms.StoresManagementDisplay._total_weight_kg(fake), float(weight), table)
            self.assertEqual(sms.StoresManagementDisplay._armed_count(fake), int(armed), table)
            weights.add(float(weight))
            checked += 1
        self.assertGreater(checked, RUNS)
        self.assertGreater(len(weights), 10, "the runs reached many different tables")
        self.assertIn(0.0, weights, "a jettison among them")


if __name__ == "__main__":
    unittest.main()
