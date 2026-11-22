"""The aircraft the plant flies with --dynamics (unit 36, ICD v1.28).

Upstream's FMS carried a flight-control package nothing ran: `flightControlSys/flight_dynamics_processor.py`'s
FlightDynamicsProcessor turned control inputs into the aircraft's motion. Its one path in use is
`_calculate_simplified_response` (`use_simplified_model` is always True, and the "full model" calls the same
method): each axis' rate goes first-order toward the input times the axis' maximum rate, with the damping
coefficient as the time constant; the attitude integrates the rates; the angle of attack, the sideslip and the load
factor follow from them. `simplified_response` below is that method step for step (test_plant_dynamics holds it to
the frozen class); it is world, the aircraft, so it lives in the plant.

What the class leaves out, the plant adds as world of its own (ICD README section 2): a banked aircraft turns (the
coordinated turn rate g tan(roll) / V), a pitched one climbs (vertical speed V sin(pitch)), and the speed goes
first-order toward the speed the engines' thrust holds, less the weight's component along the flight path.

The inputs are the flight control computer's commanded deflections, FCS_SURFACE_STATUS relayed as
PLANT_FCS_SURFACES: percent of travel, ailerons + roll right, elevator + nose up, rudder + nose right. The class
reads `aileron`, `elevator` and `rudder` from -1 to 1, rolls right for a positive aileron and yaws right for a
positive rudder, as the FCS's signs say, but pitches the nose *down* for a positive elevator (`target_pitch_rate =
-elevator * max_pitch_rate`, under a comment saying the elevator is positive when pulled back): so the plant hands it
minus the FCS's elevator, and a commanded nose-up raises the nose.
"""

import math

from fmofp_bus.icd.enums import Ssm

# FlightDynamicsProcessor._get_default_config() and its aircraft_params' damping coefficients.
MAX_ROLL_RATE = 120.0    # deg/s
MAX_PITCH_RATE = 60.0    # deg/s
MAX_YAW_RATE = 30.0      # deg/s
MAX_G = 9.0
MIN_G = -3.0
MAX_ALPHA = 25.0         # deg; the class limits the pitch attitude with it
MIN_ALPHA = -15.0
ROLL_DAMPING = 0.4       # s
PITCH_DAMPING = 0.6
YAW_DAMPING = 0.3

G = 9.80665              # m/s2
MPS_PER_KT = 0.514444
FT_PER_MIN_PER_KT = 101.2686  # 1 kt along the vertical in ft/min
SPEED_AT_IDLE_KT = 150.0      # the speed the engines hold at 0 % thrust (plant world, unit 36)
SPEED_PER_THRUST_KT = 5.0     # and the knots each percent adds: 440 kt at the demo's 58 %, 650 at 100 %
SPEED_TIME_CONSTANT_S = 20.0
MIN_SPEED_KT = 100.0          # the walk's limits (FlightControlComputer._adjust)
MAX_SPEED_KT = 1000.0
MAX_ALTITUDE_FT = 60000.0


def simplified_response(control_inputs, current_state, dt):
    """FlightDynamicsProcessor._calculate_simplified_response, step for step."""
    new_state = dict(current_state)
    aileron = control_inputs.get('aileron', 0.0)
    elevator = control_inputs.get('elevator', 0.0)
    rudder = control_inputs.get('rudder', 0.0)
    roll = current_state.get('roll', 0.0)
    pitch = current_state.get('pitch', 0.0)
    yaw = current_state.get('yaw', 0.0)
    roll_rate = current_state.get('roll_rate', 0.0)
    pitch_rate = current_state.get('pitch_rate', 0.0)
    yaw_rate = current_state.get('yaw_rate', 0.0)
    target_roll_rate = aileron * MAX_ROLL_RATE
    target_pitch_rate = -elevator * MAX_PITCH_RATE
    target_yaw_rate = rudder * MAX_YAW_RATE
    new_roll_rate = roll_rate + (target_roll_rate - roll_rate) * (1.0 - math.exp(-dt / ROLL_DAMPING))
    new_pitch_rate = pitch_rate + (target_pitch_rate - pitch_rate) * (1.0 - math.exp(-dt / PITCH_DAMPING))
    new_yaw_rate = yaw_rate + (target_yaw_rate - yaw_rate) * (1.0 - math.exp(-dt / YAW_DAMPING))
    new_roll = roll + new_roll_rate * dt
    new_pitch = pitch + new_pitch_rate * dt
    new_yaw = yaw + new_yaw_rate * dt
    new_roll = (new_roll + 180) % 360 - 180
    new_pitch = max(MIN_ALPHA, min(MAX_ALPHA, new_pitch))
    new_yaw = new_yaw % 360
    new_state['roll'] = new_roll
    new_state['pitch'] = new_pitch
    new_state['yaw'] = new_yaw
    new_state['roll_rate'] = new_roll_rate
    new_state['pitch_rate'] = new_pitch_rate
    new_state['yaw_rate'] = new_yaw_rate
    new_state['alpha'] = new_pitch * 0.1 + new_pitch_rate * 0.01
    new_state['beta'] = -new_yaw_rate * 0.1
    g_force_pitch = 1.0 + abs(new_pitch_rate) / MAX_PITCH_RATE * 4.0
    g_force_roll = 1.0 + (new_roll_rate / MAX_ROLL_RATE) ** 2 * 4.0
    new_state['g_force'] = max(MIN_G, min(MAX_G, max(g_force_pitch, g_force_roll)))
    return new_state


