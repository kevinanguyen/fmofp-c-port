"""
Flight Control System (FCS)

Handles aircraft orientation control and provides data to the displays.
This system integrates with the Flight Management System to provide
comprehensive flight control capabilities for the aircraft.
"""

import threading
import time
import traceback
import math
from typing import List

from FMOFP.Utils.logger.sys_logger import get_logger
from FMOFP.Systems.flightManagementSys.flightControlSys.attitude_calculator import get_attitude_calculator
from FMOFP.Systems.flightManagementSys.flightControlSys.fcs_message_type_detector import fcs_message_type_detector

logger = get_logger()

class FlightControlModes:
    """Flight Control System modes."""
    NORMAL = "NORMAL"         # Standard flight control mode
    COMBAT = "COMBAT"         # Enhanced maneuverability for tactical operations
    PRECISION = "PRECISION"   # Precise control for landing/refueling
    AUTOPILOT = "AUTOPILOT"   # Automated flight control
    TERRAIN = "TERRAIN"       # Terrain following mode
    EMERGENCY = "EMERGENCY"   # Emergency control mode with simplified handling
    
    @classmethod
    def get_all_modes(cls) -> List[str]:
        """Get all available FCS modes."""
        return [cls.NORMAL, cls.COMBAT, cls.PRECISION, 
                cls.AUTOPILOT, cls.TERRAIN, cls.EMERGENCY]

