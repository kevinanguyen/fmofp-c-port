"""
Radar Display Modes
--Aligns with addressbook.xml
Defines the display modes specific to radar displays.
This file serves as a central reference for radar display modes used across the system.

This is the primary source of truth for all radar mode values in the system.
All display and system components must use these values for consistency.
"""

from enum import Enum

class RadarDisplayMode(Enum):
    """
    Radar-specific display modes.
    
    These modes are used for radar displays and are separate from the general
    display modes (DAY, NIGHT, NVG) defined in base_display.py.
    
    This comprehensive enum includes modes from all radar types:
    - Weather Radar
    - Terrain Following Radar (TFR)
    - Synthetic Aperture Radar (SAR)
    - Targeting Radar
    - Airborne Early Warning and Control (AEWC) Radar
    
    The mode values follow a standardized structure:
    - Universal Base Modes: -1 to 9
    - Weather Radar Modes: 10-19
    - TFR Radar Modes: 20-29
    - SAR Radar Modes: 30-39
    - Targeting Radar Modes: 40-49
    - AEWC Radar Modes: 50-59
    """
    # Universal Base Modes (0-9)
    INITIALIZING = -1   # Special pre-operational state
    STANDBY = 0         # Power-saving/inactive state
    NORMAL = 1          # Standard operational mode
    DEGRADED = 2        # Reduced capability mode
    TEST = 3            # Built-in test mode 
    MAINTENANCE = 4     # Maintenance/calibration mode
    EMERGENCY = 5       # Emergency operations mode
    FAILURE = 6         # System failure mode
    RECOVERY = 7        # Recovery from failure mode
    CALIBRATION = 8     # Active calibration mode
    
    # Weather Radar Modes (10-19)
    SURVEILLANCE = 10   # Primary weather surveillance mode
    MAPPING = 11        # Ground mapping (Weather radar)
    TURBULENCE = 12     # Turbulence detection (Weather radar)
    WINDSHEAR = 13      # Wind shear detection (Weather radar)
    PRECIPITATION = 14  # Precipitation measurement mode
    
    # TFR Radar Modes (20-29)
    TFR_SEARCH = 20     # Search mode (TFR)
    TFR_TRACK = 21      # Track mode (TFR)
    TFR_ACTIVE = 22     # Active mode (TFR)
    TERRAIN_FOLLOWING = 23  # Terrain following (TFR)
    OBSTACLE_AVOIDANCE = 24 # Obstacle avoidance (TFR)
    TFR_GROUND_MAPPING = 25 # Ground mapping (TFR)
    
    # SAR Radar Modes (30-39)
    STRIPMAP = 30       # Stripmap mode (SAR)
    SPOTLIGHT = 31      # Spotlight mode (SAR)
    SCANSAR = 32        # ScanSAR mode (SAR)
    INTERFEROMETRIC = 33 # Interferometric mode (SAR)
    DOPPLER_BEAM = 34   # Doppler beam mode (SAR)
    
    # Targeting Radar Modes (40-49)
    TARGET_SEARCH = 40  # Target search mode
    TARGET_TRACK = 41   # Target tracking mode
    LOCK = 42           # Lock mode (Targeting)
    TERRAIN_AVOIDANCE = 43 # Terrain avoidance (Targeting)
    
    # AEWC Radar Modes (50-59)
    AEWC_SEARCH = 50    # Search mode (AEWC)
    AEWC_SURVEILLANCE = 51 # Surveillance mode (AEWC)
    SECTOR_SCAN = 52    # Sector scan (AEWC)
    STEALTH_DETECTION = 53 # Stealth detection (AEWC)
    ELECTRONIC_PROTECTION = 54 # Electronic protection (AEWC)
    AEWC_TRACK = 55     # Track mode (AEWC)

    
    # NOTE (B8): the six lookup dictionaries that used to sit here now live
    # at module level, below the class. See the comment there.

    @classmethod
    def from_string(cls, mode_str):
        """
        Convert a string mode name to the corresponding enum value.
        
        Args:
            mode_str: String representation of the mode name
            
        Returns:
            RadarDisplayMode: The corresponding enum value, or STANDBY if not found
        """
        if not mode_str:
            return cls.STANDBY
            
        mode_str = mode_str.upper()
        
        # First check the comprehensive mode map
        if mode_str in cls.mode_map:
            return cls.mode_map[mode_str]
            
        # Then try a direct match with enum names
        for mode in cls:
            if mode.name == mode_str:
                return mode
                
        # Default to STANDBY if not found
        return cls.STANDBY
    
    @classmethod
    def to_string(cls, mode_value):
        """
        Convert a mode value to its string representation.
        
        Args:
            mode_value: Integer value of the mode
            
        Returns:
            str: The string representation of the mode, or "STANDBY" if not found
        """
        if mode_value is None:
            return "STANDBY"
            
        # Try to convert directly from value
        for mode in cls:
            if mode.value == mode_value:
                return mode.name
                
        # Default to STANDBY if not found
        return "STANDBY"
        
    @classmethod
    def get_radar_specific_mode(cls, mode_name_or_value, radar_type):
        """
        Get the appropriate mode for a specific radar type.
        
        This handles the case where the same name might map to different
        mode values for different radar types.
        
        Args:
            mode_name_or_value: String name or integer value of the mode
            radar_type: String identifying the radar type
                (weather_radar, tfr_radar, sar_radar, targeting_radar, aewc_radar)
                
        Returns:
            RadarDisplayMode: The appropriate mode for the specified radar type
        """
        # Convert mode to string if it's an integer or enum
        if isinstance(mode_name_or_value, int):
            mode_name = cls.to_string(mode_name_or_value)
        elif isinstance(mode_name_or_value, cls):
            mode_name = mode_name_or_value.name
        else:
            mode_name = str(mode_name_or_value).upper()
            
        # Select the appropriate mode map based on radar type
        if radar_type == 'weather_radar':
            mode_map = cls.weather_radar_modes
        elif radar_type == 'tfr_radar':
            mode_map = cls.tfr_radar_modes
        elif radar_type == 'sar_radar':
            mode_map = cls.sar_radar_modes
        elif radar_type == 'targeting_radar':
            mode_map = cls.targeting_radar_modes
        elif radar_type == 'aewc_radar':
            mode_map = cls.aewc_radar_modes
        else:
            # If radar type is unknown, use the comprehensive mode map
            mode_map = cls.mode_map
            
        # Look up the mode in the selected mode map
        if mode_name in mode_map:
            return mode_map[mode_name]
            
        # Default to the common mode map if not found in radar-specific map
        if mode_name in cls.mode_map:
            return cls.mode_map[mode_name]
            
        # Default to STANDBY if not found anywhere
        return cls.STANDBY


