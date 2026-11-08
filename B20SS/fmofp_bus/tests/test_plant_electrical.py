"""The plant's electrical readings: PowerManagementSystem's draws as the world, on PLANT_ELECTRICAL. No sockets."""

import os
import random
import sys
import unittest
from unittest import mock

from fmofp_bus.icd import messages as m
from fmofp_bus.status import Status
from fmofp_plant.electrical import (AUX_BUS_V, CONSUMPTION_KW, FREQUENCY_HZ, GENERATOR_KW, MAIN_BUS_V, POWER_FACTOR,
                                    ElectricalWorld)
from fmofp_plant.plant import PlantModel

B20SS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if B20SS not in sys.path:
    sys.path.insert(0, B20SS)


class ElectricalWorldTest(unittest.TestCase):
    def test_a_reading_is_within_the_pythons_ranges_and_the_epoch_cycles_from_one(self):
        world = ElectricalWorld(random.Random(3))
        self.assertEqual((0, 0.0, 0.0, None), (world.epoch, world.generator_output, world.main_bus_voltage, world.hold_kw))
        for n in range(1, 600):
            world.step()
            self.assertEqual((n - 1) % 255 + 1, world.epoch, "1-255: 0 is no reading")
            self.assertTrue(GENERATOR_KW[0] <= world.generator_output <= GENERATOR_KW[1])
            self.assertTrue(CONSUMPTION_KW[0] <= world.total_power_consumption <= CONSUMPTION_KW[1])
            self.assertTrue(MAIN_BUS_V[0] <= world.main_bus_voltage <= MAIN_BUS_V[1])
            self.assertTrue(AUX_BUS_V[0] <= world.aux_bus_voltage <= AUX_BUS_V[1])
            self.assertTrue(FREQUENCY_HZ[0] <= world.generator_frequency <= FREQUENCY_HZ[1])
            self.assertTrue(POWER_FACTOR[0] <= world.power_factor <= POWER_FACTOR[1])

    def test_the_readings_are_the_pythons_draws_in_their_order(self):
        """PowerManagementSystem seeded like the world draws the same six numbers a second: adjust_power_parameters'
        generator and consumption, then monitor()'s four bus readings."""
        import FMOFP.Systems.powerManagement.elec.powerManagementSystem as pms_module
        world = ElectricalWorld(random.Random(11))
        world.step()
        world.step()
        with mock.patch.object(pms_module, "DatabaseManager"):  # the SQLite the Python wrote its snapshots to
            pms = pms_module.PowerManagementSystem()
        random.seed(11)
        for _ in range(2):
            pms.adjust_power_parameters()
            pms.monitor()
        self.assertEqual((pms.generator_output, pms.total_power_consumption),
                         (world.generator_output, world.total_power_consumption))
        self.assertEqual((pms.pms_data["main_bus_voltage"], pms.pms_data["aux_bus_voltage"],
                          pms.pms_data["generator_frequency"], pms.pms_data["power_factor"]),
                         (world.main_bus_voltage, world.aux_bus_voltage, world.generator_frequency, world.power_factor))

    def test_the_hold_replaces_the_draw_and_keeps_the_sequence(self):
        held = ElectricalWorld(random.Random(7))
        free = ElectricalWorld(random.Random(7))
        hold = m.PwrGenCmd(override=True, generator_output=150.0, sequence=1)
        self.assertTrue(held.command(hold))
        self.assertFalse(held.command(hold), "the same hold again changes nothing")
        held.step()
        free.step()
        self.assertEqual(150.0, held.generator_output)
        self.assertNotEqual(150.0, free.generator_output)
        self.assertEqual(free.total_power_consumption, held.total_power_consumption, "the draw was made and discarded")
        self.assertEqual(free.power_factor, held.power_factor)
        self.assertTrue(held.message().generator_override)
        self.assertTrue(held.command(m.PwrGenCmd(override=True, generator_output=-5.0, sequence=2)))
        held.step()
        free.step()
        self.assertEqual(0.0, held.generator_output, "max(0, output), as set_generator_output had it")
        self.assertTrue(held.command(m.PwrGenCmd(override=False, sequence=3)))
        held.step()
        free.step()
        self.assertEqual(free.generator_output, held.generator_output, "released: the draw again, in step")
        self.assertFalse(held.message().generator_override)
        self.assertEqual(3, held.commands)

    def test_the_message_round_trips(self):
        world = ElectricalWorld(random.Random(5))
        for _ in range(20):
            world.step()
            status, words = world.message().encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED))
            self.assertEqual(m.PlantElectrical.WORDS, len(words))
            status, back = m.PlantElectrical.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertEqual((world.epoch, False), (back.epoch, back.generator_override))
            self.assertAlmostEqual(world.generator_output, back.generator_output, delta=0.006)
            self.assertAlmostEqual(world.total_power_consumption, back.total_power_consumption, delta=0.006)
            self.assertAlmostEqual(world.main_bus_voltage, back.main_bus_voltage, delta=0.006)
            self.assertAlmostEqual(world.aux_bus_voltage, back.aux_bus_voltage, delta=0.006)
            self.assertAlmostEqual(world.generator_frequency, back.generator_frequency, delta=0.006)
            self.assertAlmostEqual(world.power_factor, back.power_factor, delta=0.00006)

    def test_the_plant_carries_it_and_can_leave_it_out(self):
        model = PlantModel(seed=1, traffic=False, ground=False, weather=False)
        self.assertIsNotNone(model.electrical)
        model.electrical.step()
        self.assertEqual(1, model.electrical_message().epoch)
        dark = PlantModel(seed=1, traffic=False, ground=False, weather=False, electrical=False)
        self.assertIsNone(dark.electrical)
        self.assertEqual(m.PlantElectrical(), dark.electrical_message())
        # A generator command reaches the world through the plant.
        status, words = m.PlantGenCmd(payload=m.PwrGenCmd(override=True, generator_output=120.0, sequence=4)).encode()
        self.assertEqual(Status.OK, status)
        self.assertTrue(model.generator_command(words))
        self.assertFalse(dark.generator_command(words))
        model.electrical.step()
        self.assertEqual(120.0, model.electrical.generator_output)
        # Its own generator: the flight state of a seeded run is the same with or without the readings.
        with_electrical = PlantModel(seed=9, traffic=False, ground=False, weather=False)
        without = PlantModel(seed=9, traffic=False, ground=False, weather=False, electrical=False)
        for _ in range(20):
            with_electrical.adjust()
            without.adjust()
        self.assertEqual((with_electrical.altitude, with_electrical.heading), (without.altitude, without.heading))


if __name__ == "__main__":
    unittest.main()
