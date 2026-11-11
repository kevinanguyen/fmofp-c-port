"""The plant terminal.

    py -m fmofp_plant [--port-base 51000] [--syncs 0] [--seed N] [--terrain-ft ELEVATION]
                      [--lat 0.0] [--lon 0.0]
                      [--gps-noise-m 3.0] [--gps-clock-bias-us 1.0] [--gps-outage]
                      [--no-weather] [--no-traffic] [--no-ground] [--no-electrical] [--no-utilities]
                      [--hold altitude=1500,vertical_speed=-4500,...] [--quiet]

PlantModel is Systems/flightControlSys/flightControlComputer.FlightControlComputer's
random walk, step for step, at the same 10 Hz, plus what the ported navigation needs
from the simulated world: a position that moves with the (held) speed and heading,
and a GPS receiver front end that measures pseudoranges to the 12-satellite
constellation of Systems/nav/gps/globalPositionSystem.py: a new epoch once a second, its ranges following the aircraft in between. The
position solver itself lives in the navigation terminal; the plant only produces
what the receiver would measure, noise included. It also owns the weather
(fmofp_plant.weather): the storm cells and stratiform area the radar's sensor
model renders, published as PLANT_WEATHER once a second; and the terrain
(fmofp_plant.terrain): the elevation profile ahead of the aircraft that the
terrain-following radar assesses, published as the PLANT_TERRAIN block ten times
a second. --terrain-ft flattens the world to one elevation. And it runs the two
engines (fmofp_plant.engine): engineControlUnit.py's engine model at its 2 Hz,
at the thrust the engine computer commands (PLANT_THRUST_CMD, relayed from the
engine terminal's ENG_THRUST_CMD), published as PLANT_ENGINE ten times a second.
And it flies the air traffic (fmofp_plant.traffic): the aircraft the targeting and
AEWC radars generated, published as the PLANT_TRAFFIC block five times a second
as the radars' antennas would measure them. And it holds the ground scene
(fmofp_plant.ground): the training range the synthetic aperture radar images,
laid out along the northbound track from home, published as the PLANT_GROUND
block once a second with its vehicles and ship moving. And it reads the electrical
system (fmofp_plant.electrical): the generator output, the consumption, the bus
voltages, the frequency and the power factor PowerManagementSystem drew, published
as PLANT_ELECTRICAL once a second, the generator held where the power management
terminal commands it (PLANT_GEN_CMD).

--hold freezes named quantities at fixed values, which is how the tests put the
aircraft into a known situation.
"""

import argparse
import math
import random
import sys

from fmofp_bus.block import BlockPublisher
from fmofp_bus.icd.blocks import PlantGround, PlantSensorScan, PlantTerrain, PlantTraffic
from fmofp_bus.icd.enums import GearPosition, Ssm
from fmofp_bus.icd.messages import (PlantAirframe, PlantCabin, PlantElectrical, PlantEsm, PlantGenCmd, PlantGps,
                                    PlantHydraulics, PlantInjectContact, PlantInjectWeather, PlantRf, PlantSensors,
                                    PlantThrustCmd, PlantWeather)
from fmofp_bus.rt_process import RtProcess
from fmofp_bus.status import Status
from fmofp_plant.electrical import ElectricalWorld
from fmofp_plant.utilities import AirframeWorld, CabinWorld, HydraulicsWorld
from fmofp_plant.engine import ECU_DT, ECU_HZ, EngineWorld
from fmofp_plant.ground import GroundScene
from fmofp_plant.esm import EsmWorld
from fmofp_plant.rf import RfWorld
from fmofp_plant.sensors import SensorScanWorld
from fmofp_plant.terrain import FlatTerrain, HillTerrain, profile_message
from fmofp_plant.traffic import TrafficWorld, ownship_enu, ownship_velocity
from fmofp_plant.weather import WeatherWorld

