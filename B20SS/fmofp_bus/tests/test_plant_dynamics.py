"""Unit 36: the plant's flight dynamics (fmofp_plant.dynamics).

The simplified response is held to the frozen FlightDynamicsProcessor; the model's turn, climb and speed are the
plant's own world; the random walk is unchanged without --dynamics; and on the bus the real flight control
computer's surface commands fly the aircraft (needs FMOFP_BC and FMOFP_FCS).
"""

import os
import random
import subprocess
import tempfile
import threading
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import ControlSurface, Ssm
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_plant import dynamics as d
from fmofp_plant.plant import PlantModel, PlantTerminal

PORT_BASE = free_port_base(64250)
FCS_RT = m.FcsSurfaceStatus.RT


def frozen_processor():
    from FMOFP.Systems.flightManagementSys.flightControlSys.flight_dynamics_processor import FlightDynamicsProcessor
    return FlightDynamicsProcessor()


def surfaces(ailerons=0.0, elevator=0.0, rudder=0.0, ssm=Ssm.NORMAL):
    return m.FcsSurfaceStatus(ailerons_ssm=ssm, elevator_ssm=ssm, rudder_ssm=ssm, ailerons=ailerons,
                              elevator=elevator, rudder=rudder)


def quiet_model(**hold):
    model = PlantModel(seed=5, weather=False, traffic=False, ground=False, rf=False, esm=False, scan_sensors=False,
                       electrical=False, utilities=False, dynamics=True)
    model.hold = hold
    return model


def fly(model, seconds, thrust=58.0):
    for engine in model.engines.engines:
        engine.thrust = thrust
    for _ in range(int(round(seconds * 10))):
        model.fly(0.1)


class FrozenResponseTest(unittest.TestCase):
    def test_the_constants_are_the_frozen_classes(self):
        p = frozen_processor()
        self.assertEqual((d.MAX_ROLL_RATE, d.MAX_PITCH_RATE, d.MAX_YAW_RATE, d.MAX_G, d.MIN_G, d.MAX_ALPHA, d.MIN_ALPHA),
                         tuple(p.config[k] for k in ("max_roll_rate", "max_pitch_rate", "max_yaw_rate", "max_g_force",
                                                     "min_g_force", "max_alpha", "min_alpha")))
        self.assertEqual((d.ROLL_DAMPING, d.PITCH_DAMPING, d.YAW_DAMPING),
                         tuple(p.aircraft_params[k] for k in ("roll_damping", "pitch_damping", "yaw_damping")))
        self.assertTrue(p.config["use_simplified_model"], "the one path the class runs")

    def test_the_response_is_the_frozen_methods_step_for_step(self):
        p = frozen_processor()
        rng = random.Random(36)
        for _ in range(500):
            inputs = {k: rng.uniform(-1.2, 1.2) for k in ("aileron", "elevator", "rudder")}
            state = {"roll": rng.uniform(-200, 200), "pitch": rng.uniform(-30, 40), "yaw": rng.uniform(-10, 370),
                     "roll_rate": rng.uniform(-150, 150), "pitch_rate": rng.uniform(-80, 80),
                     "yaw_rate": rng.uniform(-40, 40), "airspeed": 450.0, "altitude": 10000.0}
            dt = rng.choice((0.02, 0.1, 0.5))
            self.assertEqual(p._calculate_simplified_response(inputs, state, dt),
                             d.simplified_response(inputs, state, dt))

    def test_the_frozen_elevator_sign_contradicts_its_comment(self):
        """The class pitches the nose down for a positive elevator: the plant hands it minus the FCS's elevator."""
        p = frozen_processor()
        out = p._calculate_simplified_response({"elevator": 0.5}, {"pitch": 0.0}, 0.1)
        self.assertLess(out["pitch"], 0.0)


