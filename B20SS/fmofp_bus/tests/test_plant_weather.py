"""The plant's weather world: repeatable, within the ICD's limits, and aged as the Python aged it, but for the
rain area's reflectivity, which the Python let grow without limit (ICD v1.24)."""

import math
import random
import unittest

from fmofp_bus.icd.messages import PlantWeather
from fmofp_bus.status import Status
from fmofp_plant.plant import PlantModel
from fmofp_plant.weather import WIND, StormCell, StratiformArea, WeatherWorld


class WeatherWorldTest(unittest.TestCase):
    def test_initial_world_and_message(self):
        world = WeatherWorld(random.Random(3))
        self.assertTrue(3 <= len(world.cells) <= 8)
        self.assertEqual(1, len(world.areas))
        for cell in world.cells:
            self.assertTrue(0 <= cell.position[0] < 360)
            self.assertTrue(20 <= cell.position[1] <= 180)
            self.assertTrue(5 <= cell.size <= 20)
            self.assertTrue(35 <= cell.intensity <= 65)
            self.assertFalse(cell.entry_profile)
        m = world.message()
        status, words = m.encode()
        self.assertEqual(Status.OK, status)
        self.assertEqual(32, len(words))
        self.assertEqual(len(world.cells), m.cell_count)
        self.assertEqual(1, m.area_count)
        again = PlantWeather.decode(words)[1]
        self.assertAlmostEqual(world.cells[0].position[0], again.cell_1_azimuth, delta=0.01)
        self.assertAlmostEqual(world.cells[0].size, again.cell_1_size, delta=0.25)
        self.assertEqual(2, world.message().weather_seq)

    def test_same_seed_same_world(self):
        a, b = WeatherWorld(random.Random(11)), WeatherWorld(random.Random(11))
        for _ in range(5):
            a.update(10.0)
            b.update(10.0)
        self.assertEqual(a.message().encode(), b.message().encode())

    def test_cells_drift_and_age_like_the_python(self):
        """StormCell.update, step for step: growth, then the mature plateau, then decay to nothing."""
        rng = random.Random(1)
        cell = StormCell(rng, (90.0, 100.0), 10.0, 40.0, False)
        cell.lifetime, cell.growth_phase, cell.mature_phase = 1000.0, 0.2, 0.5
        self.assertTrue(cell.update(rng, 100.0, WIND["altitude"]))
        self.assertAlmostEqual(50.0, cell.intensity)  # half way through the growth phase: 35 + 30 * 0.5
        # The wind at 290 degrees, 25 knots, for 100 s moves it 1.286 km outward.
        self.assertAlmostEqual(100.0 + 25 * 1.852 / 3600 * 100 * 0.3420201433, cell.position[1], places=6)
        self.assertTrue(cell.update(rng, 300.0, WIND["altitude"]))
        self.assertTrue(60 <= cell.intensity <= 70)
        self.assertFalse(cell.update(rng, 700.0, WIND["altitude"]), "past its lifetime")

    def test_the_python_rain_area_grows_without_limit(self):
        """The frozen StratiformArea.update writes its swing back into the value it swings around, at every
        call: stepped as the plant steps the weather (ten times a second), an area made at 20 dBZ is past the
        strongest storm cell there can be (65 dBZ) within a minute and past 2,000 dBZ within five. This is the
        behaviour the plant departs from."""
        from FMOFP.Systems.radarManagement.weather.weather_state_manager import StratiformArea as FrozenArea
        frozen = FrozenArea((90.0, 50.0), 100.0, 50.0, 20.0)
        frozen.lifetime = 7200.0
        expected = 20.0
        for step in range(1, 601):
            self.assertTrue(frozen.update(0.1, WIND["surface"]))
            expected += 3.0 * math.sin(step * 0.1 / 600)
        self.assertAlmostEqual(expected, frozen.intensity, places=6)
        self.assertGreater(frozen.intensity, 100.0, "a minute of flight")
        for _ in range(2400):
            frozen.update(0.1, WIND["surface"])
        self.assertGreater(frozen.intensity, 2000.0, "five minutes of flight")

    def test_the_plant_rain_area_keeps_the_strength_it_was_made_with(self):
        """The departure (ICD README section 2, v1.24): the swing and the decay work on the reflectivity the
        area was made with, as the Python's comments say they should. Its position still drifts as the
        Python's."""
        from FMOFP.Systems.radarManagement.weather.weather_state_manager import StratiformArea as FrozenArea
        rng = random.Random(4)
        area = StratiformArea(rng, (90.0, 50.0), 100.0, 50.0, 20.0)
        frozen = FrozenArea((90.0, 50.0), 100.0, 50.0, 20.0)
        area.lifetime = frozen.lifetime = 7200.0
        low, high = 20.0, 20.0
        for step in range(1, 30001):  # fifty minutes: under four fifths of its life
            self.assertTrue(area.update(0.1, WIND["surface"]))
            frozen.update(0.1, WIND["surface"])
            low, high = min(low, area.intensity), max(high, area.intensity)
            if step % 6000 == 0:
                self.assertAlmostEqual(20.0 + 3.0 * math.sin(area.age / 600), area.intensity, places=9)
        self.assertGreaterEqual(low, 17.0)
        self.assertLessEqual(high, 23.0)
        self.assertGreater(high, 22.99, "the swing reaches three either way")
        self.assertLess(low, 17.01)
        self.assertAlmostEqual(frozen.position[0], area.position[0], places=9)
        self.assertAlmostEqual(frozen.position[1], area.position[1], places=9)
        # The last fifth of its life: down toward a fifth of what it was made with, and it ends below 5 dBZ.
        area.age = 0.9 * area.lifetime - 0.1
        self.assertTrue(area.update(0.1, WIND["surface"]))
        self.assertAlmostEqual(20.0 * 0.6 + 3.0 * math.sin(area.age / 600), area.intensity, places=6)
        area.age = area.lifetime - 0.2
        alive = area.update(0.1, WIND["surface"])
        self.assertAlmostEqual(20.0 * 0.2 + 3.0 * math.sin(area.age / 600), area.intensity, delta=0.01)
        self.assertEqual(area.intensity > 5, alive)

    def test_the_whole_sky_stays_within_what_a_radar_can_see(self):
        """Half an hour of the plant's weather at its own step: no cell and no area above the 65 dBZ a storm
        cell peaks at, where the area had reached 35,000 dBZ."""
        world = WeatherWorld(random.Random(1 ^ 0x5745))
        strongest = 0.0
        for _ in range(18000):
            world.update(0.1)
            strongest = max(strongest, world.areas[0].intensity, max(cell.intensity for cell in world.cells))
        self.assertLessEqual(world.areas[0].intensity, 33.0, "made at 15 to 30 dBZ, three either way")
        self.assertLessEqual(strongest, 70.0, "a mature cell is 65 dBZ give or take five")

    def test_the_sky_is_never_empty(self):
        world = WeatherWorld(random.Random(2), populate=False)
        world.update(1.0)
        self.assertEqual(1, len(world.cells))
        self.assertEqual(1, len(world.areas))

    def test_plant_publishes_it(self):
        model = PlantModel(seed=5)
        m = model.weather_message()
        self.assertGreaterEqual(m.cell_count, 3)
        model.move(0.1)
        self.assertEqual(2, model.weather_message().weather_seq)
        quiet = PlantModel(seed=5, weather=False)
        self.assertEqual(0, quiet.weather_message().cell_count)


if __name__ == "__main__":
    unittest.main()