PLANT_RT = PlantSensors.RT
SYNC_HZ = 50
WALK_HZ = 10  # the FCC's update rate
SYNCS_PER_WALK = SYNC_HZ // WALK_HZ
GPS_HZ = 1  # GPSSystem.UPDATE_INTERVAL_S
SYNCS_PER_GPS = SYNC_HZ // GPS_HZ
WEATHER_HZ = 1
SYNCS_PER_WEATHER = SYNC_HZ // WEATHER_HZ
TERRAIN_HZ = 5  # a new profile every 0.2 s; its four segments take 0.16 s at the 25 Hz of PLANT_TERRAIN (v1.10)
SYNCS_PER_TERRAIN = SYNC_HZ // TERRAIN_HZ
SYNCS_PER_ECU_STEP = SYNC_HZ // ECU_HZ  # the engine model's own rate
ENGINE_HZ = 10  # PLANT_ENGINE's rate; a reading stays current for three periods at its consumer
SYNCS_PER_ENGINE = SYNC_HZ // ENGINE_HZ
TRAFFIC_HZ = 5  # PLANT_TRAFFIC's rate; its four segments take 0.16 s at the block's 25 Hz
SYNCS_PER_TRAFFIC = SYNC_HZ // TRAFFIC_HZ
GROUND_HZ = 1  # PLANT_GROUND: the movers have moved; its four segments take 20 frames at the block's 10 Hz
SYNCS_PER_GROUND = SYNC_HZ // GROUND_HZ
RF_HZ = 1  # PLANT_RF: CommsService._simulate ran once a second
SYNCS_PER_RF = SYNC_HZ // RF_HZ
ESM_STEP_FRAMES = 10  # PLANT_ESM: a new detection set every 0.2 s, as often as SensorDataFusion read its ESM sensor (the
#                       defensive service read its own every half second and takes the latest set; 25 until v1.18)
SCAN_STEP_FRAMES = 10  # PLANT_SENSOR_SCAN: a new scan set every 0.2 s, SensorDataFusion's poll; three segments, six frames at 25 Hz
ELECTRICAL_HZ = 1  # PLANT_ELECTRICAL: PowerManagementSystem's loop read its generator and buses once a second
SYNCS_PER_ELECTRICAL = SYNC_HZ // ELECTRICAL_HZ
CABIN_HZ = 2  # PLANT_CABIN: ECSControl's loop read the cabin twice a second (polled five times, v1.22)
SYNCS_PER_CABIN = SYNC_HZ // CABIN_HZ
UTILITIES_HZ = 1  # PLANT_HYDRAULICS and PLANT_AIRFRAME: their controllers' loops ran once a second
SYNCS_PER_UTILITIES = SYNC_HZ // UTILITIES_HZ

HOLDABLE = ("cabin_temperature", "cabin_pressure", "cabin_air_quality", "primary_psi", "backup_psi",
            "wing_root_strain", "fuselage_strain", "leading_edge_temp",
            "altitude", "speed", "heading", "pitch", "roll", "vertical_speed", "angle_of_attack", "g_force",
            "flaps", "latitude", "longitude")

# Where the Python aircraft lived: flightManagementSystem's navigation dict starts
# at latitude 0, longitude 0, and the GPS truth followed it, so every fix in the
# frozen Python was made here. It is also a spot the 12-satellite constellation
# serves well (five satellites, a fix good to a few metres). The INS's starting
# point, 35.4147 N 97.3866 W, was never used by anything, and from there the
# constellation shows four coplanar satellites whose fixes are off by kilometres.
HOME_LATITUDE = 0.0
HOME_LONGITUDE = 0.0

# WGS-84 and the constellation, as globalPositionSystem.py has them.
WGS84_A = 6_378_137.0
WGS84_B = 6_356_752.314_245
WGS84_E2 = 1 - (WGS84_B / WGS84_A) ** 2
SPEED_OF_LIGHT = 299_792_458.0
GPS_ORBIT_RADIUS_M = 26_560_000.0
GPS_INCLINATION = math.radians(55.0)
GPS_MIN_ELEVATION_DEG = 5.0
GPS_SATELLITES = 12


def build_constellation():
    """globalPositionSystem._build_constellation(): [(id, (x, y, z) m, clock bias s)]."""
    sats = []
    sat_id = 1
    for plane in range(3):
        raan = math.radians(plane * 120)
        for slot in range(4):
            u = math.radians(slot * 90)
            x_p = GPS_ORBIT_RADIUS_M * math.cos(u)
            y_p = GPS_ORBIT_RADIUS_M * math.sin(u)
            x_i = x_p
            y_i = y_p * math.cos(GPS_INCLINATION)
            z_i = y_p * math.sin(GPS_INCLINATION)
            x = x_i * math.cos(raan) - y_i * math.sin(raan)
            y = x_i * math.sin(raan) + y_i * math.cos(raan)
            z = z_i
            clock_bias = (sat_id * 1.3e-9) % 1e-6
            sats.append((sat_id, (x, y, z), clock_bias))
            sat_id += 1
    return sats


def wgs84_to_ecef(lat_deg, lon_deg, alt_ft):
    """GPSReceiver.update_true_position(): geodetic degrees and feet to ECEF metres."""
    alt_m = alt_ft * 0.3048
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
    x = (n + alt_m) * math.cos(lat) * math.cos(lon)
    y = (n + alt_m) * math.cos(lat) * math.sin(lon)
    z = (n * (1 - WGS84_E2) + alt_m) * math.sin(lat)
    return x, y, z