# ── mode lookup tables (BLOCKER B8) ──────────────────────────────────────────
#
# These six dictionaries used to be declared INSIDE the RadarDisplayMode class
# body. In an Enum class body every plain assignment becomes an enum MEMBER, so
# `mode_map`, `weather_radar_modes` and the other four were not dictionaries at
# all -- they were members of RadarDisplayMode whose .value happened to be a
# dict. Two consequences, both live:
#
#   * `mode_str in cls.mode_map` in from_string() raised
#     TypeError: argument of type 'RadarDisplayMode' is not iterable.
#     Every lookup by mode NAME therefore failed. The one consumer that caught
#     it, displays/radar/display_radar_enums.py, returns STANDBY on failure --
#     so a radar commanded to SURVEILLANCE or TURBULENCE by name quietly stayed
#     in standby, with only a log line. The five call sites in
#     display_outgoing_router.py all took their exception paths.
#
#   * len(RadarDisplayMode) counted them, which is why the range check in
#     DisplayMessageHandler (`0 <= mode_value < len(RadarDisplayMode)`) was
#     measuring 42 against real values that run -1..55.
#
# At module level they are ordinary dicts again, and because the class now
# exists when they are built, the values are real enum members rather than the
# bare ints the class-body version captured -- which is what from_string() has
# always documented itself as returning, and what callers reading
# `.value` off the result need.

