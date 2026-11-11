"""The scenario engine's injections into the plant's world (ICD v1.23): a radar contact into the traffic, a storm
cell into the sky, and the plant's reading of the two messages."""

import math
import random
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import IffIdentity, TargetClass, WeatherCategory
from fmofp_bus.status import Status
from fmofp_plant.plant import PlantModel
from fmofp_plant.traffic import INJECTED, M_PER_FT, MAX_TARGETS, TARGETING, TrafficWorld
from fmofp_plant.weather import MAX_CELLS, WIND, WeatherWorld

OWNSHIP = (1000.0, 2000.0, 3000.0)  # east, north, up in metres


class TrafficInjectionTest(unittest.TestCase):
    def test_an_injected_aircraft_is_placed_relative_to_the_aircraft_and_flies_straight(self):
        world = TrafficWorld(random.Random(1), populations=(TARGETING,))
        world.populate(OWNSHIP)
        self.assertEqual(TARGETING.count, len(world.targets))
        target = world.inject(7, OWNSHIP, 80.0, 60.0, 25000.0, (-5.0, -3.0, 0.0), 5.0, False)
        self.assertEqual(TARGETING.count + 1, len(world.targets))
        self.assertIs(target, world.targets[-1])
        self.assertEqual(7, target.injected_id)
        self.assertIs(INJECTED, target.population)
        self.assertEqual([OWNSHIP[0] + 80000.0, OWNSHIP[1] + 60000.0, 25000.0 * M_PER_FT], target.position)
        self.assertEqual([-5.0, -3.0, 0.0], target.velocity)
        self.assertEqual([0.0, 0.0, 0.0], target.acceleration)
        self.assertEqual((5.0, False), (target.rcs, target.stealth))
        # no acceleration: the velocity stays, the position moves with it
        world.update(10.0, OWNSHIP)
        self.assertEqual([-5.0, -3.0, 0.0], target.velocity)
        self.assertAlmostEqual(OWNSHIP[0] + 80000.0 - 50.0, target.position[0])
        self.assertAlmostEqual(OWNSHIP[1] + 60000.0 - 30.0, target.position[1])
        # far from the aircraft it stays (a generated aircraft beyond its generator's range would be replaced)
        world.update(1.0, (OWNSHIP[0] + 5e6, OWNSHIP[1], OWNSHIP[2]))
        self.assertIn(target, world.targets)
        # the same contact id moves the aircraft injected before
        again = world.inject(7, OWNSHIP, 65.0, 50.0, 24000.0, (-5.0, -3.0, 1.0), 6.0, True)
        self.assertIs(target, again)
        self.assertEqual(TARGETING.count + 1, len(world.targets))
        self.assertEqual([OWNSHIP[0] + 65000.0, OWNSHIP[1] + 50000.0, 24000.0 * M_PER_FT], target.position)
        self.assertEqual(([-5.0, -3.0, 1.0], 6.0, True), (target.velocity, target.rcs, target.stealth))

    def test_a_thirteenth_aircraft_replaces_the_farthest_generated_one(self):
        world = TrafficWorld(random.Random(2))
        world.populate(OWNSHIP)
        self.assertEqual(MAX_TARGETS, len(world.targets))
        farthest = max(world.targets, key=lambda t: world.range_m(t, OWNSHIP))
        first = world.inject(1, OWNSHIP, 10.0, 10.0, 20000.0, (0.0, 0.0, 0.0), 5.0, False)
        self.assertEqual(MAX_TARGETS, len(world.targets))
        self.assertNotIn(farthest, world.targets)
        self.assertIn(first, world.targets)
        second = world.inject(2, OWNSHIP, -10.0, 5.0, 20000.0, (0.0, 0.0, 0.0), 5.0, False)
        self.assertEqual(MAX_TARGETS, len(world.targets))
        self.assertIn(first, world.targets)  # an injected aircraft is never the one replaced
        self.assertIn(second, world.targets)
        self.assertEqual(2, sum(1 for t in world.targets if t.injected_id is not None))


