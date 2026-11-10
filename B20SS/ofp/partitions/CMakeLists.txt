# Code shared by every partition process, and the partitions themselves.
# Today: the terminal socket loop and a stub terminal that answers TERM_STATUS,
# which is what the Phase 1 gate runs against the bus controller.
add_library(ofp_rt_process STATIC common/src/rt_process.cpp)
add_library(ofp::rt_process ALIAS ofp_rt_process)
target_include_directories(ofp_rt_process PUBLIC common/include)
target_link_libraries(ofp_rt_process PUBLIC ofp::bus ofp::osal PRIVATE ofp::flight)

add_executable(fmofp_rt_stub rt_stub/src/main.cpp)
add_dependencies(fmofp_rt_stub ofp_icd_generate)
target_link_libraries(fmofp_rt_stub PRIVATE ofp::rt_process ofp::bc ofp::icd ofp::warnings)

# Flight control: the first ported partition. The logic is a library so the
# tests can drive it frame by frame; fmofp_fcs puts it on the bus.
add_library(ofp_fcs STATIC fcs/src/flight_control.cpp)
add_library(ofp::fcs ALIAS ofp_fcs)
add_dependencies(ofp_fcs ofp_icd_generate)
target_include_directories(ofp_fcs PUBLIC fcs/include)
target_link_libraries(ofp_fcs PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_fcs fcs/src/main.cpp)
target_link_libraries(fmofp_fcs PRIVATE ofp::fcs ofp::rt_process ofp::bc ofp::warnings)

# Navigation: the GPS solver and the GPS / dead-reckoning fusion as a library,
# fmofp_nav on the bus, and fmofp_nav_tool, which exposes the pure functions on
# stdin/stdout so the Python tests can run the original Python beside them.
add_library(ofp_nav STATIC nav/src/gps_solver.cpp nav/src/navigation.cpp)
add_library(ofp::nav ALIAS ofp_nav)
add_dependencies(ofp_nav ofp_icd_generate)
target_include_directories(ofp_nav PUBLIC nav/include)
target_link_libraries(ofp_nav PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_nav nav/src/main.cpp)
target_link_libraries(fmofp_nav PRIVATE ofp::nav ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_nav_tool nav/tools/nav_tool.cpp)
target_link_libraries(fmofp_nav_tool PRIVATE ofp::nav ofp::warnings)

# Flight management: flight modes and their envelopes, attitude commands and
# maneuvers, autopilot targets, thrust and gear, flight data and energy.
add_library(ofp_fms STATIC fms/src/flight_management.cpp)
add_library(ofp::fms ALIAS ofp_fms)
add_dependencies(ofp_fms ofp_icd_generate)
target_include_directories(ofp_fms PUBLIC fms/include)
target_link_libraries(ofp_fms PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_fms fms/src/main.cpp)
target_link_libraries(fmofp_fms PRIVATE ofp::fms ofp::rt_process ofp::bc ofp::warnings)

# The radar computer, RT 9, with the weather radar and the terrain-following
# radar ported: the sensor model that renders the plant's weather, the signal
# processing (VIL, rain rate, storm cells, precipitation areas, wind shear,
# turbulence) and the scan; the clearance assessment, path optimiser and
# terrain warnings over the plant's terrain profile; the targeting radar's
# tracks, lock, signature analysis and stealth detection over the plant's
# traffic, the AEWC radar's tracks, sectors and electronic protection over the
# same traffic, and the cross-radar track fusion. fmofp_radar_tool exposes the pure
# functions on stdin/stdout for the oracle tests.
add_library(ofp_radar STATIC radar/src/weather_model.cpp radar/src/weather_products.cpp
                             radar/src/weather_radar.cpp radar/src/terrain_following.cpp
                             radar/src/target_processing.cpp radar/src/targeting_radar.cpp
                             radar/src/track_fusion.cpp radar/src/aewc_radar.cpp
                             radar/src/sar_radar.cpp)
add_library(ofp::radar ALIAS ofp_radar)
add_dependencies(ofp_radar ofp_icd_generate)
target_include_directories(ofp_radar PUBLIC radar/include)
target_link_libraries(ofp_radar PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_radar radar/src/main.cpp)
target_link_libraries(fmofp_radar PRIVATE ofp::radar ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_radar_tool radar/tools/radar_tool.cpp)
target_link_libraries(fmofp_radar_tool PRIVATE ofp::radar ofp::warnings)

# Engine management, RT 3: the commanded thrust of each engine, the autothrottle
# and the asymmetry check (thrustManagement.py), the tanks, fuel lines, transfer
# policy and fuel monitor (fuelControl.py, fuelMonitor.py), and the assessment
# of the engines' measurements; the engine model itself runs in the plant.
# fmofp_engine_tool exposes the pure functions on stdin/stdout for the oracle tests.
add_library(ofp_engine STATIC engine/src/engine_management.cpp)
add_library(ofp::engine ALIAS ofp_engine)
add_dependencies(ofp_engine ofp_icd_generate)
target_include_directories(ofp_engine PUBLIC engine/include)
target_link_libraries(ofp_engine PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_engine engine/src/main.cpp)
target_link_libraries(fmofp_engine PRIVATE ofp::engine ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_engine_tool engine/tools/engine_tool.cpp)
target_link_libraries(fmofp_engine_tool PRIVATE ofp::engine ofp::warnings)

