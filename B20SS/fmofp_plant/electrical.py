"""The electrical readings the power management terminal measures: PowerManagementSystem's draws, as the world.

The Python's PowerManagementSystem drew, once a second, a generator output uniform in 200-250 kW and a total
consumption uniform in 180-220 kW (adjust_power_parameters), then, taking its snapshot, a main bus voltage
uniform in 110-120 V, an auxiliary bus voltage uniform in 25-28 V, a generator frequency uniform in 398-402 Hz
and a power factor uniform in 0.95-1 (monitor). Here those numbers are the world's, published as
PLANT_ELECTRICAL once a second in the Python's draw order. The power management terminal (RT 8) does the
bookkeeping: the batteries, the coolant loop, the cabin. Its SET_GENERATOR_OUTPUT (the Python's
set_generator_output, whose value the next second's draw overwrote) holds the generator at the commanded output
(PLANT_GEN_CMD) until GENERATOR_AUTO; the draw is made and discarded meanwhile, so a seeded run keeps its
sequence.
"""

from fmofp_bus.icd import messages as m

GENERATOR_KW = (200.0, 250.0)      # adjust_power_parameters: random.uniform(200, 250)
CONSUMPTION_KW = (180.0, 220.0)    # random.uniform(180, 220)
MAIN_BUS_V = (110.0, 120.0)        # monitor: random.uniform(110, 120)
AUX_BUS_V = (25.0, 28.0)           # random.uniform(25, 28)
FREQUENCY_HZ = (398.0, 402.0)      # random.uniform(398, 402)
POWER_FACTOR = (0.95, 1.0)         # random.uniform(0.95, 1)


class ElectricalWorld:
    """The generator, the loads and the buses, read once a second from their own random generator."""

    def __init__(self, rng):
        self.rng = rng
        self.epoch = 0            # 1-255 once readings exist; 0 says "no reading" to the terminal
        self.generator_output = 0.0
        self.total_power_consumption = 0.0
        self.main_bus_voltage = 0.0
        self.aux_bus_voltage = 0.0
        self.generator_frequency = 0.0
        self.power_factor = 0.0
        self.hold_kw = None       # the output PLANT_GEN_CMD holds the generator at, or None
        self.commands = 0

    def command(self, gen_cmd):
        """A PWR_GEN_CMD (the payload of PLANT_GEN_CMD): the generator held at its output while override is set.
        True when the hold changed."""
        hold = max(0.0, float(gen_cmd.generator_output)) if gen_cmd.override else None
        if hold == self.hold_kw:
            return False
        self.hold_kw = hold
        self.commands += 1
        return True

    def step(self):
        """One second, in the Python's draw order: the generator, the loads, then the snapshot's buses."""
        u = self.rng.uniform
        drawn = u(*GENERATOR_KW)
        self.generator_output = drawn if self.hold_kw is None else self.hold_kw
        self.total_power_consumption = u(*CONSUMPTION_KW)
        self.main_bus_voltage = u(*MAIN_BUS_V)
        self.aux_bus_voltage = u(*AUX_BUS_V)
        self.generator_frequency = u(*FREQUENCY_HZ)
        self.power_factor = u(*POWER_FACTOR)
        self.epoch = self.epoch % 255 + 1

    def message(self):
        return m.PlantElectrical(epoch=self.epoch, generator_override=self.hold_kw is not None,
                                 generator_output=self.generator_output,
                                 total_power_consumption=self.total_power_consumption,
                                 main_bus_voltage=self.main_bus_voltage, aux_bus_voltage=self.aux_bus_voltage,
                                 generator_frequency=self.generator_frequency, power_factor=self.power_factor)
