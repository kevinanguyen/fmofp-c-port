"""The plant's cabin, hydraulic and airframe readings: the world the four small utility terminals measure. No sockets.

The Python subsystems had no sensor sources (ECSControl's readings stayed None, HydraulicSystemController read a
constant 2800 psi, AirframeSystemManager had no caller of set_sensor_reading), so these are the plant's own: there
is no Python draw to compare with. Checked: the ranges, the epochs, the holds, the determinism, the messages' round
trips, and that the plant carries them and can leave them out without changing a seeded flight.
"""

import os
import random
import sys
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.status import Status
from fmofp_plant.plant import HOLDABLE, PlantModel
from fmofp_plant.utilities import (CABIN_AIR_QUALITY_RANGE, CABIN_PRESSURE_RANGE, CABIN_TEMPERATURE_RANGE,
                                   FUSELAGE_STRAIN_PER_G, HYDRAULIC_RANGE, LEADING_EDGE_NOISE, STRAIN_NOISE,
                                   WING_ROOT_STRAIN_PER_G, AirframeWorld, CabinWorld, HydraulicsWorld)

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)


class CabinWorldTest(unittest.TestCase):
    def test_readings_drift_within_the_configs_limits_and_the_epoch_cycles_from_one(self):
        world = CabinWorld(random.Random(3))
        self.assertEqual((0, 22.0, 101.3, 98.0), (world.epoch, world.temperature, world.pressure, world.air_quality))
        for n in range(1, 600):
            world.step()
            self.assertEqual((n - 1) % 255 + 1, world.epoch, "1-255: 0 is no reading")
            self.assertTrue(CABIN_TEMPERATURE_RANGE[0] <= world.temperature <= CABIN_TEMPERATURE_RANGE[1])
            self.assertTrue(CABIN_PRESSURE_RANGE[0] <= world.pressure <= CABIN_PRESSURE_RANGE[1])
            self.assertTrue(CABIN_AIR_QUALITY_RANGE[0] <= world.air_quality <= CABIN_AIR_QUALITY_RANGE[1])
        self.assertNotEqual(22.0, world.temperature, "it moved")

    def test_the_same_seed_gives_the_same_readings_and_a_hold_replaces_one(self):
        a, b = CabinWorld(random.Random(7)), CabinWorld(random.Random(7))
        for _ in range(50):
            a.step()
            b.step()
        self.assertEqual(a.message(), b.message())
        held = a.message({"cabin_temperature": 24.0, "cabin_air_quality": 93.0})
        self.assertEqual((24.0, 93.0, a.pressure, a.epoch), (held.temperature, held.air_quality, held.pressure, held.epoch))
        self.assertEqual(b.temperature, a.temperature, "the hold leaves the walk alone")

    def test_the_message_round_trips(self):
        world = CabinWorld(random.Random(5))
        for _ in range(20):
            world.step()
            status, words = world.message().encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED))
            self.assertEqual(m.PlantCabin.WORDS, len(words))
            status, back = m.PlantCabin.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertEqual(world.epoch, back.epoch)
            self.assertAlmostEqual(world.temperature, back.temperature, delta=0.006)
            self.assertAlmostEqual(world.pressure, back.pressure, delta=0.006)
            self.assertAlmostEqual(world.air_quality, back.air_quality, delta=0.006)


class HydraulicsWorldTest(unittest.TestCase):
    def test_pressures_drift_within_range_and_round_trip(self):
        world = HydraulicsWorld(random.Random(3))
        self.assertEqual((0, 2900.0, 2950.0), (world.epoch, world.primary_psi, world.backup_psi))
        for n in range(1, 300):
            world.step()
            self.assertEqual((n - 1) % 255 + 1, world.epoch)
            self.assertTrue(HYDRAULIC_RANGE[0] <= world.primary_psi <= HYDRAULIC_RANGE[1])
            self.assertTrue(HYDRAULIC_RANGE[0] <= world.backup_psi <= HYDRAULIC_RANGE[1])
            status, words = world.message().encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED))
            status, back = m.PlantHydraulics.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertAlmostEqual(world.primary_psi, back.primary_psi, delta=0.51)
            self.assertAlmostEqual(world.backup_psi, back.backup_psi, delta=0.51)
        held = world.message({"primary_psi": 2450.0})
        self.assertEqual((2450.0, world.backup_psi), (held.primary_psi, held.backup_psi))


