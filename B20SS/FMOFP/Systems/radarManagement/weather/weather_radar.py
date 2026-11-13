"""
Weather Radar System

Handles weather radar operations using direct message handling.
"""

from enum import Enum
import os
import time
import traceback
import threading
import xml.etree.ElementTree as ET
import numpy as np
import uuid
import FMOFP.Utils.common.fetching as fetching
from typing import Dict
from FMOFP.Systems.radarManagement.radar_enums import weather_radarMode
from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.radarManagement.weather.reflectivity_simulator import ReflectivitySimulator
from FMOFP.Systems.radarManagement.weather.vil_data_generator_sync import VILDataGenerator
from FMOFP.Systems.radarManagement.weather.precipitation_data_generator_sync import PrecipitationDataGenerator
from FMOFP.Systems.radarManagement.radar_messaging.stormCellTracking import StormCellTracker
from FMOFP.Systems.radarManagement.radar_messaging.precipitation_analysis import PrecipitationAnalyzer
from FMOFP.Systems.radarManagement.weather.weather_processor import WindShearProcessor, TurbulenceProcessor
from FMOFP.Utils.common.operation_tracker import track_operation, is_operation_completed
from FMOFP.Systems.radarManagement.weather.weather_message_type_detector import weather_message_type_detector
# Import centralized message type constants

logger = get_logger()

