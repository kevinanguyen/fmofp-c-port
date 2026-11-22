# 8. Multi-Function Display, EICAS, TSD and SMS

**Navigation:** [← Primary Flight Display](07_Primary_Flight_Display.md) | [Table of Contents](00_Title_and_TOC.md) | [Holographic Displays →](09_Holographic_Display_System.md)

---

Four cockpit displays besides the PFD and the radar window. Each is a Python program running the original display
class unchanged, fed from the bus by `fmofp_display/systems_feed.py` (stand-ins for the subsystem getters the classes
called) and `radar_feed.py`.

## 8.1 Multi-Function Display (MFD), RT 13

`py -m fmofp_display mfd`. Pages, chosen by the display's own menu:

| Page | Draws | From |
|---|---|---|
| NAV | position, heading, speed | `BCAST_FMS_FLIGHT_DATA` |
| SYSTEMS | engine, fuel, GCAS alerts, envelope exceedances | `BCAST_ENG_*`, `BCAST_FCS_GCAS_ALERTS`, `BCAST_FCS_PERF_STATUS` |
| COMMS | radio, satcom, data link | `MFD_COM_LINK_STATUS` (the comms terminal's status relayed) |
| MISSION | route, targets, order of battle | `BCAST_MSN_STATUS`, the `BCAST_MSN_PLAN` block |
| RADAR | the weather, targeting, terrain, SAR and AEWC pictures | the radars' broadcasts and their track and image blocks |

The MFD commands nothing; the radar window is the radars' control panel. With `--theme modern` the holographic MFD
replaces it (chapter 9). Known quirk: the MFD's ENGINE page is unreachable, as in the Python.

## 8.2 EICAS, RT 14

`py -m fmofp_display eicas`. The engine indicating and crew alerting system:

- **Engines**: N1, N2, EGT, fuel flow, oil, vibration for both engines (`BCAST_ENG_ENGINE_STATUS`, the plant's engine
  model through the engine computer).
- **Fuel**: the three tanks, the burn rate, low, critical and leak flags.
- **Hydraulics**: SYS A and B (the primary and backup systems of the hydraulics terminal); SYS C has no system and
  stays unknown.
- **Electrical**: the main and essential bus voltages, the generators (the power terminal).
- **Cabin**: temperature and cabin altitude (the ECS terminal); OXY PSI stays unknown.
- **Countermeasures**: chaff, flares, ECM mode (the defensive systems terminal).
- **Sensors**: the sensor management terminal's health and the fused track count.
- **Self tests**: the avionics terminal's power-on built-in test results.
- **The crew alert list**: decided by the crew alerting computer (RT 26, C++) from the same inputs the display's own
  rules read, relayed as `EICAS_CAS_ALERTS` and drawn in order (warnings, cautions, advisories). While the alert
  computer is silent the list shows one caution, `CAS  ALERTS UNKNOWN`, never an empty list.

## 8.3 Tactical Situation Display (TSD), RT 16

`py -m fmofp_display tsd`. The route and its waypoints, the fused tracks with their class symbols, the radar warning
receiver's contacts and threat ring, the order of battle, and the energy metrics panel (`TSD_FMS_ENERGY`). Known
quirk: the metrics panel floods red while warning contacts are drawn (ICD README section 12).

## 8.4 Stores Management Display (SMS), RT 17

`py -m fmofp_display sms`. The eleven weapon stations, master arm, the release and delivery modes, the selected
station, the load and the armed count. Since unit 32 they are the **stores management computer**'s (RT 28, C++,
`DSP_SMS_STORES`): master arm follows the FMS's weapons state (ARMED, READY as TRAIN, otherwise SAFE), and it takes
commands to select, arm and safe a station, set the modes, release and jettison:

```
fmofp> send SMS_CMD command=ARM_STATION station=2
fmofp> send SMS_CMD command=RELEASE station=1
fmofp> msg SMS_STATUS
```

A release needs master arm ARMED and the station ARMED (SINGLE drops one store, RIPPLE two, SALVO the rest); jettison
drops everything. While the computer is not heard the window shows its own table and says "stores computer: no data".

## 8.5 Lighting modes and themes

Every display takes its own `DSP_*_MODE_CMD` (DAY, NIGHT, NVG): `mode night` from the prompt sends all six, `mode nvg
pfd mfd` two of them, `py -m fmofp_demo --mode night` sends them at the start of a flight. `--theme` chooses the
colours and, with MODERN, the holographic PFD and MFD (chapter 9).

## 8.6 Tests

`fmofp_bus/tests/test_display_feeds.py`, `test_display_render.py`, `test_display_e2e.py`, `test_cas_oracle.py` and
`test_cas_e2e.py` (the alert list against the frozen EICAS rules), `test_stores_oracle.py` and `test_stores_e2e.py`;
`test displays` from the prompt.
