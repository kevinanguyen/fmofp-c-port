"""The plant's ESM intercepts: ESMSensor.detect's draws as the world, on PLANT_ESM. No sockets."""

import os
import random
import sys
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.status import Status
from fmofp_plant.esm import EsmWorld, MAX_SIGNALS
from fmofp_plant.plant import PlantModel

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)


class EsmWorldTest(unittest.TestCase):
    def test_a_set_has_up_to_five_signals_within_the_sensors_ranges(self):
        esm = EsmWorld(random.Random(3))
        self.assertEqual((0, []), (esm.epoch, esm.signals))
        counts = set()
        for n in range(1, 301):
            esm.step()
            self.assertEqual(n % 256, esm.epoch)
            self.assertLessEqual(len(esm.signals), MAX_SIGNALS)
            counts.add(len(esm.signals))
            for frequency, strength, bearing, range_nm in esm.signals:
                self.assertTrue(0.5e9 <= frequency < 40e9, frequency)
                self.assertTrue(-120.0 <= strength <= -20.0, strength)
                self.assertTrue(0.0 <= bearing < 360.0, bearing)
                self.assertTrue(5.0 <= range_nm <= 60.0, range_nm)
        self.assertEqual(set(range(MAX_SIGNALS + 1)), counts, "randint(0, 5): every count turns up in 300 sets")

    def test_the_signals_are_the_pythons_sensors_draws_in_its_order(self):
        """A sensor seeded like the world detects the same signals; the world's ranges come after each set."""
        from FMOFP.Systems.sensorManagement.passiveSensors.passiveSensors import PassiveSensorManager
        world = EsmWorld(random.Random(11))
        world.step()
        world.step()
        random.seed(11)
        psm = PassiveSensorManager()
        psm.activate_sensor("electronic_support_measures")
        first = psm.get_sensor_data("electronic_support_measures")
        for _ in first:
            random.uniform(5.0, 60.0)  # the ranges the world drew after its first set
        second = psm.get_sensor_data("electronic_support_measures")
        self.assertEqual([(s["frequency"], s["signal_strength"], s["bearing"]) for s in second],
                         [(f, s, b) for f, s, b, _ in world.signals])

    def test_the_message_round_trips_and_pads_the_unused_signals(self):
        world = EsmWorld(random.Random(5))
        sets = 0
        while sets < 20:
            world.step()
            sets += 1
            status, words = world.message().encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED))
            self.assertEqual(m.PlantEsm.WORDS, len(words))
            status, back = m.PlantEsm.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertEqual((world.epoch, len(world.signals)), (back.epoch, back.count))
            for i in range(1, MAX_SIGNALS + 1):
                frequency = getattr(back, f"frequency_{i}")
                bearing = getattr(back, f"bearing_{i}")
                range_nm = getattr(back, f"range_{i}")
                if i <= len(world.signals):
                    f, s, b, r = world.signals[i - 1]
                    self.assertAlmostEqual(f / 1e6, frequency, delta=0.0006, msg="kHz steps")
                    self.assertAlmostEqual(s, getattr(back, f"strength_{i}"), delta=0.06)
                    self.assertAlmostEqual(b, bearing, delta=0.006)
                    self.assertAlmostEqual(r, range_nm, delta=0.06)
                else:
                    self.assertEqual((0.0, 0.0, 0.0), (frequency, bearing, range_nm))

    def test_the_plant_carries_it_and_can_leave_it_out(self):
        model = PlantModel(seed=1, traffic=False, ground=False, weather=False)
        self.assertIsNotNone(model.esm)
        model.esm.step()
        self.assertEqual(1, model.esm_message().epoch)
        silent = PlantModel(seed=1, traffic=False, ground=False, weather=False, esm=False)
        self.assertIsNone(silent.esm)
        self.assertEqual(m.PlantEsm(), silent.esm_message())
        # Its own generator: the flight state of a seeded run is the same with or without the intercepts.
        with_esm = PlantModel(seed=9, traffic=False, ground=False, weather=False)
        without = PlantModel(seed=9, traffic=False, ground=False, weather=False, esm=False)
        for _ in range(20):
            with_esm.adjust()
            without.adjust()
        self.assertEqual(with_esm.altitude, without.altitude)
        self.assertEqual(with_esm.heading, without.heading)


if __name__ == "__main__":
    unittest.main()