class WeatherInjectionTest(unittest.TestCase):
    def test_an_injected_cell_sits_where_asked_at_its_reflectivity(self):
        sky = WeatherWorld(random.Random(4), populate=False)
        self.assertEqual([], sky.cells)
        cell = sky.inject(45.0, 30.0, 8.0, 42.0)
        self.assertEqual([cell], sky.cells)
        self.assertEqual(((45.0, 30.0), 8.0, 42.0, True), (cell.position, cell.size, cell.intensity, cell.injected))
        # placed in its growth phase where 42 dBZ is reached: a step of no time keeps it there
        cell.update(sky.rng, 0.0, WIND["altitude"])
        self.assertAlmostEqual(42.0, cell.intensity, places=6)
        severe = sky.inject(300.0, 10.0, 12.0, 55.0)
        severe.update(sky.rng, 0.0, WIND["altitude"])
        self.assertAlmostEqual(55.0, severe.intensity, places=6)
        mature = sky.inject(0.0, 50.0, 5.0, 70.0)  # beyond the growth phase's 65: the mature phase, 65 +- 5
        mature.update(sky.rng, 0.0, WIND["altitude"])
        self.assertGreaterEqual(mature.intensity, 60.0)
        self.assertLessEqual(mature.intensity, 70.0)
        weak = sky.inject(0.0, 5.0, 5.0, 20.0)  # below the growth phase's start: it starts at 35
        weak.update(sky.rng, 0.0, WIND["altitude"])
        self.assertAlmostEqual(35.0, weak.intensity, places=6)
        self.assertEqual(4, len(sky.cells))

    def test_a_ninth_cell_replaces_the_weakest(self):
        sky = WeatherWorld(random.Random(5), populate=False)
        for i in range(MAX_CELLS):
            sky.inject(float(i * 40), 50.0, 5.0, 40.0 + i)
        weakest = min(sky.cells, key=lambda c: c.intensity)
        self.assertEqual(40.0, weakest.intensity)
        new = sky.inject(10.0, 10.0, 5.0, 60.0)
        self.assertEqual(MAX_CELLS, len(sky.cells))
        self.assertNotIn(weakest, sky.cells)
        self.assertIn(new, sky.cells)

    def test_an_injection_does_not_move_the_seeded_sky(self):
        plain = WeatherWorld(random.Random(6))
        injected = WeatherWorld(random.Random(6))
        injected.inject(90.0, 20.0, 5.0, 42.0)
        plain.update(1.0)
        injected.update(1.0)
        generated = [c for c in injected.cells if not getattr(c, "injected", False)]
        self.assertEqual(len(plain.cells), len(generated))
        for a, b in zip(plain.cells, generated):
            self.assertEqual((a.position, a.intensity, a.size), (b.position, b.intensity, b.size))


class PlantInjectionMessagesTest(unittest.TestCase):
    def test_the_plant_puts_a_contact_into_its_traffic(self):
        model = PlantModel(seed=9, ground=False)
        status, words = m.PlantInjectContact(contact_id=1, classification=TargetClass.FIGHTER, identity=IffIdentity.HOSTILE,
                                             x_km=65.0, y_km=50.0, alt_ft=24000.0, velocity_east=-5.0, velocity_north=-3.0,
                                             rcs=5.0).encode()
        self.assertEqual(Status.OK, status)
        self.assertTrue(model.inject_contact(words))
        own = model.ownship_enu()
        target = next(t for t in model.traffic.targets if t.injected_id == 1)
        self.assertAlmostEqual(own[0] + 65000.0, target.position[0], places=3)
        self.assertAlmostEqual(own[1] + 50000.0, target.position[1], places=3)
        self.assertAlmostEqual(24000.0 * M_PER_FT, target.position[2], places=3)
        self.assertEqual(([-5.0, -3.0, 0.0], 5.0, False), (target.velocity, target.rcs, target.stealth))
        # contact 0 is REJECTED
        status, words = m.PlantInjectContact(contact_id=0, x_km=1.0).encode()
        self.assertEqual(Status.OK, status)
        self.assertFalse(model.inject_contact(words))
        self.assertEqual(1, sum(1 for t in model.traffic.targets if t.injected_id is not None))
        # a plant without traffic or weather has nowhere to put an injection
        bare = PlantModel(seed=9, traffic=False, weather=False, ground=False)
        status, words = m.PlantInjectContact(contact_id=1, x_km=1.0).encode()
        self.assertFalse(bare.inject_contact(words))
        status, words = m.PlantInjectWeather(x_km=1.0).encode()
        self.assertFalse(bare.inject_weather(words))

    def test_the_plant_puts_a_cell_into_its_sky_at_the_bearing_and_range_of_the_offset(self):
        model = PlantModel(seed=9, ground=False)
        for x_km, y_km, azimuth, range_km in ((20.0, 0.0, 90.0, 20.0), (0.0, 10.0, 0.0, 10.0), (-10.0, -10.0, 225.0, math.hypot(10, 10))):
            status, words = m.PlantInjectWeather(category=WeatherCategory.SEVERE, x_km=x_km, y_km=y_km, size=8.0,
                                                 intensity=0.6, reflectivity=42.0).encode()
            self.assertEqual(Status.OK, status)
            before = [c for c in model.weather.cells if getattr(c, "injected", False)]
            self.assertTrue(model.inject_weather(words))
            cell = next(c for c in model.weather.cells if getattr(c, "injected", False) and c not in before)
            self.assertAlmostEqual(azimuth, cell.position[0], places=6)
            self.assertAlmostEqual(range_km, cell.position[1], places=6)
            self.assertEqual((8.0, 42.0), (cell.size, cell.intensity))


if __name__ == "__main__":
    unittest.main()