def elevation_deg(receiver, satellite):
    """GPSReceiver._is_visible()'s elevation angle; 90 at the Earth's centre, as that code behaves."""
    rx, ry, rz = receiver
    sx, sy, sz = satellite
    dx, dy, dz = sx - rx, sy - ry, sz - rz
    r_mag = math.sqrt(rx ** 2 + ry ** 2 + rz ** 2)
    if r_mag == 0:
        return 90.0
    nx, ny, nz = rx / r_mag, ry / r_mag, rz / r_mag
    d_mag = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    if d_mag == 0:
        return -90.0
    cos_el = (dx * nx + dy * ny + dz * nz) / d_mag
    return math.degrees(math.asin(max(-1.0, min(1.0, cos_el))))


class PlantModel:
    """FlightControlComputer._adjust(), including its clamps and starting state, plus position and GPS."""

    def __init__(self, seed=None, terrain=None, latitude=HOME_LATITUDE, longitude=HOME_LONGITUDE,
                 gps_noise_m=3.0, gps_clock_bias_us=1.0, gps_outage=False, weather=True, traffic=True,
                 ground=True, rf=True, satellite_after_s=None, esm=True, scan_sensors=True, electrical=True,
                 utilities=True):
        self.rng = random.Random(seed)
        # The weather draws from its own generator so adding it changed nothing else about a seeded run.
        self.weather = WeatherWorld(random.Random(None if seed is None else seed ^ 0x5745)) if weather else None
        self.weather_seq = 0
        self.terrain = HillTerrain() if terrain is None else terrain
        self.terrain_seq = 0
        # The engines draw from their own generator too, for the same reason.
        self.engines = EngineWorld(random.Random(None if seed is None else seed ^ 0x454E47))
        # And the traffic from its own.
        self.traffic = TrafficWorld(random.Random(None if seed is None else seed ^ 0x545246)) if traffic else None
        self.traffic_seq = 0
        # And the ground scene: fixed, laid out around home (a GroundScene of the caller's, True for the default).
        if isinstance(ground, GroundScene):
            self.ground = ground
        else:
            self.ground = GroundScene(home_latitude=latitude, home_longitude=longitude) if ground else None
        self.ground_seq = 0
        # And the RF environment the communications terminal measures, from its own generator (v1.16).
        self.rf = RfWorld(random.Random(None if seed is None else seed ^ 0x5246),
                          satellite_after_s=satellite_after_s) if rf else None
        # And the ESM intercepts the defensive systems terminal receives, from its own generator (v1.17).
        self.esm = EsmWorld(random.Random(None if seed is None else seed ^ 0x45534D)) if esm else None
        # And the five scanning sensors the sensor data fusion asked, from their own generator (v1.18).
        self.scan_world = SensorScanWorld(random.Random(None if seed is None else seed ^ 0x534E53)) if scan_sensors else None
        # And the electrical system the power management terminal measures, from its own generator (v1.19).
        self.electrical = ElectricalWorld(random.Random(None if seed is None else seed ^ 0x454C45)) if electrical else None
        # And the cabin, the hydraulic pressures and the airframe sensors the four small utility terminals
        # measure, each from its own generator (v1.22).
        self.cabin = CabinWorld(random.Random(None if seed is None else seed ^ 0x434142)) if utilities else None
        self.hydraulics = HydraulicsWorld(random.Random(None if seed is None else seed ^ 0x485944)) if utilities else None
        self.airframe = AirframeWorld(random.Random(None if seed is None else seed ^ 0x414652)) if utilities else None
        self.altitude = 10000.0       # feet
        self.speed = 500.0            # knots
        self.heading = 0.0            # degrees true
        self.pitch = 0.0              # degrees
        self.roll = 0.0               # degrees
        self.vertical_speed = 0.0     # feet/min
        self.angle_of_attack = 2.0    # degrees
        self.g_force = 1.0
        self.flaps = 0.0              # degrees
        self.landing_gear = "up"
        self.latitude = float(latitude)    # degrees, WGS-84
        self.longitude = float(longitude)
        self.home_latitude = float(latitude)   # the origin of the traffic's east-north-up frame
        self.home_longitude = float(longitude)
        self.gps_noise_m = float(gps_noise_m)        # GPSReceiver._measurement_noise_m
        self.gps_clock_bias_s = float(gps_clock_bias_us) * 1e-6
        self.gps_outage = bool(gps_outage)
        self.satellites = build_constellation()
        self.gps_epoch = 0
        self.gps_noise = None  # per satellite, drawn by new_gps_epoch()
        self.hold = {}
        if self.traffic is not None:
            self.traffic.populate(self.ownship_enu())

    def ownship_enu(self):
        """Metres east, north and up of the aircraft from home, the traffic's frame."""
        return ownship_enu(self.value("latitude"), self.value("longitude"), self.value("altitude"),
                           self.home_latitude, self.home_longitude)

    def ownship_velocity(self):
        return ownship_velocity(self.value("speed"), self.value("heading"), self.value("vertical_speed"))

    def adjust(self):
        """One 10 Hz step of the FCC's random walk."""
        u = self.rng.uniform
        self.altitude += u(-50, 50)
        self.speed += u(-5, 5)
        self.heading = (self.heading + u(-1, 1)) % 360
        self.pitch += u(-0.5, 0.5)
        self.roll += u(-0.5, 0.5)
        self.vertical_speed = u(-500, 500)
        self.angle_of_attack = max(0, self.angle_of_attack + u(-0.2, 0.2))
        self.g_force = max(0.5, min(9.0, self.g_force + u(-0.05, 0.05)))

        self.altitude = max(0, min(60000, self.altitude))
        self.speed = max(100, min(1000, self.speed))
        self.pitch = max(-45, min(45, self.pitch))
        self.roll = max(-60, min(60, self.roll))
        self.angle_of_attack = min(25, self.angle_of_attack)

    def move(self, dt):
        """Advance the position by the (held) speed and heading for dt seconds.

        The same dead-reckoning rates flightManagementSystem.update_flight_data
        derived (knots to feet per second to degrees per second), so the
        navigation terminal's prediction between fixes matches the motion.
        """
        gs_kts = self.value("speed")
        heading_rad = math.radians(self.value("heading"))
        gs_dps_lat = (gs_kts * 1.68781) / (111_000 / 0.3048)
        gs_dps_lon = gs_dps_lat / max(0.001, math.cos(math.radians(self.latitude)))
        self.latitude += gs_dps_lat * math.cos(heading_rad) * dt
        self.longitude += gs_dps_lon * math.sin(heading_rad) * dt
        self.latitude = max(-90.0, min(90.0, self.latitude))
        self.longitude = (self.longitude + 180.0) % 360.0 - 180.0
        if self.weather is not None:
            self.weather.update(dt)
        if self.traffic is not None:
            self.traffic.update(dt, self.ownship_enu())
        if self.ground is not None:
            self.ground.update(dt)

    def value(self, name):
        return self.hold.get(name, getattr(self, name))

    def sensors(self):
        """PLANT_SENSORS for the current state, every quantity NORMAL."""
        s = PlantSensors()
        for ssm in ("altitude_ssm", "airspeed_ssm", "pitch_ssm", "roll_ssm", "heading_ssm", "vertical_speed_ssm",
                    "aoa_ssm", "g_ssm", "flaps_ssm"):
            setattr(s, ssm, Ssm.NORMAL)
        s.gear = GearPosition.DOWN if self.landing_gear == "down" else GearPosition.UP
        s.altitude = self.value("altitude")
        s.airspeed = self.value("speed")
        s.vertical_speed = self.value("vertical_speed")
        s.pitch = self.value("pitch")
        s.roll = self.value("roll")
        s.heading = self.value("heading")
        s.angle_of_attack = self.value("angle_of_attack")
        s.g_force = self.value("g_force")
        s.flaps = self.value("flaps")
        return s

    def terrain_message(self):
        """PLANT_TERRAIN for the current position and heading: the profile the radar's antenna would measure."""
        self.terrain_seq = (self.terrain_seq + 1) % 256
        return profile_message(self.terrain, self.value("latitude"), self.value("longitude"), self.value("heading"),
                               self.terrain_seq)

    def weather_message(self):
        """PLANT_WEATHER for the current weather; an empty sky when the weather is off."""
        if self.weather is not None:
            return self.weather.message()
        m = PlantWeather()
        self.weather_seq = (self.weather_seq + 1) % 256
        m.weather_seq = self.weather_seq
        return m

    def engine_message(self):
        """PLANT_ENGINE: what the engines' sensors read now."""
        return self.engines.message()

    def traffic_message(self):
        """PLANT_TRAFFIC as the radars' antennas would measure the traffic now; an empty sky when it is off."""
        if self.traffic is not None:
            return self.traffic.message(self.ownship_enu(), self.ownship_velocity())
        self.traffic_seq = (self.traffic_seq + 1) % 256
        return PlantTraffic(traffic_seq=self.traffic_seq)

    def ground_message(self):
        """PLANT_GROUND with the movers where they are now; bare ground when the scene is off."""
        if self.ground is not None:
            return self.ground.message()
        self.ground_seq = (self.ground_seq + 1) % 256
        return PlantGround(scene_seq=self.ground_seq)

    def rf_message(self):
        """PLANT_RF: the field, the satellite and the link; a silent world without an RF model."""
        return self.rf.message() if self.rf is not None else PlantRf()

    def esm_message(self):
        return self.esm.message() if self.esm is not None else PlantEsm()

    def scan_block(self):
        return self.scan_world.block() if self.scan_world is not None else PlantSensorScan()

    def electrical_message(self):
        """PLANT_ELECTRICAL: the last reading; epoch 0 (no reading) without an electrical model."""
        return self.electrical.message() if self.electrical is not None else PlantElectrical()

    def cabin_message(self):
        """PLANT_CABIN: the last reading, a held quantity where a test asks; epoch 0 without the model."""
        return self.cabin.message(self.hold) if self.cabin is not None else PlantCabin()

    def hydraulics_message(self):
        """PLANT_HYDRAULICS: the last reading; epoch 0 without the model."""
        return self.hydraulics.message(self.hold) if self.hydraulics is not None else PlantHydraulics()

    def airframe_message(self):
        """PLANT_AIRFRAME: the last reading; epoch 0 without the model."""
        return self.airframe.message(self.hold) if self.airframe is not None else PlantAirframe()

    def step_utilities(self, cabin=False, others=False):
        """The utility worlds' passes: the cabin's (2 Hz) and the hydraulics' and airframe's (1 Hz), from the
        flight state now."""
        if cabin and self.cabin is not None:
            self.cabin.step()
        if others and self.hydraulics is not None:
            self.hydraulics.step()
        if others and self.airframe is not None:
            self.airframe.step(self.value("g_force"), self.value("altitude"))

    def generator_command(self, words):
        """A PLANT_GEN_CMD received: the generator held where the power management terminal asks. True when the
        hold changed."""
        status, cmd = PlantGenCmd.decode(words)
        if status != Status.OK or self.electrical is None:
            return False
        return self.electrical.command(cmd.payload)

    def inject_contact(self, words):
        """A PLANT_INJECT_CONTACT received (the scenario engine, v1.23): an aircraft into the traffic, placed
        relative to the aircraft now. True when applied (there is traffic and the id is not 0)."""
        status, cmd = PlantInjectContact.decode(words)
        if status != Status.OK or self.traffic is None or cmd.contact_id == 0:
            return False
        self.traffic.inject(cmd.contact_id, self.ownship_enu(), cmd.x_km, cmd.y_km, cmd.alt_ft,
                            (cmd.velocity_east, cmd.velocity_north, cmd.velocity_up), cmd.rcs, cmd.is_stealth)
        return True

    def inject_weather(self, words):
        """A PLANT_INJECT_WEATHER received (v1.23): a storm cell into the sky at the bearing and range of the
        east/north offset given. True when applied (there is weather)."""
        status, cmd = PlantInjectWeather.decode(words)
        if status != Status.OK or self.weather is None:
            return False
        azimuth = math.degrees(math.atan2(cmd.x_km, cmd.y_km)) % 360.0
        self.weather.inject(azimuth, math.hypot(cmd.x_km, cmd.y_km), cmd.size, cmd.reflectivity)
        return True

    def thrust_command(self, words):
        """A PLANT_THRUST_CMD received: the engines take the engine computer's command. True when applied."""
        status, cmd = PlantThrustCmd.decode(words)
        if status != Status.OK:
            return False
        return self.engines.command(cmd.payload)

    def true_position_ecef(self):
        return wgs84_to_ecef(self.value("latitude"), self.value("longitude"), self.value("altitude"))

    def new_gps_epoch(self):
        """Starts a GPS epoch: the epoch count moves on and each satellite's measurement noise is drawn once
        (GPSReceiver._pseudorange drew it per measurement; the solver sees one consistent set per epoch)."""
        self.gps_epoch = (self.gps_epoch + 1) % 16
        self.gps_noise = {sat_id: self.rng.gauss(0.0, self.gps_noise_m) for sat_id, _, _ in self.satellites}

    def gps_message(self):
        """PLANT_GPS as the receiver's output register reads now: this epoch's noise on the geometric ranges from
        the present true position, so a fix is current whenever the bus controller polls it, in whatever frame
        the schedule gives that poll (the navigation solves an epoch once, when its count changes).

        A satellite counts as visible at 5 degrees of elevation or more, seen from
        the true position (GPSReceiver._is_visible). The pseudorange is the
        geometric range plus c times (receiver clock bias minus satellite clock
        bias) plus the epoch's Gaussian noise (GPSReceiver._pseudorange). During
        an outage no satellite is visible.
        """
        if self.gps_noise is None:
            self.new_gps_epoch()
        g = PlantGps()
        g.epoch = self.gps_epoch
        if self.gps_outage:
            return g
        receiver = self.true_position_ecef()
        mask = 0
        for sat_id, position, sat_bias in self.satellites:
            if elevation_deg(receiver, position) < GPS_MIN_ELEVATION_DEG:
                continue
            geometric = math.dist(receiver, position)
            pseudorange = geometric + SPEED_OF_LIGHT * (self.gps_clock_bias_s - sat_bias) + self.gps_noise[sat_id]
            setattr(g, f"pseudorange_{sat_id}", pseudorange)
            mask |= 1 << (sat_id - 1)
        g.visible_mask = mask
        return g

    def gps(self):
        """PLANT_GPS for a new epoch, measured now."""
        self.new_gps_epoch()
        return self.gps_message()