def thrust_speed_kt(thrust_pct):
    """The speed the engines' thrust holds in level flight (plant world)."""
    return SPEED_AT_IDLE_KT + SPEED_PER_THRUST_KT * max(0.0, thrust_pct)


class FlightDynamics:
    """The commanded deflections the aircraft flies, and its angular rates between steps."""

    def __init__(self):
        self.inputs = {'aileron': 0.0, 'elevator': 0.0, 'rudder': 0.0}
        self.roll_rate = 0.0
        self.pitch_rate = 0.0
        self.yaw_rate = 0.0
        self.beta = 0.0
        self.commands = 0

    def command(self, surfaces):
        """A PLANT_FCS_SURFACES payload (FCS_SURFACE_STATUS): percent of travel to the class's -1..1 inputs, a surface
        the flight control computer does not vouch for at neutral."""
        def share(value, ssm):
            return max(-1.0, min(1.0, value / 100.0)) if ssm == Ssm.NORMAL else 0.0
        self.inputs = {'aileron': share(surfaces.ailerons, surfaces.ailerons_ssm),
                       # the class pitches the nose down for a positive elevator; the FCS's positive is nose up
                       'elevator': -share(surfaces.elevator, surfaces.elevator_ssm),
                       'rudder': share(surfaces.rudder, surfaces.rudder_ssm)}
        self.commands += 1

    def step(self, model, dt, thrust_pct):
        """Flies the model's flight state for dt seconds: attitude and rates by the class, then the turn, the climb
        and the speed."""
        state = {'roll': model.roll, 'pitch': model.pitch, 'yaw': model.heading, 'roll_rate': self.roll_rate,
                 'pitch_rate': self.pitch_rate, 'yaw_rate': self.yaw_rate}
        new = simplified_response(self.inputs, state, dt)
        self.roll_rate, self.pitch_rate, self.yaw_rate = new['roll_rate'], new['pitch_rate'], new['yaw_rate']
        self.beta = new['beta']
        model.roll = new['roll']
        model.pitch = new['pitch']
        speed_mps = max(MIN_SPEED_KT, model.speed) * MPS_PER_KT
        turn_dps = math.degrees(G * math.tan(math.radians(max(-80.0, min(80.0, model.roll)))) / speed_mps)
        model.heading = (new['yaw'] + turn_dps * dt) % 360
        along = -G * math.sin(math.radians(model.pitch)) / MPS_PER_KT  # kt/s the weight takes off a climb
        model.speed += ((thrust_speed_kt(thrust_pct) - model.speed) / SPEED_TIME_CONSTANT_S + along) * dt
        model.speed = max(MIN_SPEED_KT, min(MAX_SPEED_KT, model.speed))
        model.vertical_speed = model.speed * math.sin(math.radians(model.pitch)) * FT_PER_MIN_PER_KT
        model.altitude = max(0.0, min(MAX_ALTITUDE_FT, model.altitude + model.vertical_speed * dt / 60.0))
        model.angle_of_attack = max(0.0, min(MAX_ALPHA, new['alpha']))
        model.g_force = new['g_force']
