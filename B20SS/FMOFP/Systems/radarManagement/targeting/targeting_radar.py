"""
Targeting Radar System

Handles targeting radar operations using direct message handling.
"""

import time
import threading
import traceback
import numpy as np
from typing import Dict, Optional
from FMOFP.Systems.radarManagement.radar_enums import targeting_radarMode
# Import radar-local message definitions to enforce system boundaries
# Import message type constants

from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.radarManagement.targeting.target_processor import TargetProcessor

logger = get_logger()

class targeting_radar:
    def __init__(self, name: str, radar_control, radar_messenger):
        self.name = name
        self.mode = targeting_radarMode.STANDBY
        self.radar_control = radar_control
        self.radar_messenger = radar_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True

        # Targeting specific parameters
        self.max_range = 100000  # meters
        self.current_targets = {}  # track_id -> target_data
        self.next_track_id = 1
        self.locked_track_id = None
        self.lock_quality = 0.0
        self.jamming_detected = False
        # Signal-processing capability modules
        self.target_processor = TargetProcessor()

        logger.info(f"Targeting radar {name} initialized")

    def _generate_target(self) -> Dict:
        """Generate a simulated target."""
        # Random position within range
        r = np.random.uniform(1000, self.max_range)
        theta = np.random.uniform(0, 2*np.pi)
        phi = np.random.uniform(-np.pi/6, np.pi/6)  # Limited elevation angle

        x = r * np.cos(phi) * np.cos(theta)
        y = r * np.cos(phi) * np.sin(theta)
        z = r * np.sin(phi)

        # Random velocity components (realistic speeds)
        v_mag = np.random.uniform(100, 300)  # m/s
        v_theta = np.random.uniform(0, 2*np.pi)
        v_phi = np.random.uniform(-np.pi/6, np.pi/6)

        vx = v_mag * np.cos(v_phi) * np.cos(v_theta)
        vy = v_mag * np.cos(v_phi) * np.sin(v_theta)
        vz = v_mag * np.sin(v_phi)

        # Random acceleration components
        a_mag = np.random.uniform(0, 30)  # m/s²
        ax = a_mag * np.random.normal()
        ay = a_mag * np.random.normal()
        az = a_mag * np.random.normal()

        # Classification based on speed and altitude
        if v_mag > 250:
            classification = "FIGHTER"
        elif abs(z) > 10000:
            classification = "HIGH_ALT"
        else:
            classification = "UNKNOWN"

        return {
            'position': (float(x), float(y), float(z)),
            'velocity': (float(vx), float(vy), float(vz)),
            'acceleration': (float(ax), float(ay), float(az)),
            'classification': classification,
            'identity': "UNKNOWN",
            'rcs': np.random.uniform(1, 10),  # Radar Cross Section in m²
            'snr': np.random.uniform(10, 30),  # Signal-to-Noise Ratio in dB
            'last_update': time.time()
        }

    def _update_targets(self):
        """Update target positions based on their velocities and accelerations."""
        current_time = time.time()

        with self._lock:
            # Update existing targets
            for track_id, target in list(self.current_targets.items()):
                dt = current_time - target['last_update']

                # Update position based on velocity and acceleration
                px, py, pz = target['position']
                vx, vy, vz = target['velocity']
                ax, ay, az = target['acceleration']

                # Update velocity with acceleration
                new_vx = vx + ax * dt
                new_vy = vy + ay * dt
                new_vz = vz + az * dt

                # Update position with new velocity
                new_x = px + 0.5 * (vx + new_vx) * dt
                new_y = py + 0.5 * (vy + new_vy) * dt
                new_z = pz + 0.5 * (vz + new_vz) * dt

                # Remove targets that are out of range
                if np.sqrt(new_x**2 + new_y**2 + new_z**2) > self.max_range:
                    if track_id == self.locked_track_id:
                        self.locked_track_id = None
                        self.lock_quality = 0.0
                    del self.current_targets[track_id]
                    continue

                # Update target state
                target['position'] = (new_x, new_y, new_z)
                target['velocity'] = (new_vx, new_vy, new_vz)
                target['last_update'] = current_time

                # Update SNR based on range
                range_to_target = np.sqrt(new_x**2 + new_y**2 + new_z**2)
                target['snr'] = 30 - 20 * np.log10(range_to_target / 1000)  # Simple SNR model

            # Add new targets randomly in SEARCH mode
            if self.mode == targeting_radarMode.SEARCH and len(self.current_targets) < 5:
                if np.random.random() < 0.1:  # 10% chance per update
                    self.current_targets[self.next_track_id] = self._generate_target()
                    self.next_track_id += 1

            # Update lock quality for locked target
            if self.locked_track_id is not None and self.locked_track_id in self.current_targets:
                target = self.current_targets[self.locked_track_id]
                self.lock_quality = min(1.0, target['snr'] / 30)  # Simple lock quality model
                self.jamming_detected = np.random.random() < 0.05  # 5% chance of jamming

    def _run_target_processing(self) -> None:
        """Run signature analysis and stealth detection on all active tracks."""
        try:
            with self._lock:
                self.target_processor.process_tracks(self.current_targets)
        except Exception as exc:
            logger.error(f"[TARGETING] Processor error: {exc}")

    def _get_target_range_data(self, track_id: int) -> Optional[Dict]:
        """Get range data for a specific target."""
        if track_id not in self.current_targets:
            return None

        target = self.current_targets[track_id]
        x, y, z = target['position']
        vx, vy, vz = target['velocity']

        # Calculate range and range rate
        range_to_target = np.sqrt(x**2 + y**2 + z**2)
        range_rate = (x*vx + y*vy + z*vz) / range_to_target

        # Calculate angles
        azimuth = np.arctan2(y, x)
        elevation = np.arctan2(z, np.sqrt(x**2 + y**2))

        return {
            'range': range_to_target,
            'range_rate': range_rate,
            'azimuth': azimuth,
            'elevation': elevation
        }

    def start(self):
        """Start the targeting radar system."""
        try:
            logger.info(f"Starting targeting radar {self.name}")
            with self._lock:
                if self.running:
                    logger.warning(f"Targeting radar {self.name} already running")
                    return
                self.running = True
                self.mode = targeting_radarMode.STANDBY
            logger.info(f"Targeting radar {self.name} started")
        except Exception as e:
            logger.error(f"Error starting targeting radar {self.name}: {str(e)}")
            self._health_status = False

    def stop(self):
        """Stop the targeting radar system."""
        try:
            logger.info(f"Stopping targeting radar {self.name}")
            with self._lock:
                if not self.running:
                    logger.warning(f"Targeting radar {self.name} already stopped")
                    return
                self.running = False
                self.mode = targeting_radarMode.STANDBY
            logger.info(f"Targeting radar {self.name} stopped")
        except Exception as e:
            logger.error(f"Error stopping targeting radar {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
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
            # Story C23.1 AC5: a mode value delivered as a plain int is a
            # legitimate shape off the 1553B path, and the other three radars
            # already accepted it. These two refused it, so the five disagreed
            # about the same wire format. (Instrumented over a live boot and
            # the full mode sweep, no int was in fact observed reaching
            # set_mode -- every call carried an enum. This closes the
            # inconsistency rather than fixing an observed failure.)
            if isinstance(mode, int) and not isinstance(mode, targeting_radarMode):
                try:
                    mode = targeting_radarMode(mode)
                except ValueError:
                    logger.error(
                        f"[TARGETING_RADAR] Refusing mode value {mode}: no "
                        f"targeting_radarMode member has it"
                    )
                    return False

            if not isinstance(mode, targeting_radarMode):
                logger.error(
                    f"[TARGETING_RADAR] Refusing mode of type {type(mode).__name__}: "
                    f"this radar is commanded with its own enum. Coercing a "
                    f"foreign enum by numeric value is what story C23.1 "
                    f"removed from the other radars."
                )
                return False

            with self._lock:
                old_mode = self.mode
                self.mode = mode
                logger.info(f"Targeting radar {self.name} mode changed from {old_mode.name} to {mode.name}")

                # Clear targets when entering STANDBY
                if mode == targeting_radarMode.STANDBY:
                    self.current_targets.clear()
                    self.locked_track_id = None
                    self.lock_quality = 0.0

            return True
        except Exception as e:
            logger.error(f"Error setting mode for targeting radar {self.name}: {str(e)}")

    def is_healthy(self) -> bool:
        """Check if radar is healthy."""
        return self._health_status and self.running

    def get_status(self) -> Dict:
        """Get radar status."""
        with self._lock:
            status = {
                'name': self.name,
                'mode': self.mode.name,
                'running': self.running,
                'healthy': self._health_status,
                'max_range': self.max_range,
                'active_tracks': len(self.current_targets)
            }

            if self.locked_track_id is not None:
                status.update({
                    'locked_track': self.locked_track_id,
                    'lock_quality': self.lock_quality,
                    'jamming_detected': self.jamming_detected
                })

            return status