# Comprehensive mode map for all radar types
MODE_MAP = {
    # Universal Base Modes
    'INITIALIZING': RadarDisplayMode.INITIALIZING,
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'DEGRADED': RadarDisplayMode.DEGRADED,
    'TEST': RadarDisplayMode.TEST,
    'MAINTENANCE': RadarDisplayMode.MAINTENANCE,
    'EMERGENCY': RadarDisplayMode.EMERGENCY,
    'FAILURE': RadarDisplayMode.FAILURE,
    'RECOVERY': RadarDisplayMode.RECOVERY,
    'CALIBRATION': RadarDisplayMode.CALIBRATION,
    
    # Weather Radar Modes
    'SURVEILLANCE': RadarDisplayMode.SURVEILLANCE,
    'MAPPING': RadarDisplayMode.MAPPING,
    'TURBULENCE': RadarDisplayMode.TURBULENCE,
    'WINDSHEAR': RadarDisplayMode.WINDSHEAR,
    'PRECIPITATION': RadarDisplayMode.PRECIPITATION,
    
    # TFR Radar Modes
    'TFR_SEARCH': RadarDisplayMode.TFR_SEARCH,
    'SEARCH': RadarDisplayMode.TFR_SEARCH,  # Alias for backward compatibility
    'TFR_TRACK': RadarDisplayMode.TFR_TRACK,
    'TRACK': RadarDisplayMode.TFR_TRACK,    # Alias for backward compatibility
    'TFR_ACTIVE': RadarDisplayMode.TFR_ACTIVE,
    'ACTIVE': RadarDisplayMode.TFR_ACTIVE,  # Alias for backward compatibility
    'TERRAIN_FOLLOWING': RadarDisplayMode.TERRAIN_FOLLOWING,
    'OBSTACLE_AVOIDANCE': RadarDisplayMode.OBSTACLE_AVOIDANCE,
    'TFR_GROUND_MAPPING': RadarDisplayMode.TFR_GROUND_MAPPING,
    'GROUND_MAPPING': RadarDisplayMode.TFR_GROUND_MAPPING,  # Alias for backward compatibility
    
    # SAR Radar Modes
    'STRIPMAP': RadarDisplayMode.STRIPMAP,
    'SPOTLIGHT': RadarDisplayMode.SPOTLIGHT,
    'SCANSAR': RadarDisplayMode.SCANSAR,
    'INTERFEROMETRIC': RadarDisplayMode.INTERFEROMETRIC,
    'DOPPLER_BEAM': RadarDisplayMode.DOPPLER_BEAM,
    
    # Targeting Radar Modes
    'TARGET_SEARCH': RadarDisplayMode.TARGET_SEARCH,
    'TARGET_TRACK': RadarDisplayMode.TARGET_TRACK,
    'LOCK': RadarDisplayMode.LOCK,
    'TERRAIN_AVOIDANCE': RadarDisplayMode.TERRAIN_AVOIDANCE,
    
    # AEWC Radar Modes
    'AEWC_SEARCH': RadarDisplayMode.AEWC_SEARCH,
    'AEWC_SURVEILLANCE': RadarDisplayMode.AEWC_SURVEILLANCE,
    'SECTOR_SCAN': RadarDisplayMode.SECTOR_SCAN,
    'STEALTH_DETECTION': RadarDisplayMode.STEALTH_DETECTION, 
    'ELECTRONIC_PROTECTION': RadarDisplayMode.ELECTRONIC_PROTECTION,
    'AEWC_TRACK': RadarDisplayMode.AEWC_TRACK,

    # NOTE (production readiness re-analysis, August 2026): a duplicate
    # 'SEARCH'/'TRACK'/'ACTIVE' block used to be here, repeating the same
    # three keys (with identical values: TFR_SEARCH/TFR_TRACK/TFR_ACTIVE)
    # already defined above under "TFR Radar Modes" as backward-
    # compatibility aliases. Found via `ruff check --select F601`
    # (multi-value-repeated-key-literal). Since the values were
    # byte-for-byte identical both times, this was purely redundant --
    # not a behavior bug, just dead duplicate code -- removed rather than
    # the earlier occurrence to keep the aliases defined in one place.
}

