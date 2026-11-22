# 3. Targeting Radar System

**Navigation:** [← Weather Radar](02_Weather_Radar_System.md) | [Table of Contents](00_Title_and_TOC.md) | [SAR Radar →](04_SAR_Radar_System.md)

---

## 3.1 Overview

The targeting radar searches for and tracks the aircraft around ours. It lives in the radar computer (RT 9,
`ofp/partitions/radar`: `target_processing`, `targeting_radar`, `track_fusion`) beside the other radars, and its
tracks and the AEWC radar's are fused into one picture.

| | |
|---|---|
| Modes | TARGET_SEARCH, TARGET_TRACK, LOCK, TERRAIN_AVOIDANCE, GROUND_MAPPING (NONE when standing by) |
| Range | 100 km |
| Tracks | up to 12; a detection within 1000 m of a track's predicted position continues it; a track not seen for 15 frames is dropped |
| Input | `PLANT_TRAFFIC` (the plant's aircraft, 5 Hz block) |
| Outputs | `RDR_TGT_STATUS` (broadcast), the `RDR_TGT_TRACKS` block (to the MFD), the fused tracks block `RDR_FUSED_TRACKS` (broadcast) |
| Command | `RDR_TGT_MODE_CMD`: state, mode, track filter (ALL, HOSTILE, FRIENDLY, UNKNOWN), lock track id |

## 3.2 How a track is made

1. The plant flies a dozen aircraft (`fmofp_plant/traffic.py`) and reports them as the antenna would see them.
2. Each detection is analysed (`target_processing`): the signature analyser's class (FIGHTER, BOMBER, HIGH_ALT,
   MISSILE, HELICOPTER, DRONE, STEALTH) from speed, altitude and radar cross-section; the stealth detector's
   probability; the threat rule (HOSTILE when the cross-section is under 3 m2 and the speed over 200 m/s, else
   UNKNOWN; there is no IFF, so no track is ever FRIENDLY by identity).
3. The track table continues, starts and drops tracks; a lock is held on one track.
4. Every 25 frames the fusion clusters the targeting and AEWC tracks within 500 m into fused tracks, each with a
   confidence of 1 minus the product of 1 minus each report's weight.

## 3.3 Lock-on

A lock is taken only in TARGET_TRACK mode (as the Python refused it in any other): the command carries the track id.
The status reports the lock (NONE, ACQUIRING, LOCKED), the locked track and the lock quality (signal-to-noise over
30 dB); a lock below quality 0.5 is ACQUIRING. While locked the radar may report jamming.

## 3.4 Operating it

**Radar window:** the *Targeting radar* row has STANDBY, TARGET_SEARCH and TARGET_TRACK with a *lock track* box. The
picture is on the MFD's radar page (TARGETING).

**Prompt:**

```
fmofp> do tgt TARGET_SEARCH
fmofp> do tgt TARGET_SEARCH HOSTILE
fmofp> do tgt-lock 3
fmofp> msg RDR_TGT_STATUS
fmofp> do tracks
```

`do tgt-lock N` sends TARGET_TRACK with track N. From the mission: INGRESS to EGRESS put the radar in TARGET_SEARCH,
COMPLETE stands it by (chapter 10).

**Scenarios** inject an aircraft into the plant's traffic (`radar_contact` events); the radar finds it like any other.

## 3.5 Consumers

- MFD targeting page: the tracks block, drawn by `TargetingRadarDisplay`.
- TSD: the fused tracks.
- EICAS and the crew alert list: the fused track count, hostile tracks.
- Defensive systems (RT 22): hostile fused tracks become radar warning receiver contacts.
- Holographic MFD: the targeting and AEWC tracks within 100 nm (chapter 9).

## 3.6 Tests and code

`fmofp_bus/tests/test_targeting_oracle.py` (against the frozen processing, tracking and fusion),
`test_targeting_e2e.py`, `ofp/tests/target_processing_test.cpp`, `targeting_radar_test.cpp`,
`track_fusion_test.cpp`; `test targeting` (or `test 8`) from the prompt.

## 3.7 Troubleshooting

| Symptom | Check |
|---|---|
| No tracks | `msg RDR_TGT_STATUS`: state NORMAL, mode TARGET_SEARCH or TARGET_TRACK? Is the plant flying its traffic (`status plant`, `PLANT_TRAFFIC`)? |
| A lock is not taken | the mode must be TARGET_TRACK and the track id one the radar holds (`do tracks`) |
| Every target is UNKNOWN | expected: no IFF interrogator exists (ICD README section 12) |