class PlantTerminal:
    """RT 27 on the bus: walks the model at 10 Hz, publishes PLANT_SENSORS every frame, PLANT_WEATHER once a
    second, PLANT_GPS with a new epoch once a second and its ranges refreshed at the walk rate, the
    PLANT_TERRAIN block ten times a second, PLANT_ENGINE ten times a second (the engine model steps at 2 Hz) and
    the PLANT_GROUND block once a second, PLANT_RF once a second (the RF environment, stepped at that
    rate), PLANT_ESM every 0.2 s (a new set of intercepts), the PLANT_SENSOR_SCAN block every 0.2 s (a new
    set of scans), PLANT_ELECTRICAL once a second (a new reading), PLANT_CABIN twice a second and
    PLANT_HYDRAULICS and PLANT_AIRFRAME once a second (v1.22), and takes the engine computer's thrust
    command from PLANT_THRUST_CMD and the power management terminal's generator hold from PLANT_GEN_CMD."""

    def __init__(self, model, port_base=51000):
        self.model = model
        self.process = RtProcess()
        self.port_base = port_base
        self.syncs = 0
        self.publish_failures = 0
        self.thrust_commands = 0
        self.generator_commands = 0
        self.injections = 0
        self.terrain_block = BlockPublisher(PlantTerrain.MAX_PAYLOAD_WORDS)
        self.traffic_block = BlockPublisher(PlantTraffic.MAX_PAYLOAD_WORDS)
        self.ground_block = BlockPublisher(PlantGround.MAX_PAYLOAD_WORDS)
        self.sensor_block = BlockPublisher(PlantSensorScan.MAX_PAYLOAD_WORDS)

    def init(self):
        status = self.process.init(PLANT_RT, self.port_base)
        if status == Status.OK:
            self.publish()
            self.publish_gps()
            self.publish_weather()
            self.publish_terrain()
            self.serve_terrain()
            self.publish_engine()
            self.publish_traffic()
            self.serve_traffic()
            self.publish_ground()
            self.serve_ground()
            self.publish_rf()
            self.publish_esm()
            self.publish_sensors()
            self.serve_sensors()
            self.publish_electrical()
            self.publish_utilities()
        return status

    def _load(self, message):
        status, words = message.encode()
        if status not in (Status.OK, Status.CLAMPED):
            self.publish_failures += 1
            return
        self.process.terminal.set_transmit(message.SUBADDRESS, words)

    def publish(self):
        self._load(self.model.sensors())

    def publish_gps(self):
        self._load(self.model.gps_message())

    def publish_weather(self):
        self._load(self.model.weather_message())

    def publish_engine(self):
        self._load(self.model.engine_message())

    def take_thrust_command(self):
        """Applies a PLANT_THRUST_CMD that arrived since the last frame."""
        status, words, fresh = self.process.terminal.get_received(PlantThrustCmd.SUBADDRESS)
        if status == Status.OK and fresh and self.model.thrust_command(words):
            self.thrust_commands += 1

    def publish_terrain(self):
        status, words = self.model.terrain_message().encode()
        if status not in (Status.OK, Status.CLAMPED):
            self.publish_failures += 1
            return
        if self.terrain_block.publish(self.process.terminal, PlantTerrain.SEGMENT_SUBADDRESS, words) != Status.OK:
            self.publish_failures += 1

    def serve_terrain(self):
        self.terrain_block.serve(self.process.terminal, PlantTerrain.DESCRIPTOR_SUBADDRESS,
                                 PlantTerrain.SEGMENT_SUBADDRESS)

    def publish_traffic(self):
        status, words = self.model.traffic_message().encode()
        if status not in (Status.OK, Status.CLAMPED):
            self.publish_failures += 1
            return
        if self.traffic_block.publish(self.process.terminal, PlantTraffic.SEGMENT_SUBADDRESS, words) != Status.OK:
            self.publish_failures += 1

    def serve_traffic(self):
        self.traffic_block.serve(self.process.terminal, PlantTraffic.DESCRIPTOR_SUBADDRESS,
                                 PlantTraffic.SEGMENT_SUBADDRESS)

    def publish_rf(self):
        self._load(self.model.rf_message())

    def publish_esm(self):
        self._load(self.model.esm_message())

    def publish_electrical(self):
        self._load(self.model.electrical_message())

    def publish_utilities(self):
        self._load(self.model.cabin_message())
        self._load(self.model.hydraulics_message())
        self._load(self.model.airframe_message())

    def take_generator_command(self):
        """Applies a PLANT_GEN_CMD that arrived since the last frame."""
        status, words, fresh = self.process.terminal.get_received(PlantGenCmd.SUBADDRESS)
        if status == Status.OK and fresh and self.model.generator_command(words):
            self.generator_commands += 1

    def take_injections(self):
        """Applies the scenario engine's injections that arrived since the last frame (v1.23)."""
        for cls, apply in ((PlantInjectContact, self.model.inject_contact),
                           (PlantInjectWeather, self.model.inject_weather)):
            status, words, fresh = self.process.terminal.get_received(cls.SUBADDRESS)
            if status == Status.OK and fresh and apply(words):
                self.injections += 1

    def publish_ground(self):
        status, words = self.model.ground_message().encode()
        if status not in (Status.OK, Status.CLAMPED):
            self.publish_failures += 1
            return
        if self.ground_block.publish(self.process.terminal, PlantGround.SEGMENT_SUBADDRESS, words) != Status.OK:
            self.publish_failures += 1

    def serve_ground(self):
        self.ground_block.serve(self.process.terminal, PlantGround.DESCRIPTOR_SUBADDRESS, PlantGround.SEGMENT_SUBADDRESS)

    def publish_sensors(self):
        status, words = self.model.scan_block().encode()
        if status not in (Status.OK, Status.CLAMPED):
            self.publish_failures += 1
            return
        if self.sensor_block.publish(self.process.terminal, PlantSensorScan.SEGMENT_SUBADDRESS, words) != Status.OK:
            self.publish_failures += 1

    def serve_sensors(self):
        self.sensor_block.serve(self.process.terminal, PlantSensorScan.DESCRIPTOR_SUBADDRESS,
                                PlantSensorScan.SEGMENT_SUBADDRESS)

    def poll(self, timeout_s=0.1):
        """One iteration of the loop: handle a datagram, step on sync. Returns True on a sync."""
        self.process.poll(timeout_s)
        got, _ = self.process.terminal.take_sync()
        if not got:
            if self.process.terminal.take_reset_request():
                self.terrain_block = BlockPublisher(PlantTerrain.MAX_PAYLOAD_WORDS)
                self.traffic_block = BlockPublisher(PlantTraffic.MAX_PAYLOAD_WORDS)
                self.ground_block = BlockPublisher(PlantGround.MAX_PAYLOAD_WORDS)
                self.sensor_block = BlockPublisher(PlantSensorScan.MAX_PAYLOAD_WORDS)
                self.publish()
                self.publish_gps()
                self.publish_weather()
                self.publish_terrain()
                self.serve_terrain()
                self.publish_engine()
                self.publish_traffic()
                self.serve_traffic()
                self.publish_ground()
                self.serve_ground()
                self.publish_rf()
                self.publish_esm()
                self.publish_sensors()
                self.serve_sensors()
                self.publish_electrical()
                self.publish_utilities()
            return False
        self.syncs += 1
        self.take_thrust_command()
        self.take_generator_command()
        self.take_injections()
        if self.syncs % SYNCS_PER_ECU_STEP == 0:
            self.model.engines.step(ECU_DT)
        if self.syncs % SYNCS_PER_ENGINE == 0:
            self.publish_engine()
        if self.syncs % SYNCS_PER_GPS == 0:
            self.model.new_gps_epoch()
        if self.syncs % SYNCS_PER_WALK == 0:
            self.model.adjust()
            self.model.move(1.0 / WALK_HZ)
            self.publish_gps()  # the receiver's output follows the aircraft; the epoch count says when a fix is new
        if self.syncs % SYNCS_PER_WEATHER == 0:
            self.publish_weather()
        if self.syncs % SYNCS_PER_TERRAIN == 0:
            self.publish_terrain()
        if self.syncs % SYNCS_PER_TRAFFIC == 0:
            self.publish_traffic()
        if self.syncs % SYNCS_PER_GROUND == 0:
            self.publish_ground()
        if self.syncs % SYNCS_PER_RF == 0:
            if self.model.rf is not None:
                self.model.rf.step()
            self.publish_rf()
        if self.syncs % ESM_STEP_FRAMES == 0:
            if self.model.esm is not None:
                self.model.esm.step()
            self.publish_esm()
        if self.syncs % SCAN_STEP_FRAMES == 0:
            if self.model.scan_world is not None:
                self.model.scan_world.step()
            self.publish_sensors()
        if self.syncs % SYNCS_PER_ELECTRICAL == 0:
            if self.model.electrical is not None:
                self.model.electrical.step()
            self.publish_electrical()
        if self.syncs % SYNCS_PER_CABIN == 0 or self.syncs % SYNCS_PER_UTILITIES == 0:
            self.model.step_utilities(cabin=self.syncs % SYNCS_PER_CABIN == 0,
                                      others=self.syncs % SYNCS_PER_UTILITIES == 0)
            self.publish_utilities()
        self.serve_terrain()
        self.serve_traffic()
        self.serve_ground()
        self.serve_sensors()
        self.publish()
        return True

    def shutdown(self):
        self.process.shutdown()