class FlightControlSystem:
    """
    Flight Control System (FCS) for  aircraft.
    
    This system manages aircraft orientation and control, integrating with
    the FMS to provide comprehensive flight control capabilities.
    """
    def __init__(self, name: str = "FCS", fms_control=None, fms_messenger=None):
        """
        Initialize the Flight Control System.
        
        Args:
            name: Name of the flight control system
            fms_control: Reference to the parent FMS
            fms_messenger: Reference to the FMS messenger for communication
        """
        self.name = name
        self.fms_control = fms_control
        self.fms_messenger = fms_messenger
        self.running = False
        self._lock = threading.Lock()
        self._health_status = True
        self._last_update = time.time()
        self._update_interval = 0.02  # 50Hz update rate
        self._thread = None
        
        # Flag to track startup state
        self._in_startup = True
        self._startup_complete_time = None
        self._startup_timeout = 5.0  # seconds
        
        # System mode
        self.mode = FlightControlModes.NORMAL
        
        # Control inputs
        self.control_inputs = {
            'aileron': 0,      # Roll control: -1.0 to 1.0
            'elevator': 0,     # Pitch control: -1.0 to 1.0
            'rudder': 0,       # Yaw control: -1.0 to 1.0
            'throttle': 0.5,   # Engine power: 0.0 to 1.0
        }
        
        # Initialize attitude calculator
        self.attitude_calculator = get_attitude_calculator()
        
        # Initialize message type detector
        self.message_detector = fcs_message_type_detector()
        
        # Aircraft attitude/orientation - will be updated from attitude calculator
        self.attitude = {
            'roll': 0,         # Roll angle in degrees
            'pitch': 0,        # Pitch angle in degrees
            'yaw': 0,          # Yaw angle (heading) in degrees
            'roll_rate': 0,    # Roll rate in degrees/sec
            'pitch_rate': 0,   # Pitch rate in degrees/sec
            'yaw_rate': 0,     # Yaw rate in degrees/sec
            'alpha': 0,        # Angle of attack in degrees
            'beta': 0,         # Sideslip angle in degrees
            'g_force': 1.0     # Current G-force (1.0 = normal gravity)
        }
        
        # System status
        self.status = {
            'health': 'NOMINAL',  # System health status
            'mode': FlightControlModes.NORMAL,  # Current operating mode
            'warnings': [],       # Active warnings
            'errors': [],         # Active errors
        }
        
        logger.info(f"[FCS] Flight Control System {name} initialized")

    def set_messenger(self, messenger):
        """Set the messenger for FCS communications via FMS."""
        self.fms_messenger = messenger
            
        logger.info("[FCS] FCS messenger set")

    def start(self):
        """Start the flight control system."""
        try:
            logger.info(f"[FCS] Starting flight control system {self.name}")
            with self._lock:
                if self.running:
                    logger.info(f"[FCS] Flight control system {self.name} already running")
                    return False
                
                # Set startup flag to true
                self._in_startup = True
                self._startup_complete_time = time.time() + self._startup_timeout
                
                self.running = True
                self.mode = FlightControlModes.NORMAL
                
                # Start the update thread
                self._thread = threading.Thread(
                    target=self.update_loop,
                    name="FCSUpdateThread",
                    daemon=True
                )
                self._thread.start()
                
                # Set startup flag to false after initialization
                self._in_startup = False
                logger.info(f"[FCS] Flight control system {self.name} startup complete, now accepting messages")
                
            logger.info(f"[FCS] Flight control system {self.name} started and configured")
            return True
        except Exception as e:
            logger.error(f"[FCS] Error starting flight control system {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            self._health_status = False
            return False

    def stop(self):
        """Stop the flight control system."""
        try:
            logger.info(f"[FCS] Stopping flight control system {self.name}")
            with self._lock:
                if not self.running:
                    logger.info(f"[FCS] Flight control system {self.name} already stopped")
                    return
                self.running = False
                
                # Wait for the thread to end
                if self._thread and self._thread.is_alive():
                    self._thread.join(2.0)  # Wait up to 2 seconds
                    if self._thread.is_alive():
                        logger.warning("[FCS] Flight control system thread did not terminate cleanly")
                    self._thread = None
                
            logger.info(f"[FCS] Flight control system {self.name} stopped")
        except Exception as e:
            logger.error(f"[FCS] Error stopping flight control system {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            self._health_status = False

    def update_loop(self):
        """Main update loop for the flight control system."""
        logger.info("[FCS] FCS update loop started")
        
        while self.running:
            try:
                start_time = time.time()
                
                # Update flight controls and attitude
                self.update_flight_controls()
                
                # Calculate time to sleep to maintain update rate
                elapsed = time.time() - start_time
                sleep_time = max(0, self._update_interval - elapsed)
                time.sleep(sleep_time)
            except Exception as e:
                logger.error(f"[FCS] Error in FCS update loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(1)  # Sleep longer on error to avoid error flood
        
        logger.info("[FCS] FCS update loop ended")

    def update_flight_controls(self):
        """Update flight controls and aircraft attitude."""
        with self._lock:
            # Use the attitude calculator for more accurate attitude calculations
            if self.attitude_calculator:
                # Convert control inputs to format expected by attitude calculator
                surface_positions = {
                    'left_aileron': self.control_inputs['aileron'],
                    'right_aileron': -self.control_inputs['aileron'],  # Right aileron moves in opposite direction
                    'elevator': self.control_inputs['elevator'],
                    'rudder': self.control_inputs['rudder']
                }
                
                # Update attitude using attitude calculator
                updated_attitude = self.attitude_calculator.update(
                    control_inputs=self.control_inputs,
                    surface_positions=surface_positions,
                    dt=self._update_interval
                )
                
                # Copy updated values to our attitude dict
                self.attitude['roll'] = updated_attitude['roll']
                self.attitude['pitch'] = updated_attitude['pitch']
                self.attitude['yaw'] = updated_attitude['yaw']
                self.attitude['roll_rate'] = updated_attitude['roll_rate']
                self.attitude['pitch_rate'] = updated_attitude['pitch_rate']
                self.attitude['yaw_rate'] = updated_attitude['yaw_rate']
                self.attitude['alpha'] = updated_attitude['alpha']
                self.attitude['beta'] = updated_attitude['beta']
                self.attitude['g_force'] = updated_attitude['g_force']
            else:
                # Fallback to simple simulation if attitude calculator is unavailable
                logger.warning("[FCS] Attitude calculator not available, using simplified simulation")
                
                # Simulate roll response to aileron input
                target_roll_rate = self.control_inputs['aileron'] * 20  # Max 20 deg/sec
                self.attitude['roll_rate'] += (target_roll_rate - self.attitude['roll_rate']) * 0.1
                self.attitude['roll'] += self.attitude['roll_rate'] * self._update_interval
                
                # Simulate pitch response to elevator input
                target_pitch_rate = -self.control_inputs['elevator'] * 10  # Max 10 deg/sec, negative because pulling back (positive) should increase pitch
                self.attitude['pitch_rate'] += (target_pitch_rate - self.attitude['pitch_rate']) * 0.1
                self.attitude['pitch'] += self.attitude['pitch_rate'] * self._update_interval
                
                # Simulate yaw response to rudder input
                target_yaw_rate = self.control_inputs['rudder'] * 5  # Max 5 deg/sec
                self.attitude['yaw_rate'] += (target_yaw_rate - self.attitude['yaw_rate']) * 0.1
                self.attitude['yaw'] += self.attitude['yaw_rate'] * self._update_interval
                
                # Add some natural oscillation to simulate airflow effects
                self.attitude['roll'] += math.sin(time.time() * 0.5) * 0.05
                self.attitude['pitch'] += math.sin(time.time() * 0.7) * 0.02
                self.attitude['yaw'] += math.sin(time.time() * 0.3) * 0.01
                
                # Calculate AoA and sideslip based on motion (simplified)
                self.attitude['alpha'] = self.attitude['pitch'] * 0.1 + self.attitude['pitch_rate'] * 0.01
                self.attitude['beta'] = -self.attitude['yaw_rate'] * 0.1 + math.sin(time.time() * 0.4) * 0.2
                
                # Calculate G-force (simplified)
                pitch_change = abs(self.attitude['pitch_rate']) / 10.0  # Normalize by max rate
                roll_change = abs(self.attitude['roll_rate']) / 20.0    # Normalize by max rate
                self.attitude['g_force'] = 1.0 + pitch_change + (roll_change * 0.5)
                
                # Keep angles within appropriate ranges
                self.attitude['roll'] = (self.attitude['roll'] + 180) % 360 - 180
                self.attitude['pitch'] = max(-60, min(60, self.attitude['pitch']))
                self.attitude['yaw'] = self.attitude['yaw'] % 360
                self.attitude['g_force'] = max(0.1, min(9.0, self.attitude['g_force']))
            
            # Update status
            self.status['mode'] = self.mode

    def set_control_input(self, control_type: str, value: float, send_completion: bool = True, request_id: str = None) -> bool:
        """
        Set a control input value.
        
        Args:
            control_type: Type of control ('aileron', 'elevator', 'rudder', 'throttle')
            value: Control value (-1.0 to 1.0 for flight controls, 0.0 to 1.0 for throttle)
            send_completion: Whether to send a completion message
            request_id: Request ID for completion message
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if control_type not in self.control_inputs:
                logger.warning(f"[FCS] Invalid control type: {control_type}")
                return False
            
            # Check value range
            if control_type == 'throttle':
                value = max(0.0, min(1.0, value))  # Throttle: 0.0 to 1.0
            else:
                value = max(-1.0, min(1.0, value))  # Other controls: -1.0 to 1.0
            
            # Set the control input
            old_value = self.control_inputs[control_type]
            self.control_inputs[control_type] = value
            logger.info(f"[FCS] {control_type} changed from {old_value} to {value}")
            
            return True
        except Exception as e:
            logger.error(f"[FCS] Error setting control input: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def set_mode(self, mode: str, send_completion: bool = True, request_id: str = None) -> bool:
        """
        Set the flight control system mode.
        
        Args:
            mode: New mode to set (use FlightControlModes class constants)
            send_completion: Whether to send a completion message
            request_id: Request ID for completion message
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate mode
            if mode not in FlightControlModes.get_all_modes():
                logger.warning(f"[FCS] Invalid mode: {mode}")
                return False
            
            # Set the mode
            if self.mode == mode:
                logger.info(f"[FCS] Already in mode {mode}, no change needed")
                return True
                
            old_mode = self.mode
            self.mode = mode
            logger.info(f"[FCS] Mode changed from {old_mode} to {mode}")
            
            # Update parameters based on mode
            if mode == FlightControlModes.COMBAT:
                # Increase responsiveness for combat mode
                self._update_interval = 0.01  # 100Hz update rate
            elif mode == FlightControlModes.PRECISION:
                # More precise control for precision mode
                self._update_interval = 0.02  # 50Hz update rate
            else:
                # Default update rate
                self._update_interval = 0.02  # 50Hz update rate
            
            return True
        except Exception as e:
            logger.error(f"[FCS] Error setting mode: {str(e)}")
            return False

    def send_orientation_data(self):
        """Send orientation data to other systems via messenger."""
        if not self.fms_messenger:
            logger.warning("[FCS] FMS messenger not set, cannot send orientation data")
            return False
            
        try:
            # Prepare data for transmission
            orientation_data = {
                'attitude': self.attitude.copy(),
                'status': self.status.copy(),
                'timestamp': time.time()
            }
            
            # NOTE: orientation_data (dict, above) is computed but was never
            # used - data_words (below) is what actually gets sent. Kept for
            # parity with the rest of this method, which uses individual
            # fields of self.attitude directly when building data_words.
            
            # Convert dict to a list of integers for MIL-STD-1553B transmission
            data_words = []
            
            # Add a header word to identify data type
            data_words.append(0x2000)  # FCS orientation data identifier
            
            # We can only send a limited number of words, so prioritize key attitude data
            roll_int = int(self.attitude['roll'] * 100) & 0xFFFF
            pitch_int = int(self.attitude['pitch'] * 100) & 0xFFFF
            yaw_int = int(self.attitude['yaw'] * 100) & 0xFFFF
            roll_rate_int = int(self.attitude['roll_rate'] * 100) & 0xFFFF
            pitch_rate_int = int(self.attitude['pitch_rate'] * 100) & 0xFFFF
            yaw_rate_int = int(self.attitude['yaw_rate'] * 100) & 0xFFFF
            g_force_int = int(self.attitude['g_force'] * 100) & 0xFFFF
            
            # Add each value to data words
            data_words.extend([
                roll_int, pitch_int, yaw_int,
                roll_rate_int, pitch_rate_int, yaw_rate_int,
                g_force_int
            ])
            
            # Add status word (mode packed into a 16-bit integer)
            mode_int = 0
            if self.mode == FlightControlModes.NORMAL:
                mode_int = 0
            elif self.mode == FlightControlModes.COMBAT:
                mode_int = 1
            elif self.mode == FlightControlModes.PRECISION:
                mode_int = 2
            elif self.mode == FlightControlModes.AUTOPILOT:
                mode_int = 3
            elif self.mode == FlightControlModes.TERRAIN:
                mode_int = 4
            elif self.mode == FlightControlModes.EMERGENCY:
                mode_int = 5
            data_words.append(mode_int)
            
            # Send data via messenger with properly formatted data words.
            # NOTE: this previously only logged an intent to send and always
            # returned True without ever calling into fms_messenger - no
            # orientation data was actually transmitted to any other system
            # (displays, etc.), even though this method's two callers
            # (flight_control_system._handle_orientation_data_request_sync
            # and fms_message_processor.py) treat a True return as
            # confirmation that a response was sent. Matches the same
            # send_fms_data(data_words) call pattern already used
            # successfully elsewhere (flightManagementSystem.py).
            logger.info(f"[FCS] Sending orientation data with {len(data_words)} data words")
            result = self.fms_messenger.send_fms_data(data_words)
            if not result:
                logger.warning("[FCS] fms_messenger.send_fms_data() reported failure sending orientation data")
            return result
        except Exception as e:
            logger.error(f"[FCS] Error sending orientation data: {e}")
            logger.error(traceback.format_exc())
            return False

# Singleton instance
_flight_control_system = None

def get_flight_control_system(name="MainFCS"):
    """
    Get the singleton instance of the Flight Control System.
    
    Args:
        name: Optional name for the FCS instance
        
    Returns:
        FlightControlSystem: The singleton FCS instance
    """
    global _flight_control_system
    if _flight_control_system is None:
        _flight_control_system = FlightControlSystem(name=name)
    return _flight_control_system
