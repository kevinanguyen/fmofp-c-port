# 7. Primary Flight Display (PFD)

**Navigation:** [← AEWC Radar](06_AEWC_Radar_System.md) | [Table of Contents](00_Title_and_TOC.md) | [Multi-Function Display →](08_Multi_Function_Display.md)

---

## 7.1 Overview

The PFD is display terminal RT 11, a Python program (`py -m fmofp_display pfd`) that runs the original
`PrimaryFlightDisplay` class unchanged and feeds it from the bus. It draws the attitude indicator and pitch ladder,
the airspeed and altitude tapes, the heading indicator, the flight mode, the g and angle-of-attack indicators and the
envelope warnings.

| | |
|---|---|
| Listens to | `BCAST_FMS_FLIGHT_DATA` (attitude, speeds, altitude, heading, Mach, g, AoA, energy, position, 10 Hz), `BCAST_FMS_STATUS` (flight mode, tactical systems), `BCAST_FMS_ATTITUDE_STATUS` (the envelope limits hit); since ICD v1.27 also the fuel (`BCAST_ENG_FUEL_STATUS`) and the radar warning contacts block, which the holographic PFD draws |
| Publishes | `DSP_PFD_STATUS` (its state and lighting mode) |
| Command | `DSP_PFD_MODE_CMD`: DAY, NIGHT or NVG |
| Feed | `fmofp_display/flight_feed.py` (`FlightDataFeed`): the dictionaries the display's getters returned, with only the fields the bus vouches for |

## 7.2 What it shows and where it comes from

| Element | Source on the bus |
|---|---|
| Attitude, pitch ladder | the FMS's roll and pitch (the FCS's measured attitude, through the FMS) |
| Airspeed and Mach tapes | the FMS's airspeed and Mach |
| Altitude tape, vertical speed | the FMS's altitude and vertical speed |
| Heading | the FMS's heading (true) |
| Flight mode | `BCAST_FMS_STATUS.flight_mode`: NORMAL, COMBAT, STEALTH, TRAINING, EMERGENCY |
| G and AoA | the FMS's g and angle of attack against the flight mode's limits |
| Envelope warnings | the bits of `BCAST_FMS_ATTITUDE_STATUS`: BANK_ANGLE, PITCH_ANGLE, ROLL_RATE, PITCH_RATE, YAW_RATE |

## 7.3 Invalid data

A field the bus does not vouch for (its SSM not NORMAL, or no message for two seconds) is crossed out in amber by the
display's own validity marking (`data_validity.py`), never shown as a stale number. Stop the FMS and the PFD crosses
out its readouts within two seconds.

## 7.4 Operating it

- Start it alone against a running bus: `py -m fmofp_display pfd --port-base 51000`.
- Lighting mode: from the prompt `mode night pfd` (or `mode night` for all six displays); the demo's `--mode`.
- Theme: `--theme modern` builds the holographic PFD instead (chapter 9).
- Its log is quiet by default; `--verbose` keeps the display code's INFO lines.

## 7.5 Tests

`fmofp_bus/tests/test_display_feeds.py` (the flight feed's dictionaries), `test_display_render.py` (the window painted
offscreen with and without data), `test_display_e2e.py` (every display terminal on the real bus).

## 7.6 Known display quirks

From the frozen display code, kept: the Mach number overlaps the speed tape; "LON -0.0000" at home. Both are listed in
the ICD README's backlog.