class weather_radar:
    def __init__(self, name: str, radar_control, radar_messenger):
        self.name = name
        self.mode = weather_radarMode.STANDBY
        self.radar_control = radar_control
        self.radar_messenger = radar_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True
        self._last_update = time.time()
        self._update_interval = 0.1  # seconds
        self._resource_usage = {
            'cpu_usage': 0,
            'memory_usage': 0,
            'disk_usage': 0
        }

        # Flag to track startup state and ignore startup messages
        self._in_startup = True
        self._startup_complete_time = None
        self._startup_timeout = 5.0  # seconds

        # Initialize configuration
        self.config = self._get_default_config()
        self.config.update(self._load_radar_config())

        # Initialize radar parameters
        self.tilt = self.config['tilt_range']['min']
        self.range = self.config['scan_range']['min']

        # Initialize reflectivity simulator, VIL data generator, and precipitation data generator
        self.reflectivity_simulator = ReflectivitySimulator(self.config)
        self.vil_data_generator = VILDataGenerator(self.config)
        self.precipitation_data_generator = PrecipitationDataGenerator(self.config)
        self.msg_type_detector = weather_message_type_detector()

        # Capability modules (previously orphaned — now connected)
        self.storm_cell_tracker = StormCellTracker()
        self.precip_analyzer    = PrecipitationAnalyzer()
        self.windshear_proc     = WindShearProcessor()
        self.turbulence_proc    = TurbulenceProcessor()

        logger.info(f"[WEATHER] Weather radar {name} initialized")

    def start(self):
        """Start the weather radar system."""
        try:
            logger.info(f"[WEATHER] Starting weather radar {self.name}")
            with self._lock:
                if self.running:
                    logger.info(f"[WEATHER] Weather radar {self.name} already initialized")  # Changed from warning
                    return

                # Set startup flag to true
                self._in_startup = True
                self._startup_complete_time = time.time() + self._startup_timeout

                self.running = True
                self.mode = weather_radarMode.STANDBY
                # Allow time for system initialization
                # Transition to operational mode if radar control exists
                if hasattr(self, 'radar_control') and self.radar_control:
                    logger.info(f"[WEATHER] Weather radar {self.name} transitioning to operational mode")

                    # Set the radar mode to NORMAL after startup
                    self.set_mode(weather_radarMode.NORMAL, send_completion=True, request_id=str(uuid.uuid4()))

                # Set startup flag to false after initialization
                self._in_startup = False
                logger.info(f"[WEATHER] Weather radar {self.name} startup complete, now accepting messages")

            logger.info(f"[WEATHER] Weather radar {self.name} started and configured")
        except Exception as e:
            logger.error(f"[WEATHER] Error starting weather radar {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            self._health_status = False

    def stop(self):
        """Stop the weather radar system."""
        try:
            logger.info(f"Stopping weather radar {self.name}")
            with self._lock:
                if not self.running:
                    logger.info(f"[WEATHER] Weather radar {self.name} already stopped")  # Changed from warning
                    return
                self.running = False
                self.mode = weather_radarMode.STANDBY
            logger.info(f"[WEATHER] Weather radar {self.name} stopped")
        except Exception as e:
            logger.error(f"[WEATHER] Error stopping weather radar {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            self._health_status = False

    def _load_message_rates(self):
        def _load_message_rates_impl():
            # Default message rates in case loading fails
            message_rates = {
                'status_msg': 1,
                'alert_msg': 5,
                'data_msg': 10,
                'command_msg': 2,
                'log_msg': 0.5
            }

            # Load message rates from file
            config_file = os.path.join(fetching.fetch_fmofp_path(), 'messageRateConfig.xml')
            logger.info(f"[WEATHER] Attempting to load message rates from: {config_file}")

            try:
                if not os.path.exists(config_file):
                    logger.error(f"[WEATHER] Configuration file not found: {config_file}")
                    return message_rates

                tree = ET.parse(config_file)
                root = tree.getroot()
                for msg_type in root.findall('message_rates/*'):
                    msg_name = msg_type.tag
                    rate_hz = float(msg_type.find('rate_hz').text)
                    message_rates[msg_name] = rate_hz

                logger.info("[WEATHER] Successfully loaded message rate configurations")

            except ET.ParseError as e:
                logger.error(f"[WEATHER] XML parsing error in configuration file: {e}")
                # Use default rates if parsing fails

            except Exception as e:
                logger.error(f"[WEATHER] Failed to load message rate configurations: {e}")
                # Use default rates if loading fails

            logger.info(f"[WEATHER] Using message rates: {message_rates}")
            return message_rates

        # Use the operation tracker to ensure this only happens once
        result = track_operation('message_rates_load', 'weather_radar', _load_message_rates_impl)
        if result is None:
            # If already loaded, we need to get the result from a previous call
            # Since we can't directly access the previous result, we'll check if the tracking file exists
            if is_operation_completed('message_rates_load', 'weather_radar'):
                logger.info("[WEATHER] Message rates already loaded, using cached values")
                # We need to load the rates again, but this is just to get the data
                return _load_message_rates_impl()
        return result

    def _load_radar_config(self):
        config_file = os.path.join(os.path.dirname(__file__), '..', 'rmConfig.xml')
        try:
            if not os.path.exists(config_file):
                logger.error(f"[WEATHER] Radar configuration file not found: {config_file}")
                return self._get_default_config()

            tree = ET.parse(config_file)
            root = tree.getroot()
            weather_radar = root.find('weather_radar')
            if weather_radar is None:
                logger.error("[WEATHER] 'weather_radar' section not found in the configuration file")
                return self._get_default_config()

            config = {
                'pulse_width': {'min': 0.1, 'max': 10},  # microseconds
                'prf': {'min': 100, 'max': 2000},  # Hz
                'antenna_gain': 30,  # dB
                'frequency': 9.345,  # GHz
                'tilt_range': {'min': 0, 'max': 90},  # degrees
                'scan_range': {'min': 10, 'max': 200},  # kilometers
                'vcp': {
                    'surveillance': {'elevs': (0.5, 1.5, 2.4, 3.4), 'update_rate': 20},
                    'mapping': {'elevs': (0.5, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0), 'update_rate': 120}
                },
                'vil_params': {'a': 2.55e-6, 'b': 0.55},
                'shear_params': {'threshold': 5},
                'turb_params': {'threshold': 15},
                'simulated': weather_radar.get('simulated', 'false').lower() == 'true'
            }
            return config
        except Exception as e:
            logger.error(f"[WEATHER] Error loading radar configuration: {e}")
            return self._get_default_config()

    def load_config(self, config):
        if config:
            self.config.update(config)
        logger.info(f"[WEATHER] Weather radar configuration loaded: {self.config}")

    def update(self):
        """Update weather radar state."""
        try:
            if not self.running:
                return

            current_time = time.time()
            if current_time - self._last_update < self._update_interval:
                return

            with self._lock:
                # Update resource usage
                self._update_resource_usage()

                # Update health status
                self._check_health()

                # Update radar state based on mode
                self._update_radar_state()

                self._last_update = current_time

        except Exception as e:
            logger.error(f"[WEATHER] Error updating weather radar {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            self._health_status = False

    def _update_resource_usage(self):
        """Update simulated resource usage."""
        try:
            # Simulate resource usage
            self._resource_usage['cpu_usage'] = 30  # Example CPU usage
            self._resource_usage['memory_usage'] = 40  # Example memory usage
            self._resource_usage['disk_usage'] = 20  # Example disk usage
        except Exception as e:
            logger.error(f"[WEATHER] Error updating resource usage for {self.name}: {str(e)}")

    def _check_health(self):
        """Check radar health status."""
        try:
            # Check resource thresholds
            if (self._resource_usage['cpu_usage'] > 90 or
                self._resource_usage['memory_usage'] > 90 or
                self._resource_usage['disk_usage'] > 90):
                self._health_status = False
                logger.warning(f"[WEATHER] Weather radar {self.name} resource usage too high")
            else:
                self._health_status = True
        except Exception as e:
            logger.error(f"[WEATHER] Error checking health for {self.name}: {str(e)}")
            self._health_status = False

    def _update_radar_state(self):
        """Update radar state based on current mode."""
        try:
            if self.mode == weather_radarMode.STANDBY:
                # Minimal processing in standby
                pass
            elif self.mode == weather_radarMode.SURVEILLANCE:
                # Process surveillance data
                self._process_surveillance_data()
            elif self.mode == weather_radarMode.MAPPING:
                # Process mapping data
                self._process_mapping_data()
            elif self.mode == weather_radarMode.TURBULENCE:
                self._process_turbulence_data()
            elif self.mode == weather_radarMode.WINDSHEAR:
                self._process_windshear_data()
            elif self.mode == weather_radarMode.NORMAL:
                # Process normal data
                pass
            else:
                logger.warning(f"[WEATHER] Unknown mode {self.mode} for weather radar {self.name}")
        except Exception as e:
            logger.error(f"[WEATHER] Error updating radar state for {self.name}: {str(e)}")

    def _process_surveillance_data(self):
        """Process weather surveillance data — run storm cell tracker and push to display."""
        try:
            elevation_angles = self.config['vcp'].get(
                'surveillance', {}).get('elevs', (0.5,))
            reflectivity = self.reflectivity_simulator.generate_reflectivity(
                'surveillance', elevation_angles)
            self.storm_cell_tracker.process_radar_data(
                reflectivity, elevation_angles=elevation_angles)
            cells = self.storm_cell_tracker.get_active_cells()
            logger.debug(f"[WEATHER] {len(cells) if cells else 0} storm cells tracked")
        except Exception as e:
            logger.error(f"[WEATHER] Error processing surveillance data for {self.name}: {str(e)}")

    def _process_mapping_data(self):
        """Process weather mapping data — run precipitation analyser and push to display."""
        try:
            elevation_angles = self.config['vcp'].get(
                'mapping', {}).get('elevs', (0.5,))
            reflectivity = self.reflectivity_simulator.generate_reflectivity(
                'mapping', elevation_angles)
            # generate_reflectivity() always returns a 3D array
            # (azimuth, elevation, range), but PrecipitationAnalyzer expects
            # a 2D (azimuth, range) array - it does np.argwhere() on a mask
            # of it and unpacks the result as exactly (center_y, center_x).
            # Passing the raw 3D array here made every centroid have 3
            # coordinates instead of 2, raising "too many values to unpack
            # (expected 2)" on every single call. Collapse to a 2D composite
            # first, same approach already used for the other
            # precip_analyzer.process_radar_data() call site below. Also fixes
            # elevation_angles previously landing in the temperature_data
            # positional slot instead of scan_elevation.
            reflectivity_2d = reflectivity.max(axis=1)
            lowest_elev = float(elevation_angles[0]) if elevation_angles else 0.5
            self.precip_analyzer.process_radar_data(
                reflectivity_data=reflectivity_2d,
                scan_elevation=lowest_elev
            )
            enriched = self.precip_analyzer.get_precipitation_data()
            logger.debug(f"[WEATHER] {len(enriched) if enriched else 0} precipitation points analysed")
        except Exception as e:
            logger.error(f"[WEATHER] Error processing mapping data for {self.name}: {str(e)}")

    def _process_turbulence_data(self):
        """Process TURBULENCE mode data via TurbulenceProcessor."""
        try:
            elevation_angles = self.config['vcp'].get(
                self.mode.name.lower(), {}).get('elevs', (0.5,))
            reflectivity = self.reflectivity_simulator.generate_reflectivity(
                self.mode.name.lower(), elevation_angles)
            cells = self.turbulence_proc.process(
                reflectivity, elevation_angles)
            if cells:
                logger.info(
                    f"[WEATHER] Turbulence: {len(cells)} cells, "
                    f"max category={self.turbulence_proc.max_category()}")
        except Exception as exc:
            logger.error(f"[WEATHER] Turbulence processing error: {exc}")

    def _process_windshear_data(self):
        """Process WINDSHEAR mode data via WindShearProcessor."""
        try:
            elevation_angles = self.config['vcp'].get(
                self.mode.name.lower(), {}).get('elevs', (0.5,))
            reflectivity = self.reflectivity_simulator.generate_reflectivity(
                self.mode.name.lower(), elevation_angles)
            events = self.windshear_proc.process(
                reflectivity, elevation_angles)
            if self.windshear_proc.has_microburst():
                logger.warning("[WEATHER] MICROBURST DETECTED")
            logger.debug(f"[WEATHER] {len(events) if events else 0} wind shear events")
        except Exception as exc:
            logger.error(f"[WEATHER] Windshear processing error: {exc}")

    def set_mode(self, mode, send_completion=True, request_id=None):
        """
        Set radar mode.

        Args:
            mode: The new mode to set
            send_completion: Whether to send a mode change completion notification (default: True)
            request_id: The request ID to include in the completion message

        Returns:
            True when the radar is in `mode` once this returns -- including
            when it was already there. False when the command was refused.

            Story C23.1 AC3: every exit used to be a bare `return`, so a
            caller could not tell a refused command from an accepted one. FMS
            and FCS set_mode() already return booleans and their live suites
            assert on them; this matches that convention.
        """
        try:
            # Handle different input types
            try:
                if isinstance(mode, weather_radarMode):
                    # Already a valid enum value
                    pass
                elif isinstance(mode, int):
                    # Convert integer to enum value
                    mode = weather_radarMode(mode)
                elif isinstance(mode, Enum):
                    # Story C23.1. This used to be
                    #     elif hasattr(mode, '_value_'):
                    #         mode = weather_radarMode(mode._value_)
                    # and EVERY enum member carries _value_, so a member of
                    # any enum class at all was silently reinterpreted by its
                    # number. RadarMode.SEARCH is 3 and weather_radarMode(3)
                    # is TEST -- a command meaning "search" put this radar
                    # into built-in test. Measured: value 3 maps to TEST in
                    # all five radar enums, so the collision is universal; it
                    # only bit on the three radars that had this branch.
                    #
                    # A member of a different enum is a programming error, not
                    # an integer in disguise. The int branch above stays: a
                    # mode value arriving as a plain int is a legitimate
                    # shape. (Instrumented over a live boot and the full mode
                    # sweep, no int was observed reaching set_mode -- every
                    # call carried an enum -- so that branch is kept for the
                    # paths this run did not exercise, not because it is known
                    # to be in use.)
                    logger.error(
                        f"[WEATHER] Refusing mode from a foreign enum: "
                        f"{type(mode).__name__}.{mode.name}. This radar is "
                        f"commanded with weather_radarMode; coercing by numeric "
                        f"value would silently select "
                        f"weather_radarMode({mode.value})."
                    )
                    return False
                elif mode is weather_radarMode:
                    # Handle case where we get the actual enum class itself (not an instance/member)
                    logger.info("[WEATHER] Received enum class itself, defaulting to SURVEILLANCE mode")
                    mode = weather_radarMode.SURVEILLANCE
                else:
                    logger.error(f"[WEATHER] Invalid mode type: {type(mode)}")
                    return False
            except ValueError as e:
                logger.error(f"[WEATHER] Invalid mode value: {mode}")
                return False
            except Exception as e:
                logger.error(f"[WEATHER] Error converting mode: {str(e)}")
                return False


            # Check if we're already in this mode - no need to change or send completion
            if self.mode == mode:
                logger.info(f"[WEATHER] Already in mode {mode.name}, no change needed")
                return True  # the radar IS in the requested mode

            logger.info(f"[WEATHER] Setting mode to: {mode.name}")

            old_mode = self.mode
            self.mode = mode

            logger.info(f"[WEATHER] Weather radar mode changed from {old_mode.name} to {mode.name}")
            logger.info("[WEATHER] Mode change completed")
            logger.debug(f"[WEATHER] Radar name: {self.name}")  # Keep radar name in debug log

            return True
        except Exception as e:
            logger.error(f"[WEATHER] Error setting mode for weather radar {self.name}: {str(e)}")
            logger.error(traceback.format_exc())

    def _get_default_config(self):
        """Return default configuration."""
        return {
            'pulse_width': {'min': 0.1, 'max': 10},
            'prf': {'min': 100, 'max': 2000},
            'antenna_gain': 30,
            'frequency': 9.345,
            'tilt_range': {'min': 0, 'max': 90},
            'scan_range': {'min': 10, 'max': 200},
            'vcp': {
                'surveillance': {'elevs': (0.5, 1.5, 2.4, 3.4), 'update_rate': 20},
                'mapping': {'elevs': (0.5, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0), 'update_rate': 120}
            },
            'vil_params': {'a': 2.55e-6, 'b': 0.55},
            'shear_params': {'threshold': 5},
            'turb_params': {'threshold': 15},
            'simulated': True
        }

    def is_healthy(self) -> bool:
        """Check if radar is healthy."""
        return self._health_status and self.running

    def get_status(self) -> Dict:
        """Get radar status."""
        with self._lock:
            return {
                'name': self.name,
                'mode': self.mode.name,
                'running': self.running,
                'healthy': self._health_status,
                **self._resource_usage
            }

    def get_data(self, data_type: str) -> Dict:
        """Get radar data."""
        with self._lock:
            if data_type == "surveillance":
                return self._get_surveillance_data()
            elif data_type == "mapping":
                return self._get_mapping_data()
            else:
                logger.warning(f"Unknown data type requested: {data_type}")
                return {}

    def set_range(self, range_km):
        with self._lock:
            self.range = range_km

    def scan(self):
        if self.mode == weather_radarMode.STANDBY:
            return

        with self._lock:
            # Perform radar scan and signal processing to generate products
            ref, vel, width = self._process_raw_data()
            vil = self._calculate_vil(ref)
            shear = self._detect_wind_shear(vel, width)
            turb = self._detect_turbulence(width)
            echo_tops = self._calculate_echo_tops(ref)
            self._send_weather_products(ref, vel, vil, shear, turb, echo_tops)

    def _process_raw_data(self):
        # Simulate raw reflectivity, velocity, spectrum width data
        # using radar parameters and weather simulation
        ref = None
        vel = None
        width = None
        return ref, vel, width

    def _calculate_vil(self, ref):
        """Calculate Vertically Integrated Liquid (VIL) from reflectivity volume scan."""
        if ref is None:
            return None

        # Use the VIL data generator to calculate VIL
        elevation_angles = self.config['vcp'][self.mode.name.lower()]['elevs']
        return self.vil_data_generator.calculate_vil(ref, elevation_angles)

    def _detect_wind_shear(self, vel, width):
        # Detect wind shear signatures from velocity and spectrum width data
        if vel is None or width is None:
            return None

        shear = np.zeros(vel.shape[::2])  # Initialize shear array

        for az in range(vel.shape[0]):
            for r in range(1, vel.shape[2] - 1):
                # Calculate radial shear
                radial_shear = (vel[az, :, r+1] - vel[az, :, r-1]) / 2
                # Calculate azimuthal shear
                az_next = (az + 1) % vel.shape[0]
                az_prev = (az - 1) % vel.shape[0]
                azimuthal_shear = (vel[az_next, :, r] - vel[az_prev, :, r]) / 2

                # Combine radial and azimuthal shear
                total_shear = np.sqrt(radial_shear**2 + azimuthal_shear**2)

                # Check if shear exceeds threshold and spectrum width is significant
                shear[az, r] = np.any((total_shear > self.config['shear_params']['threshold']) &
                                      (width[az, :, r] > self.config['turb_params']['threshold']))

        return shear

    def _detect_turbulence(self, width):
        # Detect turbulence from spectrum width data
        if width is None:
            return None
        turb = width > self.config['turb_params']['threshold']
        return turb

    def _calculate_echo_tops(self, ref):
        # Calculate height of storm echo tops from reflectivity data
        if ref is None:
            return None

        echo_tops = np.zeros((ref.shape[0], ref.shape[2]))  # Initialize echo tops array

        # Assuming each elevation step represents 1 km in height (adjust as needed)
        height_per_step = 1.0

        for az in range(ref.shape[0]):
            for r in range(ref.shape[2]):
                # Find the highest elevation where reflectivity exceeds a threshold (e.g., 18 dBZ)
                echo_top = np.argwhere(ref[az, :, r] > 18)
                if echo_top.size > 0:
                    echo_tops[az, r] = (echo_top[-1][0] + 1) * height_per_step

        return echo_tops

    def _get_surveillance_data(self) -> Dict:
        """Get surveillance data."""
        return {
            'type': 'surveillance',
            'timestamp': time.time(),
            'data': {}  # Add actual data here
        }

    def _get_mapping_data(self) -> Dict:
        """Get mapping data."""
        return {
            'type': 'mapping',
            'timestamp': time.time(),
            'data': {}  # Add actual data here
        }

    def update_real(self):
        """Update real radar system."""
        try:
            # Adjust tilt and range based on aircraft altitude and speed
            self._update_tilt_and_range()

            # Perform radar scan
            self.scan()

        except Exception as e:
            logger.error(f"weather_radar {self.name}: Error in real update: {e}")
            raise

    def update_simulated(self):
        """Update simulated radar system."""
        try:
            # Generate simulated data
            ref = self._get_simulated_reflectivity()
            vel = self._get_simulated_velocity()
            width = self._get_simulated_spectrum_width()

            # Process simulated data
            vil = self._calculate_vil(ref)
            shear = self._detect_wind_shear(vel, width)
            turb = self._detect_turbulence(width)
            echo_tops = self._calculate_echo_tops(ref)

            # Send processed data
            self._send_weather_products(ref, vel, vil, shear, turb, echo_tops)

        except Exception as e:
            logger.error(f"weather_radar {self.name}: Error in simulated update: {e}")
            raise

    def _get_simulated_reflectivity(self):
        """Generate a 3D volume of simulated reflectivity data using the reflectivity simulator."""
        elevation_angles = self.config['vcp'][self.mode.name.lower()]['elevs']
        return self.reflectivity_simulator.generate_reflectivity(self.mode.name.lower(), elevation_angles)

    def _get_simulated_velocity(self):
        # Generate a 3D volume of simulated velocity data
        azimuth_steps = 360
        elevation_steps = len(self.config['vcp'][self.mode.name.lower()]['elevs'])
        range_steps = 1000

        # Create a 3D array to store velocity values
        velocity = np.zeros((azimuth_steps, elevation_steps, range_steps))

        # Generate realistic velocity patterns
        for az in range(azimuth_steps):
            for el in range(elevation_steps):
                for r in range(range_steps):
                    # Simulate wind patterns
                    base_velocity = 10 * np.sin(2 * np.pi * az / azimuth_steps)  # Sinusoidal wind pattern
                    altitude_factor = 1 + (el / elevation_steps)  # Increase wind speed with altitude
                    range_factor = 1 - (r / range_steps) * 0.5  # Decrease wind speed with range

                    velocity[az, el, r] = base_velocity * altitude_factor * range_factor

                    # Add some randomness to create more realistic patterns
                    velocity[az, el, r] += np.random.normal(0, 2)

        # Ensure velocity values are within a realistic range (e.g., -50 to 50 m/s)
        velocity = np.clip(velocity, -50, 50)

        return velocity

    def _get_simulated_spectrum_width(self):
        # Generate a 3D volume of simulated spectrum width data
        azimuth_steps = 360
        elevation_steps = len(self.config['vcp'][self.mode.name.lower()]['elevs'])
        range_steps = 1000

        # Create a 3D array to store spectrum width values
        spectrum_width = np.zeros((azimuth_steps, elevation_steps, range_steps))

        # Generate realistic spectrum width patterns
        for az in range(azimuth_steps):
            for el in range(elevation_steps):
                for r in range(range_steps):
                    # Simulate turbulence
                    base_width = 2 + 3 * np.random.random()  # Base spectrum width between 2 and 5 m/s
                    altitude_factor = 1 + (el / elevation_steps) * 0.5  # Increase turbulence with altitude
                    range_factor = 1 - (r / range_steps) * 0.3  # Slight decrease in turbulence with range

                    spectrum_width[az, el, r] = base_width * altitude_factor * range_factor

                    # Add some randomness to create more realistic patterns
                    spectrum_width[az, el, r] += np.random.normal(0, 0.5)

        # Ensure spectrum width values are within a realistic range (e.g., 0 to 10 m/s)
        spectrum_width = np.clip(spectrum_width, 0, 10)

        return spectrum_width

    def _update_tilt_and_range(self):
        with self._lock:
            if hasattr(self.radar_control, 'aircraft'):
                altitude_km = self.radar_control.aircraft.altitude / 1000
                speed_km_s = self.radar_control.aircraft.speed / 1000

                self.tilt = max(self.config['tilt_range']['min'],
                                min(self.config['tilt_range']['max'],
                                    altitude_km))
                self.range = max(self.config['scan_range']['min'],
                                min(self.config['scan_range']['max'],
                                    speed_km_s * 60))

    def _convert_reflectivity_data(self, ref_data):
        # Convert reflectivity data format
        # This will depend on how reflectivity is represented in the simulation state
        # For now, we'll assume it's already in the correct format
        return ref_data

    def _convert_velocity_data(self, vel_data):
        # Convert velocity data format
        # This will depend on how wind velocity is represented in the simulation state
        # For now, we'll assume it's already in the correct format
        return vel_data

    def _convert_turbulence_to_spectrum_width(self, turb_data):
        # Convert turbulence data to spectrum width
        # This will involve modeling the spectral broadening caused by turbulence
        # For simplicity, we'll use a linear relationship for now
        return turb_data * 0.1  # Arbitrary scaling factor

    def _dict_to_xml(self, root_name, data_dict):
        root = ET.Element(root_name)
        for key, value in data_dict.items():
            child = ET.SubElement(root, key)
            child.text = str(value)
        return root

    def _send_weather_products(self, ref, vel, vil, shear, turb, echo_tops):
        """Send processed weather products."""
        try:
            # Package data
            products = {
                'reflectivity': ref,
                'velocity': vel,
                'vil': vil,
                'shear': shear,
                'turbulence': turb,
                'echo_tops': echo_tops
            }
            # Log products
            logger.debug(f"Weather products generated: {list(products.keys())}")
        except Exception as e:
            logger.error(f"Error sending weather products: {e}")
