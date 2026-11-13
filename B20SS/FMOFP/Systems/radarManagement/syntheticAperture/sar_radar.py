"""
Synthetic Aperture Radar System

Handles SAR operations using direct message handling.
"""

from enum import Enum
import threading
import numpy as np
from typing import Dict
from FMOFP.Systems.radarManagement.radar_enums import sar_radarMode
# Import radar-local message definitions to enforce system boundaries
# Import message type constants
# For backward compatibility - to be removed in future releases
from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.radarManagement.syntheticAperture.sar_processor import ChangeDetector

logger = get_logger()

class sar_radar:
    def __init__(self, name: str, radar_control, radar_messenger):
        self.name = name
        self.mode = sar_radarMode.STANDBY
        self.radar_control = radar_control
        self.radar_messenger = radar_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True

        # SAR specific parameters
        self.image_width = 1024    # pixels
        self.image_height = 1024   # pixels
        self.resolution = 1.0      # meters per pixel
        self.corner_points = [
            (-5000, -5000),  # Bottom left
            (-5000, 5000),   # Top left
            (5000, 5000),    # Top right
            (5000, -5000)    # Bottom right
        ]

        # Capability modules
        self.change_detector = ChangeDetector()
        logger.info(f"SAR radar {name} initialized")

    def _generate_imagery_data(self) -> np.ndarray:
        """Generate simulated SAR imagery data."""
        try:
            # Create a simulated ground image with features
            image = np.zeros((self.image_height, self.image_width), dtype=np.uint8)

            # Add terrain features based on current mode
            if self.mode == sar_radarMode.STRIPMAP:
                # Long linear features
                for i in range(5):
                    x = np.random.randint(0, self.image_width)
                    image[:, x:x+10] = 200

            elif self.mode == sar_radarMode.SPOTLIGHT:
                # Circular target area
                center_x = self.image_width // 2
                center_y = self.image_height // 2
                radius = min(self.image_width, self.image_height) // 4

                y, x = np.ogrid[-center_y:self.image_height-center_y, -center_x:self.image_width-center_x]
                mask = x*x + y*y <= radius*radius
                image[mask] = 200

            elif self.mode == sar_radarMode.SCANSAR:
                # Multiple swath patterns
                for i in range(3):
                    start_y = i * (self.image_height // 3)
                    end_y = (i + 1) * (self.image_height // 3)
                    image[start_y:end_y, :] = np.random.randint(100, 200, (end_y-start_y, self.image_width))

            # Add some noise
            noise = np.random.normal(0, 10, image.shape)
            image = np.clip(image + noise, 0, 255).astype(np.uint8)

            return image

        except Exception as e:
            logger.error(f"Error generating SAR imagery: {e}")
            return bytes()

    def start(self):
        """Start the SAR radar system."""
        try:
            logger.info(f"Starting SAR radar {self.name}")
            with self._lock:
                if self.running:
                    logger.warning(f"SAR radar {self.name} already running")
                    return
                self.running = True
                self.mode = sar_radarMode.STANDBY
            logger.info(f"SAR radar {self.name} started")
        except Exception as e:
            logger.error(f"Error starting SAR radar {self.name}: {str(e)}")
            self._health_status = False

    def stop(self):
        """Stop the SAR radar system."""
        try:
            logger.info(f"Stopping SAR radar {self.name}")
            with self._lock:
                if not self.running:
                    logger.warning(f"SAR radar {self.name} already stopped")
                    return
                self.running = False
                self.mode = sar_radarMode.STANDBY
            logger.info(f"SAR radar {self.name} stopped")
        except Exception as e:
            logger.error(f"Error stopping SAR radar {self.name}: {str(e)}")
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
                if isinstance(mode, sar_radarMode):
                    # Already a valid enum value
                    pass
                elif isinstance(mode, int):
                    # Convert integer to enum value
                    mode = sar_radarMode(mode)
                elif isinstance(mode, Enum):
                    # Story C23.1. This used to be
                    #     elif hasattr(mode, '_value_'):
                    #         mode = sar_radarMode(mode._value_)
                    # and EVERY enum member carries _value_, so a member of
                    # any enum class at all was silently reinterpreted by its
                    # number. RadarMode.SEARCH is 3 and sar_radarMode(3)
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
                        f"[SAR_RADAR] Refusing mode from a foreign enum: "
                        f"{type(mode).__name__}.{mode.name}. This radar is "
                        f"commanded with sar_radarMode; coercing by numeric "
                        f"value would silently select "
                        f"sar_radarMode({mode.value})."
                    )
                    return False
                elif mode is sar_radarMode:
                    # Handle case where we get the actual enum class itself (not an instance/member)
                    logger.info("[SAR_RADAR] Received enum class itself, defaulting to STRIPMAP mode")
                    mode = sar_radarMode.STRIPMAP
                else:
                    logger.error(f"[SAR_RADAR] Invalid mode type: {type(mode)}")
                    return False
            except ValueError as e:
                logger.error(f"[SAR_RADAR] Invalid mode value: {mode}")
                return False
            except Exception as e:
                logger.error(f"[SAR_RADAR] Error converting mode: {str(e)}")
                return False

            # Check if we're already in this mode - no need to change or send completion
            if self.mode == mode:
                logger.info(f"[SAR_RADAR] Already in mode {mode.name}, no change needed")
                return True  # the radar IS in the requested mode

            with self._lock:
                old_mode = self.mode
                self.mode = mode
                logger.info(f"SAR radar {self.name} mode changed from {old_mode.name} to {mode.name}")

            return True
        except Exception as e:
            logger.error(f"Error setting mode for SAR radar {self.name}: {str(e)}")

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
                'resolution': self.resolution,
                'image_dimensions': (self.image_width, self.image_height)
            }
