"""The plant's sensor scans: the two sensor managers' draws as the world, on the PLANT_SENSOR_SCAN block. No sockets."""

import os
import random
import sys
import unittest

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd.enums import SensorId
from fmofp_bus.status import Status
from fmofp_plant.plant import PlantModel
from fmofp_plant.sensors import (FLIR_FOV_DEG, LIDAR_RANGE_M, MAIN_RADAR_RANGE_M, MAWS_FOV_DEG, MAX_IR_OBJECTS,
                                 MAX_LIDAR_POINTS, MAX_RADAR_DETECTIONS, TFR_RADAR_RANGE_M, SensorScanWorld)

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)


class SensorScanWorldTest(unittest.TestCase):
    def test_a_set_has_the_sensors_counts_and_ranges(self):
        world = SensorScanWorld(random.Random(3))
        self.assertEqual((0, [], [], []), (world.epoch, world.radar, world.lidar, world.infrared))
        radar_counts, lidar_counts, ir_counts = set(), set(), set()
        for n in range(1, 301):
            world.step()
            self.assertEqual(n % 256, world.epoch)
            main = [d for d in world.radar if d[0] == SensorId.MAIN_RADAR]
            tfr = [d for d in world.radar if d[0] == SensorId.TFR_RADAR]
            self.assertEqual(len(main) + len(tfr), len(world.radar))
            self.assertLessEqual(len(main), MAX_RADAR_DETECTIONS)
            self.assertLessEqual(len(tfr), MAX_RADAR_DETECTIONS)
            radar_counts.add(len(main))
            for _, distance, angle, speed in main:
                self.assertTrue(0.0 <= distance <= MAIN_RADAR_RANGE_M and 0.0 <= angle < 360.0 and 0.0 <= speed <= 1000.0)
            for _, distance, _, _ in tfr:
                self.assertLessEqual(distance, TFR_RADAR_RANGE_M)
            self.assertLessEqual(len(world.lidar), MAX_LIDAR_POINTS)
            lidar_counts.add(len(world.lidar))
            for distance, azimuth, elevation in world.lidar:
                self.assertTrue(0.0 <= distance <= LIDAR_RANGE_M and 0.0 <= azimuth < 360.0 and -15.0 <= elevation <= 15.0)
            flir = [o for o in world.infrared if o[0] == SensorId.FLIR]
            maws = [o for o in world.infrared if o[0] == SensorId.MAWS]
            self.assertLessEqual(len(flir), MAX_IR_OBJECTS)
            self.assertLessEqual(len(maws), MAX_IR_OBJECTS)
            ir_counts.add(len(flir))
            for _, temperature, angle, distance in flir:
                self.assertTrue(0.0 <= temperature <= 1000.0 and abs(angle) <= FLIR_FOV_DEG / 2 and 100.0 <= distance <= 10000.0)
            for _, _, angle, _ in maws:
                self.assertLessEqual(abs(angle), MAWS_FOV_DEG / 2)
        self.assertEqual(set(range(MAX_RADAR_DETECTIONS + 1)), radar_counts, "randint(0, 5)")
        self.assertEqual(set(range(MAX_LIDAR_POINTS + 1)), lidar_counts)
        self.assertEqual(set(range(MAX_IR_OBJECTS + 1)), ir_counts, "randint(0, 3)")

    def test_the_scans_are_the_pythons_sensors_draws_in_their_order(self):
        """The managers' sensors, seeded like the world and asked in SensorDataFusion.update's order, invent the
        same scans."""
        from FMOFP.Systems.sensorManagement.activeSensors.activeSensors import ActiveSensorManager
        from FMOFP.Systems.sensorManagement.passiveSensors.passiveSensors import PassiveSensorManager
        world = SensorScanWorld(random.Random(11))
        world.step()
        world.step()
        random.seed(11)
        active, passive = ActiveSensorManager(), PassiveSensorManager()
        for manager in (active, passive):
            for sensor in manager.sensors.values():
                sensor.activate()
        for _ in range(2):
            main = active.sensors["main_radar"].scan()
            tfr = active.sensors["terrain_following_radar"].scan()
            lidar = active.sensors["lidar"].scan()
            flir = passive.sensors["forward_looking_infrared"].detect()
            maws = passive.sensors["missile_approach_warning"].detect()
        self.assertEqual([(SensorId.MAIN_RADAR, d["distance"], d["angle"], d["speed"]) for d in main]
                         + [(SensorId.TFR_RADAR, d["distance"], d["angle"], d["speed"]) for d in tfr], world.radar)
        self.assertEqual([(p["distance"], p["azimuth"], p["elevation"]) for p in lidar], world.lidar)
        self.assertEqual([(SensorId.FLIR, o["temperature"], o["angle"], o["distance"]) for o in flir]
                         + [(SensorId.MAWS, o["temperature"], o["angle"], o["distance"]) for o in maws], world.infrared)

    def test_the_block_round_trips(self):
        world = SensorScanWorld(random.Random(5))
        for _ in range(20):
            world.step()
            status, words = world.block().encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED))
            self.assertLessEqual(len(words), b.PlantSensorScan.MAX_PAYLOAD_WORDS)
            status, back = b.PlantSensorScan.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertEqual(world.epoch, back.epoch)
            self.assertEqual((len(world.radar), len(world.lidar), len(world.infrared)),
                             (len(back.radar), len(back.lidar), len(back.infrared)))
            for (sensor, distance, angle, speed), record in zip(world.radar, back.radar):
                self.assertEqual(sensor, record.sensor)
                self.assertAlmostEqual(distance, record.distance, delta=0.07)
                self.assertAlmostEqual(angle, record.angle, delta=0.006)
                self.assertAlmostEqual(speed, record.speed, delta=0.06)
            for (distance, azimuth, elevation), record in zip(world.lidar, back.lidar):
                self.assertAlmostEqual(distance, record.distance, delta=0.07)
                self.assertAlmostEqual(azimuth, record.azimuth, delta=0.006)
                self.assertAlmostEqual(elevation, record.elevation, delta=0.006)
            for (sensor, temperature, angle, distance), record in zip(world.infrared, back.infrared):
                self.assertEqual(sensor, record.sensor)
                self.assertAlmostEqual(temperature, record.temperature, delta=0.06)
                self.assertAlmostEqual(angle, record.angle, delta=0.006)
                self.assertAlmostEqual(distance, record.distance, delta=0.26)

    def test_the_plant_carries_it_and_can_leave_it_out(self):
        model = PlantModel(seed=1, traffic=False, ground=False, weather=False)
        self.assertIsNotNone(model.scan_world)
        model.scan_world.step()
        self.assertEqual(1, model.scan_block().epoch)
        blind = PlantModel(seed=1, traffic=False, ground=False, weather=False, scan_sensors=False)
        self.assertIsNone(blind.scan_world)
        self.assertEqual(b.PlantSensorScan(), blind.scan_block())
        # Its own generator: the flight state of a seeded run is the same with or without the scans.
        with_scans = PlantModel(seed=9, traffic=False, ground=False, weather=False)
        without = PlantModel(seed=9, traffic=False, ground=False, weather=False, scan_sensors=False)
        for _ in range(20):
            with_scans.adjust()
            without.adjust()
        self.assertEqual((with_scans.altitude, with_scans.heading), (without.altitude, without.heading))


if __name__ == "__main__":
    unittest.main()
