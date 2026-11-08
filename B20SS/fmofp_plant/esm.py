"""The ESM intercepts the defensive systems terminal receives: ESMSensor.detect's draws, as the world.

The Python's PassiveSensorManager held an ESM sensor whose detect() invented, on every call, randint(0, 5)
signals, each a frequency uniform in 0.5-40 GHz, a signal strength uniform in -120 to -20 dBm and a bearing
uniform in 0-360 degrees; DefensiveService called it every half second and, for a signal it had not seen
before (the same band and whole bearing), drew a range uniform in 5-60 nm itself. Here those numbers are the
world's, published as PLANT_ESM: a new set every 25 frames, drawn in the sensor's order (a sensor seeded
alike detects the same signals), then one range per signal, which the Python's service would have drawn for
the new ones. The defensive systems terminal (RT 22) classifies, names, ages and sorts them.
"""

from fmofp_bus.icd import messages as m

MAX_SIGNALS = 5                      # ESMSensor.detect: randint(0, 5)
FREQUENCY_HZ = (0.5e9, 40e9)         # ESMSensor("Electronic Support Measures", 0.01, 360, (0.5e9, 40e9))
STRENGTH_DBM = (-120.0, -20.0)
BEARING_DEG = (0.0, 360.0)
RANGE_NM = (5.0, 60.0)               # DefensiveService._update_rwr: random.uniform(5, 60) for a new contact


class EsmWorld:
    """The intercepts, a new set at a time from its own random generator."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0
        self.signals = []   # (frequency_hz, strength_dbm, bearing_deg, range_nm)

    def step(self):
        """One detection set, in ESMSensor.detect's draw order, then the ranges."""
        u = self.rng.uniform
        detected = []
        for _ in range(self.rng.randint(0, MAX_SIGNALS)):
            frequency = u(*FREQUENCY_HZ)
            strength = u(*STRENGTH_DBM)
            bearing = u(*BEARING_DEG)
            detected.append((frequency, strength, bearing))
        self.signals = [(frequency, strength, bearing, u(*RANGE_NM)) for frequency, strength, bearing in detected]
        self.epoch = (self.epoch + 1) % 256

    def message(self):
        fields = {"epoch": self.epoch, "count": len(self.signals)}
        for i, (frequency, strength, bearing, range_nm) in enumerate(self.signals, start=1):
            fields[f"frequency_{i}"] = frequency / 1e6
            fields[f"strength_{i}"] = strength
            fields[f"bearing_{i}"] = bearing
            fields[f"range_{i}"] = range_nm
        return m.PlantEsm(**fields)