def parse_hold(text):
    hold = {}
    for item in filter(None, (text or "").split(",")):
        name, _, value = item.partition("=")
        if name not in HOLDABLE:
            raise argparse.ArgumentTypeError(f"cannot hold '{name}'; one of {', '.join(HOLDABLE)}")
        hold[name] = float(value)
    return hold


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port-base", type=int, default=51000)
    parser.add_argument("--syncs", type=int, default=0, help="exit after this many frames (0 = run until killed)")
    parser.add_argument("--seed", type=int, default=None, help="random seed, for repeatable runs")
    parser.add_argument("--terrain-ft", type=float, default=None,
                        help="flat terrain at this elevation everywhere (default: the hills of fmofp_plant.terrain)")
    parser.add_argument("--lat", type=float, default=HOME_LATITUDE, help="starting latitude, degrees")
    parser.add_argument("--lon", type=float, default=HOME_LONGITUDE, help="starting longitude, degrees")
    parser.add_argument("--gps-noise-m", type=float, default=3.0, help="pseudorange noise, 1 sigma")
    parser.add_argument("--gps-clock-bias-us", type=float, default=1.0, help="true receiver clock bias")
    parser.add_argument("--gps-outage", action="store_true", help="no satellite is ever visible")
    parser.add_argument("--no-weather", action="store_true", help="a clear sky: PLANT_WEATHER carries no cells or area")
    parser.add_argument("--no-traffic", action="store_true", help="an empty sky: PLANT_TRAFFIC carries no aircraft")
    parser.add_argument("--no-ground", action="store_true", help="bare ground: PLANT_GROUND carries no features")
    parser.add_argument("--no-rf", action="store_true", help="a silent sky: PLANT_RF carries no field and no satellite")
    parser.add_argument("--no-esm", action="store_true", help="no emitters: PLANT_ESM carries no signals")
    parser.add_argument("--no-sensors", action="store_true", help="blind sensors: PLANT_SENSOR_SCAN carries no detections")
    parser.add_argument("--no-electrical", action="store_true",
                        help="no electrical readings: PLANT_ELECTRICAL carries epoch 0 (the power terminal waits)")
    parser.add_argument("--no-utilities", action="store_true",
                        help="no cabin, hydraulic or airframe readings: their messages carry epoch 0")
    parser.add_argument("--satellite-after", type=float, default=None,
                        help="a satellite comes into view after this many seconds instead of by chance")
    parser.add_argument("--hold", type=parse_hold, default={}, help="name=value,... held constant")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    terrain = None if args.terrain_ft is None else FlatTerrain(args.terrain_ft)
    model = PlantModel(seed=args.seed, terrain=terrain, latitude=args.lat, longitude=args.lon,
                       gps_noise_m=args.gps_noise_m, gps_clock_bias_us=args.gps_clock_bias_us,
                       gps_outage=args.gps_outage, weather=not args.no_weather, traffic=not args.no_traffic,
                       ground=not args.no_ground, rf=not args.no_rf, satellite_after_s=args.satellite_after,
                       esm=not args.no_esm, scan_sensors=not args.no_sensors, electrical=not args.no_electrical,
                       utilities=not args.no_utilities)
    model.hold = args.hold
    plant = PlantTerminal(model, args.port_base)
    status = plant.init()
    if status != Status.OK:
        print(f"plant: init failed: {status.name} (port {args.port_base + PLANT_RT} in use?)", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"plant: RT {PLANT_RT} on 127.0.0.1:{args.port_base + PLANT_RT}")
    try:
        while args.syncs == 0 or plant.syncs < args.syncs:
            if plant.poll() and not args.quiet and plant.syncs % 50 == 1:
                print(f"plant: frame {plant.syncs}: alt {model.value('altitude'):.0f} ft, "
                      f"{model.value('speed'):.0f} kt, hdg {model.value('heading'):.0f}, "
                      f"{model.value('latitude'):.4f} {model.value('longitude'):.4f}, "
                      f"thrust {model.engines.engines[0].thrust:.0f}/{model.engines.engines[1].thrust:.0f}%")
    except KeyboardInterrupt:
        pass
    finally:
        plant.shutdown()
    c = plant.process.terminal.counters
    print(f"plant: syncs={plant.syncs} transmits={c.transmits} message_errors={c.message_errors} "
          f"publish_failures={plant.publish_failures} thrust_commands={plant.thrust_commands} "
          f"generator_commands={plant.generator_commands}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
