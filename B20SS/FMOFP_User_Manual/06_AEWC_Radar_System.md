# 6. AEWC Radar System

**Navigation:** [← TFR Radar](05_TFR_Radar_System.md) | [Table of Contents](00_Title_and_TOC.md) | [Primary Flight Display →](07_Primary_Flight_Display.md)

---

## 6.1 Overview

The airborne early warning and control radar watches the whole sky to long range in six sectors, looks for stealth
aircraft and copes with jamming. It lives in the radar computer (RT 9, `ofp/partitions/radar/src/aewc_radar.cpp`).

| | |
|---|---|
| Modes | AEWC_SEARCH, AEWC_SURVEILLANCE, SECTOR_SCAN, STEALTH_DETECTION, ELECTRONIC_PROTECTION, AEWC_TRACK, GROUND_MAPPING (NONE when standing by) |
| Range | 400 km |
| Sectors | six of 60 degrees, counted counter-clockwise from east, elevation -15 to 45 degrees; dwell shared by priority |
| Input | `PLANT_TRAFFIC` (the same aircraft the targeting radar sees) |
| Outputs | `RDR_AEWC_STATUS` (broadcast), the `RDR_AEWC_TRACKS` block (to the MFD) with the six sectors; its tracks join the fusion (weight 0.7) |
| Command | `RDR_AEWC_MODE_CMD`: state, mode, sector start and end azimuth, elevation |

## 6.2 Detection, as the Python had it

The radar equation is the frozen Python's, kept as written: it mixes dBW and dBm, so the signal-to-noise ratio falls
to zero beyond about 40 km and the far aircraft are held as undetected tracks. This is a documented quirk (ICD
README section 2) and a future intern ticket. The stealth detector, the ECM assessment (jam type, mitigation,
severity per sector) and the sector priorities are ported step for step.

## 6.3 Operating it

**Radar window:** the *AEWC radar* row: STANDBY, AEWC_SEARCH, AEWC_SURVEILLANCE, AEWC_TRACK. The picture is the MFD's
AEWC page.

**Prompt:**

```
fmofp> do aewc AEWC_SEARCH
fmofp> do aewc-sector 10 80
fmofp> msg RDR_AEWC_STATUS
```

`do aewc-sector START END [ELEVATION]` sends SECTOR_SCAN with those azimuths. From the mission: INGRESS to EGRESS put
it in AEWC_SEARCH, COMPLETE stands it by.

## 6.4 Tests and code

`fmofp_bus/tests/test_aewc_oracle.py`, `ofp/tests/aewc_radar_test.cpp`; `test aewc` (or `test 9`).

## 6.5 Troubleshooting

| Symptom | Check |
|---|---|
| Distant aircraft never detected | the radar equation's dBW/dBm mix (6.2): expected |
| `jammed_sectors` set | the ECM assessment found jamming in those sectors; `RDR_AEWC_TRACKS`' sector records say which kind |
