# 5. TFR Radar System

**Navigation:** [← SAR Radar](04_SAR_Radar_System.md) | [Table of Contents](00_Title_and_TOC.md) | [AEWC Radar →](06_AEWC_Radar_System.md)

---

## 5.1 Overview

The terrain-following radar looks at the ground ahead, grades the clearance and plans the altitudes that keep the
set clearance. It lives in the radar computer (RT 9, `ofp/partitions/radar/src/terrain_following.cpp`).

| | |
|---|---|
| Modes | TFR_SEARCH, TFR_TRACK, TFR_ACTIVE, TERRAIN_FOLLOWING, OBSTACLE_AVOIDANCE, GROUND_MAPPING (NONE when standing by) |
| Set clearance | 30 to 5000 ft, 1000 ft until commanded |
| Clearance levels | CLEAR (600 m or more), LOW (300), CAUTION, PULL_UP (under 150 m) |
| Inputs | `PLANT_TERRAIN` relayed as `RDR_TFR_TERRAIN` (100 elevation samples over 10 km ahead, a new profile every 0.2 s); `PLANT_SENSORS` relayed as `RDR_TFR_SENSORS` |
| Outputs | `RDR_TFR_STATUS`, `RDR_TFR_GUIDANCE` (broadcast; also relayed to the FCS as `FCS_TERRAIN` for the ground collision avoidance system), the `RDR_TFR_ELEVATION` block |
| Command | `RDR_TFR_MODE_CMD`: state, mode, set clearance |

## 5.2 The terrain

The plant's hills (`fmofp_plant/terrain.py`) are a sum of sines and ripples around 1000 m; `py -m fmofp_plant
--terrain-ft 500` flattens the world for a test. The profile follows the aircraft's position and heading.

## 5.3 Guidance

From each profile the radar finds the minimum clearance and where it is, grades it (the master level only rises while advisories remain and resets when none do), sets the pull-up, high-terrain
and steep-terrain warnings, and runs the path optimiser: commanded altitudes along the profile, limited to 25 m/s of
altitude change, that keep the set clearance. `RDR_TFR_GUIDANCE` carries the level, the warnings, the clearance and
the next commanded altitude. The Python assessed every profile at a fixed 1000 m; the port uses the aircraft's
altitude.

## 5.4 Operating it

**Radar window:** the *Terrain-following radar* row: STANDBY, TFR_SEARCH, TFR_TRACK, TERRAIN_FOLLOWING,
GROUND_MAPPING, and a *set clearance* box. The window draws the profile under the weather picture; the MFD has a
terrain page.

**Prompt:**

```
fmofp> do tfr TERRAIN_FOLLOWING 500
fmofp> msg RDR_TFR_GUIDANCE
fmofp> do elevation
```

From the mission: every configuring phase (INGRESS, OBJECTIVE, EGRESS, COMPLETE) puts it in TERRAIN_FOLLOWING.

## 5.5 Consumers

- The FCS's ground collision avoidance (TERRAIN alert under 500 ft of clearance): chapter 10.
- The radar window's terrain picture and the MFD's terrain page.
- The holographic MFD's navigation terrain (chapter 9).

## 5.6 Tests and code

`fmofp_bus/tests/test_tfr_oracle.py`, `test_tfr_e2e.py`, `test_plant_terrain.py`,
`ofp/tests/terrain_following_test.cpp`; `test tfr` (or `test 6`).

## 5.7 Troubleshooting

| Symptom | Check |
|---|---|
| Level stays NONE | `msg RDR_TFR_STATUS`: a mode other than NONE? Does the plant publish `PLANT_TERRAIN` (`status plant`)? |
| PULL_UP stays on | the master level only rises while any advisory remains in the profile, and drops back to CLEAR when none does, as the Python's did |
| The MFD's terrain page says "Health: CLEAR" in red | a known display quirk: the page passes the level as the health (ICD README section 12) |