# Radar-specific mode maps to help with converting between system and display modes
WEATHER_RADAR_MODES = {
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'SURVEILLANCE': RadarDisplayMode.SURVEILLANCE,
    'MAPPING': RadarDisplayMode.MAPPING,
    'TURBULENCE': RadarDisplayMode.TURBULENCE,
    'WINDSHEAR': RadarDisplayMode.WINDSHEAR,
    'PRECIPITATION': RadarDisplayMode.PRECIPITATION
}

TFR_RADAR_MODES = {
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'SEARCH': RadarDisplayMode.TFR_SEARCH,
    'TRACK': RadarDisplayMode.TFR_TRACK,
    'ACTIVE': RadarDisplayMode.TFR_ACTIVE,
    'TERRAIN_FOLLOWING': RadarDisplayMode.TERRAIN_FOLLOWING,
    'OBSTACLE_AVOIDANCE': RadarDisplayMode.OBSTACLE_AVOIDANCE,
    'GROUND_MAPPING': RadarDisplayMode.TFR_GROUND_MAPPING
}

SAR_RADAR_MODES = {
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'STRIPMAP': RadarDisplayMode.STRIPMAP,
    'SPOTLIGHT': RadarDisplayMode.SPOTLIGHT,
    'SCANSAR': RadarDisplayMode.SCANSAR,
    'INTERFEROMETRIC': RadarDisplayMode.INTERFEROMETRIC,
    'DOPPLER_BEAM': RadarDisplayMode.DOPPLER_BEAM
}

TARGETING_RADAR_MODES = {
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'SEARCH': RadarDisplayMode.TARGET_SEARCH,
    'TRACK': RadarDisplayMode.TARGET_TRACK,
    'LOCK': RadarDisplayMode.LOCK,
    'TERRAIN_AVOIDANCE': RadarDisplayMode.TERRAIN_AVOIDANCE
}

AEWC_RADAR_MODES = {
    'STANDBY': RadarDisplayMode.STANDBY,
    'NORMAL': RadarDisplayMode.NORMAL,
    'SEARCH': RadarDisplayMode.AEWC_SEARCH,
    'TRACK': RadarDisplayMode.AEWC_TRACK,
    'SURVEILLANCE': RadarDisplayMode.AEWC_SURVEILLANCE,
    'SECTOR_SCAN': RadarDisplayMode.SECTOR_SCAN,
    'STEALTH_DETECTION': RadarDisplayMode.STEALTH_DETECTION,
    'ELECTRONIC_PROTECTION': RadarDisplayMode.ELECTRONIC_PROTECTION
}


# Backwards compatibility: several modules reach for these through the class
# (radar_mode_converter.py guards each one with isinstance(..., dict), a check
# that could never pass while they were enum members). Assigning after class
# creation keeps `RadarDisplayMode.mode_map` working without putting the dicts
# back inside the Enum body.
RadarDisplayMode.mode_map = MODE_MAP
RadarDisplayMode.weather_radar_modes = WEATHER_RADAR_MODES
RadarDisplayMode.tfr_radar_modes = TFR_RADAR_MODES
RadarDisplayMode.sar_radar_modes = SAR_RADAR_MODES
RadarDisplayMode.targeting_radar_modes = TARGETING_RADAR_MODES
RadarDisplayMode.aewc_radar_modes = AEWC_RADAR_MODES