class AirframeWorldTest(unittest.TestCase):
    def test_strain_follows_the_load_factor_and_the_temperature_the_altitude(self):
        world = AirframeWorld(random.Random(3))
        self.assertEqual(0, world.epoch)
        world.step(1.0, 10000.0)
        self.assertEqual(1, world.epoch)
        self.assertAlmostEqual(WING_ROOT_STRAIN_PER_G, world.wing_root_strain, delta=STRAIN_NOISE)
        self.assertAlmostEqual(FUSELAGE_STRAIN_PER_G, world.fuselage_strain, delta=STRAIN_NOISE)
        self.assertAlmostEqual(15.0 - 20.0, world.leading_edge_temp, delta=LEADING_EDGE_NOISE)
        world.step(4.0, 500.0)
        self.assertAlmostEqual(4.0 * WING_ROOT_STRAIN_PER_G, world.wing_root_strain, delta=STRAIN_NOISE)
        self.assertAlmostEqual(14.0, world.leading_edge_temp, delta=LEADING_EDGE_NOISE)
        world.step(-0.5, 0.0)
        self.assertEqual(0.0, world.wing_root_strain, "a gauge reads no negative strain")
        status, words = world.message().encode()
        self.assertIn(status, (Status.OK, Status.CLAMPED))
        status, back = m.PlantAirframe.decode(words)
        self.assertEqual(Status.OK, status)
        self.assertEqual(3, back.epoch)
        self.assertAlmostEqual(world.leading_edge_temp, back.leading_edge_temp, delta=0.006)
        held = world.message({"leading_edge_temp": -40.0, "wing_root_strain": 900.0})
        self.assertEqual((-40.0, 900.0, world.fuselage_strain), (held.leading_edge_temp, held.wing_root_strain,
                                                                held.fuselage_strain))


class PlantCarriesTheUtilitiesTest(unittest.TestCase):
    def test_the_plant_steps_publishes_and_can_leave_them_out(self):
        model = PlantModel(seed=1, traffic=False, ground=False, weather=False)
        self.assertEqual((0, 0, 0), (model.cabin_message().epoch, model.hydraulics_message().epoch,
                                     model.airframe_message().epoch))
        model.step_utilities(cabin=True, others=False)
        self.assertEqual((1, 0, 0), (model.cabin_message().epoch, model.hydraulics_message().epoch,
                                     model.airframe_message().epoch))
        model.step_utilities(cabin=True, others=True)
        self.assertEqual((2, 1, 1), (model.cabin_message().epoch, model.hydraulics_message().epoch,
                                     model.airframe_message().epoch))
        self.assertAlmostEqual(WING_ROOT_STRAIN_PER_G * model.g_force, model.airframe_message().wing_root_strain,
                               delta=STRAIN_NOISE, msg="from the flight state's load factor")
        # Held quantities, as the tests put them.
        for name in ("cabin_temperature", "cabin_pressure", "cabin_air_quality", "primary_psi", "backup_psi",
                     "wing_root_strain", "fuselage_strain", "leading_edge_temp"):
            self.assertIn(name, HOLDABLE)
        model.hold = dict(primary_psi=2450.0, cabin_temperature=24.0)
        self.assertEqual(2450.0, model.hydraulics_message().primary_psi)
        self.assertEqual(24.0, model.cabin_message().temperature)
        # Without the worlds: epoch 0 on all three.
        dark = PlantModel(seed=1, traffic=False, ground=False, weather=False, utilities=False)
        self.assertTrue(dark.cabin is None and dark.hydraulics is None and dark.airframe is None)
        dark.step_utilities(cabin=True, others=True)
        self.assertEqual((m.PlantCabin(), m.PlantHydraulics(), m.PlantAirframe()),
                         (dark.cabin_message(), dark.hydraulics_message(), dark.airframe_message()))
        # Their own generators: the flight state of a seeded run is the same with or without them.
        with_them = PlantModel(seed=9, traffic=False, ground=False, weather=False)
        without = PlantModel(seed=9, traffic=False, ground=False, weather=False, utilities=False)
        for _ in range(20):
            with_them.adjust()
            without.adjust()
            with_them.step_utilities(cabin=True, others=True)
        self.assertEqual((with_them.altitude, with_them.heading, with_them.g_force),
                         (without.altitude, without.heading, without.g_force))


if __name__ == "__main__":
    unittest.main()
