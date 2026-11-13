"""
Terrain Following Radar System

Handles terrain following radar operations using direct message handling.
"""

from enum import Enum
import time
import threading
import numpy as np
from typing import Dict, List, Tuple
from FMOFP.Systems.radarManagement.radar_enums import tfr_radarMode
# Import radar-local message definitions to enforce system boundaries
# Import message type constants
# For backward compatibility - to be removed in future releases
from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.radarManagement.terrainFollowing.tfr_processor import PathOptimiser, ClearanceManager

logger = get_logger()

class tfr_radar:
    def __init__(self, name: str, radar_control, radar_messenger):
        self.name = name
        self.mode = tfr_radarMode.STANDBY
        self.radar_control = radar_control
        self.radar_messenger = radar_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True

        # TFR specific parameters
        self.scan_range = 10000  # meters
        self.scan_width = 2000   # meters
        self.elevation_points = 100
        self.terrain_data = self._initialize_terrain_data()
        self.last_warning_time = 0
        self.warning_interval = 1.0  # seconds

        # Capability modules
        self.path_optimiser    = PathOptimiser()
        self.clearance_manager = ClearanceManager()
        logger.info(f"TFR radar {name} initialized")

    def _initialize_terrain_data(self) -> List[Tuple[float, float]]:
        """Initialize simulated terrain data."""
        distances = np.linspace(0, self.scan_range, self.elevation_points)
        # Generate realistic terrain with hills and valleys
        elevations = 1000 + 500 * np.sin(distances / 1000) + \
                    200 * np.sin(distances / 300) + \
                    np.random.normal(0, 50, self.elevation_points)
        return list(zip(distances, elevations))

    def _check_terrain_warnings(self) -> List[Dict]:
        """Check for terrain warnings based on current data."""
        warnings = []
        current_time = time.time()

        if current_time - self.last_warning_time >= self.warning_interval:
            for distance, elevation in self.terrain_data:
                # Check for dangerous terrain features
                if elevation > 1500:  # High terrain
                    warnings.append({
                        'type': 'HIGH_TERRAIN',
                        'distance': distance,
                        'elevation': elevation
                    })
                elif abs(elevation - 1000) > 300:  # Steep terrain
                    warnings.append({
                        'type': 'STEEP_TERRAIN',
                        'distance': distance,
                        'elevation': elevation
                    })

            self.last_warning_time = current_time

        return warnings

    def start(self):
        """Start the TFR radar system."""
        try:
            logger.info(f"Starting TFR radar {self.name}")
            with self._lock:
                if self.running:
                    logger.warning(f"TFR radar {self.name} already running")
                    return
                self.running = True
                self.mode = tfr_radarMode.STANDBY
            logger.info(f"TFR radar {self.name} started")
        except Exception as e:
            logger.error(f"Error starting TFR radar {self.name}: {str(e)}")
            self._health_status = False

    def stop(self):
        """Stop the TFR radar system."""
        try:
            logger.info(f"Stopping TFR radar {self.name}")
            with self._lock:
                if not self.running:
                    logger.warning(f"TFR radar {self.name} already stopped")
                    return
                self.running = False
                self.mode = tfr_radarMode.STANDBY
            logger.info(f"TFR radar {self.name} stopped")
        except Exception as e:
            logger.error(f"Error stopping TFR radar {self.name}: {str(e)}")
            self._health_status = False

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
                if isinstance(mode, tfr_radarMode):
                    # Already a valid enum value
                    pass
                elif isinstance(mode, int):
                    # Convert integer to enum value
                    mode = tfr_radarMode(mode)
                elif isinstance(mode, Enum):
                    # Story C23.1. This used to be
                    #     elif hasattr(mode, '_value_'):
                    #         mode = tfr_radarMode(mode._value_)
                    # and EVERY enum member carries _value_, so a member of
                    # any enum class at all was silently reinterpreted by its
                    # number. RadarMode.SEARCH is 3 and tfr_radarMode(3)
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
                        f"[TFR_RADAR] Refusing mode from a foreign enum: "
                        f"{type(mode).__name__}.{mode.name}. This radar is "
                        f"commanded with tfr_radarMode; coercing by numeric "
                        f"value would silently select "
                        f"tfr_radarMode({mode.value})."
                    )
                    return False
                elif mode is tfr_radarMode:
                    # Handle case where we get the actual enum class itself (not an instance/member)
                    logger.info("[TFR_RADAR] Received enum class itself, defaulting to NORMAL mode")
                    mode = tfr_radarMode.NORMAL
                else:
                    logger.error(f"[TFR_RADAR] Invalid mode type: {type(mode)}")
                    return False
            except ValueError as e:
                logger.error(f"[TFR_RADAR] Invalid mode value: {mode}")
                return False
            except Exception as e:
                logger.error(f"[TFR_RADAR] Error converting mode: {str(e)}")
                return False

            # Check if we're already in this mode - no need to change or send completion
            if self.mode == mode:
                logger.info(f"[TFR_RADAR] Already in mode {mode.name}, no change needed")
                return True  # the radar IS in the requested mode

            with self._lock:
                old_mode = self.mode
                self.mode = mode
                logger.info(f"TFR radar {self.name} mode changed from {old_mode.name} to {mode.name}")

                # Update terrain data when entering SEARCH or TRACK mode
                if mode in [tfr_radarMode.SEARCH, tfr_radarMode.TRACK]:
                    self.terrain_data = self._initialize_terrain_data()

            return True
        except Exception as e:
            logger.error(f"Error setting mode for TFR radar {self.name}: {str(e)}")

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
                'scan_range': self.scan_range,
                'scan_width': self.scan_width
            }
