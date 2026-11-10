"""The readings the four small utility terminals measure, invented by the plant: the cabin environment, the hydraulic
pressures and the airframe sensors.

None of the three Python subsystems had a sensor source: ECSControl's temperature, pressure and air quality stayed
None until set_sensor_readings, which nothing called; HydraulicSystemController.monitor_pressure read a constant 2800
psi; AirframeSystemManager.set_sensor_reading had no caller. So these are the plant's own, with nothing to copy
from the Python: slow random walks from their own seeded generators (so earlier seeded flights keep their
sequences), each published on its own message at the Python loop's rate (PLANT_CABIN twice a second,
PLANT_HYDRAULICS and PLANT_AIRFRAME once a second), with an epoch that says when a reading is new. The airframe's
strain gauges follow the load factor and its leading-edge temperature the altitude, so the readings move with the
flight. A quantity can be held at a value for a test (PlantModel.hold, like the flight state).
"""

from fmofp_bus.icd import messages as m

CABIN_TEMPERATURE_C = 22.0        # ECSControl.adjust_temperature's target
CABIN_PRESSURE_KPA = 101.3        # adjust_pressure's target
CABIN_AIR_QUALITY_PCT = 98.0      # above adjust_air_quality's 95 % threshold
CABIN_TEMPERATURE_WALK = 0.05     # degrees a step, either way
CABIN_PRESSURE_WALK = 0.02        # kPa a step
CABIN_AIR_QUALITY_WALK = 0.1      # percent a step
CABIN_TEMPERATURE_RANGE = (18.0, 26.0)     # ecsConfig.xml's min/max allowed (the code never read them)
CABIN_PRESSURE_RANGE = (95.0, 105.0)
CABIN_AIR_QUALITY_RANGE = (90.0, 100.0)

PRIMARY_PSI = 2900.0              # the primary system under load
BACKUP_PSI = 2950.0               # the backup system, unloaded
HYDRAULIC_WALK = 5.0              # psi a step
HYDRAULIC_RANGE = (2700.0, 3100.0)

WING_ROOT_STRAIN_PER_G = 180.0    # microstrain per g
FUSELAGE_STRAIN_PER_G = 110.0
STRAIN_NOISE = 4.0                # microstrain, either way
LEADING_EDGE_SEA_LEVEL_C = 15.0   # the ISA ground temperature
LEADING_EDGE_LAPSE_C_PER_FT = 0.002
LEADING_EDGE_NOISE = 0.3          # degrees, either way


def _walk(rng, value, step, low, high):
    return max(low, min(high, value + rng.uniform(-step, step)))


class CabinWorld:
    """The cabin's temperature, pressure and clean-air fraction, drifting slowly."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0            # 1-255 once readings exist; 0 says "no reading" to the terminal
        self.temperature = CABIN_TEMPERATURE_C
        self.pressure = CABIN_PRESSURE_KPA
        self.air_quality = CABIN_AIR_QUALITY_PCT

    def step(self):
        """One pass of the environmental control system's 2 Hz loop: a new reading of each."""
        self.temperature = _walk(self.rng, self.temperature, CABIN_TEMPERATURE_WALK, *CABIN_TEMPERATURE_RANGE)
        self.pressure = _walk(self.rng, self.pressure, CABIN_PRESSURE_WALK, *CABIN_PRESSURE_RANGE)
        self.air_quality = _walk(self.rng, self.air_quality, CABIN_AIR_QUALITY_WALK, *CABIN_AIR_QUALITY_RANGE)
        self.epoch = self.epoch % 255 + 1

    def message(self, hold=None):
        hold = hold or {}
        return m.PlantCabin(epoch=self.epoch, temperature=hold.get("cabin_temperature", self.temperature),
                            pressure=hold.get("cabin_pressure", self.pressure),
                            air_quality=hold.get("cabin_air_quality", self.air_quality))


class HydraulicsWorld:
    """The primary and backup hydraulic systems' pressures, drifting slowly."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0
        self.primary_psi = PRIMARY_PSI
        self.backup_psi = BACKUP_PSI

    def step(self):
        """One pass of the hydraulics controller's 1 Hz loop: a new reading of each."""
        self.primary_psi = _walk(self.rng, self.primary_psi, HYDRAULIC_WALK, *HYDRAULIC_RANGE)
        self.backup_psi = _walk(self.rng, self.backup_psi, HYDRAULIC_WALK, *HYDRAULIC_RANGE)
        self.epoch = self.epoch % 255 + 1

    def message(self, hold=None):
        hold = hold or {}
        return m.PlantHydraulics(epoch=self.epoch, primary_psi=hold.get("primary_psi", self.primary_psi),
                                 backup_psi=hold.get("backup_psi", self.backup_psi))


class AirframeWorld:
    """asmConfig.xml's three sensors: two strain gauges that follow the load factor and a leading-edge temperature
    that follows the altitude, each with a little noise."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0
        self.wing_root_strain = 0.0
        self.fuselage_strain = 0.0
        self.leading_edge_temp = 0.0

    def step(self, g_force, altitude_ft):
        """One pass of the airframe manager's 1 Hz loop: a new reading of each, from the flight state now."""
        u = self.rng.uniform
        self.wing_root_strain = max(0.0, WING_ROOT_STRAIN_PER_G * g_force + u(-STRAIN_NOISE, STRAIN_NOISE))
        self.fuselage_strain = max(0.0, FUSELAGE_STRAIN_PER_G * g_force + u(-STRAIN_NOISE, STRAIN_NOISE))
        self.leading_edge_temp = (LEADING_EDGE_SEA_LEVEL_C - LEADING_EDGE_LAPSE_C_PER_FT * altitude_ft
                                  + u(-LEADING_EDGE_NOISE, LEADING_EDGE_NOISE))
        self.epoch = self.epoch % 255 + 1

    def message(self, hold=None):
        hold = hold or {}
        return m.PlantAirframe(epoch=self.epoch, wing_root_strain=hold.get("wing_root_strain", self.wing_root_strain),
                               fuselage_strain=hold.get("fuselage_strain", self.fuselage_strain),
                               leading_edge_temp=hold.get("leading_edge_temp", self.leading_edge_temp))
