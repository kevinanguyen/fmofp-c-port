# 4. SAR Radar System

**Navigation:** [← Targeting Radar](03_Targeting_Radar_System.md) | [Table of Contents](00_Title_and_TOC.md) | [TFR Radar →](05_TFR_Radar_System.md)

---

## 4.1 Overview

The synthetic aperture radar images the ground to the right of the track and looks for what changed since its last
image. It lives in the radar computer (RT 9, `ofp/partitions/radar/src/sar_radar.cpp`).

| | |
|---|---|
| Modes | STRIPMAP, SPOTLIGHT, SCANSAR, INTERFEROMETRIC, DOPPLER_BEAM (NONE when standing by) |
| Resolution | 0.1 to 10 m (1 m by default); SCANSAR four times the swath at a quarter of the resolution |
| Image | 64 by 64 pixels on the bus (the native 1024 by 1024 image reduced), one every 150 frames (3 s) |
| Strip | its near edge 2 km to the right of the track |
| Inputs | `PLANT_GROUND` relayed as `RDR_SAR_SCENE` (the ground scene); the FMS flight data (the aircraft's position and heading) |
| Outputs | `RDR_SAR_STATUS` (broadcast), the `RDR_SAR_IMAGE` block (to the MFD) with the change regions |
| Command | `RDR_SAR_MODE_CMD`: state, mode, resolution |

## 4.2 The ground

The plant holds a training range laid out along the northbound track from home (`fmofp_plant/ground.py`):
buildings, vehicles, a ship, roads, a river, a lake, a forest, an urban block; some of them move. The radar images
what lies in its strip.

## 4.3 Change detection

Each image is compared with the reference taken at the same place (`detector_` in the code, the frozen
`ChangeDetector` step for step): log ratio, an 11 by 11 box filter, a threshold of the mean plus three standard
deviations, erosion and dilation, four-connected regions. Two quirks are kept and documented (ICD README section 2):
the detector has no guard cells, so a compact change masks itself (the moving ship is never reported), and the box
filter's running sum leaves a residue that reports unchanged ground as CHANGE. Both are future intern tickets.

## 4.4 Operating it

**Radar window:** the *SAR* row: STANDBY, STRIPMAP, SPOTLIGHT, SCANSAR, and a resolution box. The picture is the
MFD's SAR page.

**Prompt:**

```
fmofp> do sar STRIPMAP
fmofp> do sar SPOTLIGHT 0.5
fmofp> msg RDR_SAR_STATUS
fmofp> do imagery
```

The status's `image_seq` counts the images; `scene_valid` and `nav_valid` say whether the radar has the ground and
the aircraft's position. From the mission: INGRESS to EGRESS put the SAR in STRIPMAP, COMPLETE stands it by.

## 4.5 Tests and code

`fmofp_bus/tests/test_sar_oracle.py` (the imaging and the detector against the frozen code), `test_sar_e2e.py`,
`test_plant_ground.py`, `ofp/tests/sar_radar_test.cpp`; `test sar` (or `test 7`).

## 4.6 Troubleshooting

| Symptom | Check |
|---|---|
| No image | `msg RDR_SAR_STATUS`: `nav_valid` needs the FMS flight data, `scene_valid` the plant's ground scene |
| The image is old on the MFD | images come every 3 s and the page keeps the last one |
| SPOTLIGHT stares abeam | no spotlight point can be designated yet (ICD README section 12) |
