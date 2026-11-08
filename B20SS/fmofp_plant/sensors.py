"""The sensor scans the sensor management terminal receives: the two sensor managers' draws, as the world.

SensorDataFusion owned its own ActiveSensorManager and PassiveSensorManager and, five times a second, asked
each sensor for a scan. Radar.scan invented randint(0, 5) detections, each a distance uniform in 0 to the
radar's range, an angle uniform in 0-360 degrees and a speed uniform in 0-1000 m/s; Lidar.scan randint(0, 5)
points, each a distance uniform in 0-1000 m, an azimuth uniform in 0-360 and an elevation uniform in -15 to 15
degrees; InfraredSensor.detect randint(0, 3) objects, each a temperature uniform in 0-1000, an angle uniform
across the field of view and a distance uniform in 100-10000 m. The ESM sensor's intercepts are
fmofp_plant.esm. Here those numbers are the world's, published as the PLANT_SENSOR_SCAN block every 10 frames,
drawn in the managers' order: main radar, terrain-following radar, LIDAR, forward-looking infrared, missile
approach warning (the Python's sensors seeded alike invent the same scans). The sensor management terminal
(RT 10) fuses them.
"""

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd.enums import SensorId

MAX_RADAR_DETECTIONS = 5        # Radar.scan: randint(0, 5)
MAX_LIDAR_POINTS = 5            # Lidar.MAX_DETECTIONS_PER_SCAN
MAX_IR_OBJECTS = 3              # InfraredSensor.detect: randint(0, 3)
MAIN_RADAR_RANGE_M = 300000.0   # Radar("Main Radar", 300000, 0.95, 10e9)
TFR_RADAR_RANGE_M = 50000.0     # Radar("Terrain Following Radar", 50000, 0.99, 15e9)
LIDAR_RANGE_M = 1000.0          # Lidar("LIDAR", 1000, 0.99, 1000000)
SPEED_MS = (0.0, 1000.0)
ELEVATION_DEG = (-15.0, 15.0)
TEMPERATURE = (0.0, 1000.0)
IR_DISTANCE_M = (100.0, 10000.0)
FLIR_FOV_DEG = 60.0             # InfraredSensor("Forward Looking Infrared", 0.1, 60, (8e-6, 14e-6))
MAWS_FOV_DEG = 360.0            # InfraredSensor("Missile Approach Warning", 0.05, 360, (3e-6, 5e-6))


class SensorScanWorld:
    """The five scanning sensors' detections, a set at a time from its own random generator."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0
        self.radar = []      # (sensor, distance_m, angle_deg, speed_ms)
        self.lidar = []      # (distance_m, azimuth_deg, elevation_deg)
        self.infrared = []   # (sensor, temperature, angle_deg, distance_m)

    def _radar(self, sensor, range_m):
        u = self.rng.uniform
        return [(sensor, u(0.0, range_m), u(0.0, 360.0), u(*SPEED_MS))
                for _ in range(self.rng.randint(0, MAX_RADAR_DETECTIONS))]

    def _lidar(self):
        u = self.rng.uniform
        return [(u(0.0, LIDAR_RANGE_M), u(0.0, 360.0), u(*ELEVATION_DEG))
                for _ in range(self.rng.randint(0, MAX_LIDAR_POINTS))]

    def _infrared(self, sensor, fov_deg):
        u = self.rng.uniform
        return [(sensor, u(*TEMPERATURE), u(-fov_deg / 2, fov_deg / 2), u(*IR_DISTANCE_M))
                for _ in range(self.rng.randint(0, MAX_IR_OBJECTS))]

    def step(self):
        """One scan set, in the order SensorDataFusion.update asked the sensors."""
        self.radar = self._radar(SensorId.MAIN_RADAR, MAIN_RADAR_RANGE_M) + self._radar(SensorId.TFR_RADAR, TFR_RADAR_RANGE_M)
        self.lidar = self._lidar()
        self.infrared = self._infrared(SensorId.FLIR, FLIR_FOV_DEG) + self._infrared(SensorId.MAWS, MAWS_FOV_DEG)
        self.epoch = (self.epoch + 1) % 256

    def block(self):
        scan = b.PlantSensorScan(epoch=self.epoch)
        scan.radar = [b.PlantSensorScanRadar(sensor=sensor, distance=distance, angle=angle, speed=speed)
                      for sensor, distance, angle, speed in self.radar]
        scan.lidar = [b.PlantSensorScanLidar(distance=distance, azimuth=azimuth, elevation=elevation)
                      for distance, azimuth, elevation in self.lidar]
        scan.infrared = [b.PlantSensorScanInfrared(sensor=sensor, temperature=temperature, angle=angle, distance=distance)
                         for sensor, temperature, angle, distance in self.infrared]
        return scan
