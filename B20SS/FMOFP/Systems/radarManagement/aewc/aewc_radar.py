"""
Airborne Early Warning and Control (AEWC) Radar System

Handles AEWC radar operations using direct message handling.
"""

import time
import traceback
import threading
import numpy as np
from typing import Dict, List, Tuple, Optional
from FMOFP.Systems.radarManagement.radar_enums import aewc_radarMode
# Import radar-local message definitions to enforce system boundaries
# Import message type constants
from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.radarManagement.aewc.aewc_processor import SectorPriorityManager, ElectronicProtection

logger = get_logger()

class Sector:
    def __init__(self, sector_id: str, azimuth_range: Tuple[float, float],
                 elevation_range: Tuple[float, float], priority: int = 1):
        self.sector_id = sector_id
        self.azimuth_range = azimuth_range
        self.elevation_range = elevation_range
        self.priority = priority
        self.scan_progress = 0.0
        self.last_scan_time = 0.0
        self.active_tracks: List[int] = []

class aewc_radar:
    def __init__(self, name: str, radar_control, radar_messenger):
        self.name = name
        self.mode = aewc_radarMode.STANDBY
        self.radar_control = radar_control
        self.radar_messenger = radar_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True

        # AEWC specific parameters
        self.max_range = 400000  # meters (longer range than targeting radar)
        self.current_targets = {}  # track_id -> target_data
        self.next_track_id = 1
        self.stealth_probability = 0.2  # Probability of detecting stealth aircraft

        # Sector management
        self.sectors: Dict[str, Sector] = {}
        self._initialize_sectors()

        # Environmental conditions
        self.noise_floor = -110  # dBm
        self.clutter_map = {}
        self.interference_zones = []
        self.propagation_conditions = {
            'ducting': False,
            'humidity': 0.5,
            'temperature': 20.0
        }

        # Capability modules
        self.sector_priority = SectorPriorityManager(list(self.sectors.keys()))
        self.ecm_protection  = ElectronicProtection()
        logger.info(f"AEWC radar {name} initialized")

    def _initialize_sectors(self):
        """Initialize default radar coverage sectors."""
        # Create 6 main sectors covering 360 degrees
        for i in range(6):
            sector_id = f"SECTOR_{i+1}"
            azimuth_start = i * 60
            azimuth_end = (i + 1) * 60
            elevation_range = (-15, 45)  # Typical AEWC elevation coverage
            self.sectors[sector_id] = Sector(
                sector_id=sector_id,
                azimuth_range=(azimuth_start, azimuth_end),
                elevation_range=elevation_range,
                priority=1
            )

    def _generate_target(self) -> Dict:
        """Generate a simulated air target."""
        # Random position within range
        r = np.random.uniform(5000, self.max_range)
        theta = np.random.uniform(0, 2*np.pi)
        phi = np.random.uniform(-np.pi/4, np.pi/4)  # Wider elevation angle than targeting radar

        x = r * np.cos(phi) * np.cos(theta)
        y = r * np.cos(phi) * np.sin(theta)
        z = r * np.sin(phi)

        # Random velocity components (realistic aircraft speeds)
        v_mag = np.random.uniform(150, 500)  # m/s (higher speed range)
        v_theta = np.random.uniform(0, 2*np.pi)
        v_phi = np.random.uniform(-np.pi/6, np.pi/6)

        vx = v_mag * np.cos(v_phi) * np.cos(v_theta)
        vy = v_mag * np.cos(v_phi) * np.sin(v_theta)
        vz = v_mag * np.sin(v_phi)

        # Random acceleration components
        a_mag = np.random.uniform(0, 50)  # m/s²
        ax = a_mag * np.random.normal()
        ay = a_mag * np.random.normal()
        az = a_mag * np.random.normal()

        # Determine if target is stealth
        is_stealth = np.random.random() < 0.3  # 30% chance of stealth aircraft

        # Generate RCS based on aircraft type
        if is_stealth:
            rcs = np.random.uniform(0.01, 0.1)  # m² (stealth aircraft)
        else:
            rcs = np.random.uniform(1, 100)  # m² (conventional aircraft)

        # Classification based on speed, altitude, and stealth
        if is_stealth:
            classification = "STEALTH"
        elif v_mag > 400:
            classification = "FIGHTER"
        elif abs(z) > 30000:
            classification = "HIGH_ALT"
        else:
            classification = "UNKNOWN"

        return {
            'position': (float(x), float(y), float(z)),
            'velocity': (float(vx), float(vy), float(vz)),
            'acceleration': (float(ax), float(ay), float(az)),
            'classification': classification,
            'identity': "UNKNOWN",
            'is_stealth': is_stealth,
            'rcs': rcs,
            'snr': 0.0,  # Will be updated during processing
            'last_update': time.time()
        }

    def _get_target_sector(self, target_position: Tuple[float, float, float]) -> Optional[str]:
        """Determine which sector a target is in."""
        x, y, z = target_position
        azimuth = np.degrees(np.arctan2(y, x)) % 360
        elevation = np.degrees(np.arctan2(z, np.sqrt(x*x + y*y)))

        for sector_id, sector in self.sectors.items():
            az_start, az_end = sector.azimuth_range
            el_start, el_end = sector.elevation_range

            if az_start <= azimuth < az_end and el_start <= elevation < el_end:
                return sector_id

        return None

    def _calculate_snr(self, target: Dict) -> float:
        """Calculate Signal-to-Noise Ratio for a target."""
        x, y, z = target['position']
        range_to_target = np.sqrt(x*x + y*y + z*z)

        # Basic radar equation with environmental factors
        tx_power = 100000  # 100 kW
        wavelength = 0.03  # 10 GHz
        antenna_gain = 10000  # 40 dB

        # Calculate received power
        received_power = (tx_power * antenna_gain**2 * wavelength**2 * target['rcs']) / \
                        ((4*np.pi)**3 * range_to_target**4)

        # Convert to dB
        received_power_db = 10 * np.log10(received_power)

        # Account for environmental conditions
        if self.propagation_conditions['ducting']:
            received_power_db += 10

        # Calculate SNR
        snr = received_power_db - self.noise_floor

        return max(0, snr)  # Ensure non-negative SNR

    def _update_targets(self):
        """Update target positions and handle stealth detection."""
        current_time = time.time()

        with self._lock:
            # Clear sector track lists
            for sector in self.sectors.values():
                sector.active_tracks.clear()

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
                    del self.current_targets[track_id]
                    continue

                # Update target state
                target['position'] = (new_x, new_y, new_z)
                target['velocity'] = (new_vx, new_vy, new_vz)
                target['last_update'] = current_time

                # Calculate new SNR
                target['snr'] = self._calculate_snr(target)

                # Handle stealth aircraft detection
                if target['is_stealth']:
                    detection_probability = self.stealth_probability * (target['snr'] / 30)
                    if np.random.random() > detection_probability:
                        continue  # Skip updating stealth target (represents failed detection)

                # Update sector assignment
                sector_id = self._get_target_sector(target['position'])
                if sector_id and sector_id in self.sectors:
                    self.sectors[sector_id].active_tracks.append(track_id)

            # Add new targets randomly in SEARCH mode
            if self.mode == aewc_radarMode.SEARCH and len(self.current_targets) < 10:
                if np.random.random() < 0.1:  # 10% chance per update
                    self.current_targets[self.next_track_id] = self._generate_target()
                    self.next_track_id += 1

            # Update sector scan progress
            for sector in self.sectors.values():
                if current_time - sector.last_scan_time > 1.0:  # 1 second update rate
                    sector.scan_progress = (sector.scan_progress + 0.1) % 1.0
                    sector.last_scan_time = current_time

    def _run_aewc_processing(self) -> None:
        """Run sector prioritisation and ECM assessment on this update cycle."""
        try:
            sector_counts: dict = {sid: 0 for sid in self.sectors}
            sector_hostile: dict = {sid: 0 for sid in self.sectors}
            with self._lock:
                for tdata in self.current_targets.values():
                    sid = self._get_target_sector(tdata.get('position', (0, 0, 0)))
                    if sid:
                        sector_counts[sid] = sector_counts.get(sid, 0) + 1

            jammed = self.ecm_protection.get_jammed_sectors()
            self.sector_priority.update(sector_counts, sector_hostile, jammed)

            import random
            for sid in self.sectors:
                noise = self.noise_floor + random.gauss(0, 3)
                self.ecm_protection.assess_sector(sid, noise)
            self.ecm_protection.cleanup_stale()
        except Exception as exc:
            logger.error(f"[AEWC] AEWC processing error: {exc}")

    def start(self):
        """Start the AEWC radar system."""
        try:
            logger.info(f"Starting AEWC radar {self.name}")
            with self._lock:
                if self.running:
                    logger.warning(f"AEWC radar {self.name} already running")
                    return
                self.running = True
                self.mode = aewc_radarMode.STANDBY
            logger.info(f"AEWC radar {self.name} started")
        except Exception as e:
            logger.error(f"Error starting AEWC radar {self.name}: {str(e)}")
            self._health_status = False

    def stop(self):
        """Stop the AEWC radar system."""
        try:
            logger.info(f"Stopping AEWC radar {self.name}")
            with self._lock:
                if not self.running:
                    logger.warning(f"AEWC radar {self.name} already stopped")
                    return
                self.running = False
                self.mode = aewc_radarMode.STANDBY
            logger.info(f"AEWC radar {self.name} stopped")
        except Exception as e:
            logger.error(f"Error stopping AEWC radar {self.name}: {str(e)}")
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
            if isinstance(mode, int) and not isinstance(mode, aewc_radarMode):
                try:
                    mode = aewc_radarMode(mode)
                except ValueError:
                    logger.error(
                        f"[AEWC_RADAR] Refusing mode value {mode}: no "
                        f"aewc_radarMode member has it"
                    )
                    return False

            if not isinstance(mode, aewc_radarMode):
                logger.error(
                    f"[AEWC_RADAR] Refusing mode of type {type(mode).__name__}: "
                    f"this radar is commanded with its own enum. Coercing a "
                    f"foreign enum by numeric value is what story C23.1 "
                    f"removed from the other radars."
                )
                return False

            with self._lock:
                old_mode = self.mode
                self.mode = mode
                logger.info(f"AEWC radar {self.name} mode changed from {old_mode.name} to {mode.name}")

                # Clear targets when entering STANDBY
                if mode == aewc_radarMode.STANDBY:
                    self.current_targets.clear()
                    for sector in self.sectors.values():
                        sector.active_tracks.clear()
                        sector.scan_progress = 0.0

            return True
        except Exception as e:
            logger.error(f"Error setting mode for AEWC radar {self.name}: {str(e)}")

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
                'active_tracks': len(self.current_targets),
                'stealth_detection_probability': self.stealth_probability,
                'sectors': {
                    sector_id: {
                        'scan_progress': sector.scan_progress,
                        'active_tracks': len(sector.active_tracks)
                    }
                    for sector_id, sector in self.sectors.items()
                },
                'environmental_conditions': {
                    'noise_floor': self.noise_floor,
                    'propagation': self.propagation_conditions
                }
            }
            return status