class FlightModelTest(unittest.TestCase):
    def test_level_flight_stays_level(self):
        model = quiet_model()
        fly(model, 5.0, thrust=(model.speed - d.SPEED_AT_IDLE_KT) / d.SPEED_PER_THRUST_KT)
        self.assertEqual((0.0, 0.0, 0.0), (model.roll, model.pitch, model.heading))
        self.assertAlmostEqual(10000.0, model.altitude)
        self.assertAlmostEqual(500.0, model.speed)

    def test_nose_up_climbs_and_holds_its_pitch(self):
        model = quiet_model()
        model.dynamics.command(surfaces(elevator=10.0))
        fly(model, 1.0)
        pitched = model.pitch
        self.assertGreater(pitched, 3.0, "10 % nose up is a pitch rate of 6 deg/s")
        model.dynamics.command(surfaces())
        fly(model, 3.0)
        self.assertGreater(model.pitch, pitched, "the rate decays: the pitch holds where it got to")
        self.assertGreater(model.vertical_speed, 1000.0)
        self.assertGreater(model.altitude, 10100.0)

    def test_a_right_bank_turns_right_as_a_coordinated_turn(self):
        model = quiet_model()
        model.dynamics.command(surfaces(ailerons=20.0))
        fly(model, 1.0)
        model.dynamics.command(surfaces())
        fly(model, 2.0)
        self.assertGreater(model.roll, 20.0)
        heading = model.heading
        roll, speed = model.roll, model.speed
        fly(model, 1.0)
        import math
        rate = math.degrees(d.G * math.tan(math.radians(roll)) / (speed * d.MPS_PER_KT))
        self.assertAlmostEqual(rate, model.heading - heading, delta=0.2)

    def test_rudder_yaws_right_and_unvouched_surfaces_are_neutral(self):
        model = quiet_model()
        model.dynamics.command(surfaces(rudder=50.0))
        fly(model, 0.5)
        self.assertGreater(model.heading, 1.0)
        model.dynamics.command(surfaces(ailerons=100.0, elevator=100.0, rudder=100.0, ssm=Ssm.NO_COMPUTED_DATA))
        self.assertEqual({"aileron": 0.0, "elevator": 0.0, "rudder": 0.0}, model.dynamics.inputs)

    def test_the_speed_follows_the_thrust(self):
        model = quiet_model()
        fly(model, 120.0, thrust=20.0)
        self.assertAlmostEqual(d.thrust_speed_kt(20.0), model.speed, delta=5.0)

    def test_without_dynamics_the_walk_is_unchanged(self):
        walked = PlantModel(seed=9, weather=False, traffic=False, ground=False)
        flown = PlantModel(seed=9, weather=False, traffic=False, ground=False)
        for _ in range(50):
            walked.adjust()
            flown.fly(0.1)
        self.assertEqual((walked.altitude, walked.speed, walked.heading, walked.pitch, walked.roll),
                         (flown.altitude, flown.speed, flown.heading, flown.pitch, flown.roll))
        self.assertFalse(flown.surface_command([0] * m.PlantFcsSurfaces.WORDS), "the walk takes no surfaces")

    def test_the_relayed_message_is_taken(self):
        model = quiet_model()
        status, words = m.PlantFcsSurfaces(payload=surfaces(ailerons=25.0, elevator=-40.0)).encode()
        self.assertEqual(Status.OK, status)
        self.assertTrue(model.surface_command(words))
        self.assertEqual({"aileron": 0.25, "elevator": 0.4, "rudder": 0.0}, model.dynamics.inputs)


@needs("FMOFP_BC", "FMOFP_FCS")
class FcsFliesThePlantTest(unittest.TestCase):
    def test_a_surface_command_pitches_the_aircraft_up(self):
        script = os.path.join(tempfile.mkdtemp(prefix="fmofp_dynamics_"), "commands.txt")
        lines = []
        for frame, seq, position in ((60, 201, 20.0), (110, 202, 0.0)):
            status, words = m.FcsSurfaceCmd(cmd_seq=seq, surface=ControlSurface.ELEVATOR, position=position).encode()
            self.assertEqual(Status.OK, status)
            lines.append(f"{frame} {FCS_RT} {m.FcsSurfaceCmd.SUBADDRESS} " + " ".join(f"{w:04X}" for w in words))
        with open(script, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        model = quiet_model()
        plant = PlantTerminal(model, PORT_BASE)
        self.assertEqual(Status.OK, plant.init(), "plant port in use?")
        stop = threading.Event()
        pitches = []

        def pump():
            while not stop.is_set():
                if plant.poll(0.005):
                    pitches.append((plant.syncs, model.pitch, model.altitude))

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        fcs = subprocess.Popen([os.environ["FMOFP_FCS"], "--port-base", str(PORT_BASE), "--quiet"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        time.sleep(0.3)
        bc = subprocess.Popen([os.environ["FMOFP_BC"], "--rt", "27", "--rt", str(FCS_RT), "--port-base",
                               str(PORT_BASE), "--frames", "250", "--timeout-ms", "20", "--script", script],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        try:
            output, _ = bc.communicate(timeout=60)
        finally:
            stop.set()
            thread.join(timeout=2)
            fcs.kill()
            fcs.wait(timeout=10)
            fcs.stdout.close()
            plant.shutdown()
        self.assertEqual(0, bc.returncode, output)
        self.assertGreater(plant.surface_commands, 10, "FCS_SURFACE_STATUS reached the plant at 10 Hz")
        before = [p for f, p, _ in pitches if f < 60]
        after = [p for f, p, _ in pitches if f >= 200]
        self.assertTrue(before and after)
        self.assertEqual(0.0, max(abs(p) for p in before), "no command, no motion")
        self.assertGreater(min(after), 5.0, "20 % nose up for a second pitched the aircraft up, and it holds")
        self.assertGreater(pitches[-1][2], 10000.0, "and it climbs")


if __name__ == "__main__":
    unittest.main()