# The mission computer, RT 6: the route and its progress, the designated
# targets, the order of battle and the mission phase (missionService.py with
# MissionControl, RouteManager, Targeting and OrderOfBattle). fmofp_mission_tool
# exposes the three managers on stdin/stdout for the oracle tests.
add_library(ofp_mission STATIC mission/src/mission_computer.cpp)
add_library(ofp::mission ALIAS ofp_mission)
add_dependencies(ofp_mission ofp_icd_generate)
target_include_directories(ofp_mission PUBLIC mission/include)
target_link_libraries(ofp_mission PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_mission mission/src/main.cpp)
target_link_libraries(fmofp_mission PRIVATE ofp::mission ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_mission_tool mission/tools/mission_tool.cpp)
target_link_libraries(fmofp_mission_tool PRIVATE ofp::mission ofp::warnings)

# Communications, RT 2: the radio, satcom and data-link state and controls of
# CommsService; what the links measure comes from the plant's RF environment.
add_library(ofp_comms STATIC comms/src/comms_computer.cpp)
add_library(ofp::comms ALIAS ofp_comms)
add_dependencies(ofp_comms ofp_icd_generate)
target_include_directories(ofp_comms PUBLIC comms/include)
target_link_libraries(ofp_comms PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_comms comms/src/main.cpp)
target_link_libraries(fmofp_comms PRIVATE ofp::comms ofp::rt_process ofp::bc ofp::warnings)

# Defensive systems, RT 22: the radar warning receiver's contact table over the
# fused air tracks and the plant's ESM intercepts, the chaff and flare
# dispensers with the automatic salvo and its cooldown, and the ECM mode
# (DefensiveService). fmofp_defensive_tool exposes the logic on stdin/stdout
# for the oracle tests.
add_library(ofp_defensive STATIC defensive/src/defensive_systems.cpp)
add_library(ofp::defensive ALIAS ofp_defensive)
add_dependencies(ofp_defensive ofp_icd_generate)
target_include_directories(ofp_defensive PUBLIC defensive/include)
target_link_libraries(ofp_defensive PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_defensive defensive/src/main.cpp)
target_link_libraries(fmofp_defensive PRIVATE ofp::defensive ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_defensive_tool defensive/tools/defensive_tool.cpp)
target_link_libraries(fmofp_defensive_tool PRIVATE ofp::defensive ofp::warnings)

# Sensor management, RT 10: the six sensors' states and the health rule
# (SensorService) and the sensor data fusion's contact table over the plant's
# radar, LIDAR, infrared and ESM detections (SensorDataFusion). fmofp_sensor_tool
# exposes the logic on stdin/stdout for the oracle tests.
add_library(ofp_sensor STATIC sensor/src/sensor_management.cpp)
add_library(ofp::sensor ALIAS ofp_sensor)
add_dependencies(ofp_sensor ofp_icd_generate)
target_include_directories(ofp_sensor PUBLIC sensor/include)
target_link_libraries(ofp_sensor PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_sensor sensor/src/main.cpp)
target_link_libraries(fmofp_sensor PRIVATE ofp::sensor ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_sensor_tool sensor/tools/sensor_tool.cpp)
target_link_libraries(fmofp_sensor_tool PRIVATE ofp::sensor ofp::warnings)

# Power management, RT 8: PowerManagementSystem's bookkeeping over the plant's
# electrical readings (the main, APU and emergency batteries, the avionics
# coolant loop with its fan controller, the cabin's HVAC) and the component
# classes' controls. fmofp_power_tool exposes the logic on stdin/stdout for the
# oracle tests.
add_library(ofp_power STATIC power/src/power_management.cpp)
add_library(ofp::power ALIAS ofp_power)
add_dependencies(ofp_power ofp_icd_generate)
target_include_directories(ofp_power PUBLIC power/include)
target_link_libraries(ofp_power PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_power power/src/main.cpp)
target_link_libraries(fmofp_power PRIVATE ofp::power ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_power_tool power/tools/power_tool.cpp)
target_link_libraries(fmofp_power_tool PRIVATE ofp::power ofp::warnings)

# Flight surfaces, RT 21: FlightSurfaceService's ten control surfaces moved
# toward their commands at their slew rates (the ailerons and elevators from the
# sensed roll and pitch, the slats from the angle of attack, the flaps,
# speedbrake, rudder and trim from FSF_CMD), plus fmofp_surfaces_tool for the
# oracle tests.
add_library(ofp_surfaces STATIC surfaces/src/flight_surfaces.cpp)
add_library(ofp::surfaces ALIAS ofp_surfaces)
add_dependencies(ofp_surfaces ofp_icd_generate)
target_include_directories(ofp_surfaces PUBLIC surfaces/include)
target_link_libraries(ofp_surfaces PUBLIC ofp::bus ofp::icd PRIVATE ofp::flight)

add_executable(fmofp_surfaces surfaces/src/main.cpp)
target_link_libraries(fmofp_surfaces PRIVATE ofp::surfaces ofp::rt_process ofp::bc ofp::warnings)

add_executable(fmofp_surfaces_tool surfaces/tools/surfaces_tool.cpp)
target_link_libraries(fmofp_surfaces_tool PRIVATE ofp::surfaces ofp::warnings)
