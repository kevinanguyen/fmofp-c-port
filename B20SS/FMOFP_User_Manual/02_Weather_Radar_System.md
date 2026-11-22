# 2. Weather Radar System

**Navigation:** [← System Overview](01_System_Overview.md) | [Table of Contents](00_Title_and_TOC.md) | [Targeting Radar →](03_Targeting_Radar_System.md)

---

## 2.1 Overview

The weather radar is one of the five radars in the **radar computer** (RT 9, `fmofp_radar`, C++ in
`B20SS/ofp/partitions/radar`: `weather_model`, `weather_products`, `weather_radar`). It renders a volume of
reflectivity from the weather the plant publishes, scans it, and derives the products the displays draw:
precipitation, vertically integrated liquid (VIL), storm cells, wind shear and turbulence.

| | |
|---|---|
| Modes | SURVEILLANCE, MAPPING, TURBULENCE, WINDSHEAR, PRECIPITATION (NONE when standing by) |
| Range | 10 to 200 km (`range_km`), tilt 0 to 90 degrees |
| Scan | 60 frames, 1.2 s, six azimuths a frame over 360 degrees |
| Volume | 360 azimuths by the elevations by 200 range bins of reflectivity in dBZ |
| Input | `PLANT_WEATHER` relayed as `RDR_WX_WEATHER` (the plant's storm cells and stratiform area, 1 Hz) |
| Outputs | `RDR_WX_STATUS`, `RDR_WX_SCAN` (a summary per scan, broadcast), the `RDR_WX_PRODUCTS` block (the products, 25 Hz, broadcast) |
| Command | `RDR_WX_MODE_CMD`: requested state and mode, range, tilt, `cmd_seq` |

## 2.2 Where the weather comes from

The plant's weather world (`B20SS/fmofp_plant/weather.py`) is the frozen Python's weather generator, step for step:
storm cells that grow, mature and decay with the wind, and one stratiform rain area. The radar renders them into its
volume each scan, with ground clutter and a texture noise. A scenario can put a storm cell into the sky where it
asks (chapter 12).

One departure: the frozen rain area added its 3 dBZ swing to its stored value at every update, so it grew without
limit (past 100 dBZ in a minute). The plant keeps the area's base reflectivity and swings around it (ICD README,
section 2).

## 2.3 Products

- **Precipitation**: the reflectivity per azimuth and range classified by intensity, rounded to three significant
  figures as the Python did.
- **VIL**: the liquid water integrated through the elevations, kg/m2; the scan summary carries the maximum.
- **Storm cells**: connected regions above the cell threshold, labelled in raster order. (The frozen tracker deleted
  each new cell in the call that made it; the port keeps that quirk, so the cells the displays draw are the scan's
  detections, not tracked cells.)
- **Wind shear** events with their severity and whether they are microbursts, and **turbulence** cells by
  category, from the frozen processors.

`RDR_WX_SCAN` sums a scan up: its number, mode, range and tilt, the maximum reflectivity, the cell, area, shear and
turbulence counts, the VIL maximum, the maximum shear.

## 2.4 Operating it

**From the radar window** (`py -m fmofp_display radar`, or the demo): the *Weather radar* row has STANDBY and one
button per mode; the range comes from the window. The picture shows the precipitation, VIL and cells as particles.

**From the prompt** (`py -m fmofp_cli`):

```
fmofp> do wx SURVEILLANCE 150
fmofp> do wx MAPPING tilt=2
fmofp> do wx NONE
fmofp> msg RDR_WX_SCAN
fmofp> status radar
```

`do wx MODE [RANGE_KM] [TILT]` sends `RDR_WX_MODE_CMD` (range 200 km unless given; NONE stands the radar by).
`do precipitation` and `do vil` show the latest scan summary. `send RDR_WX_MODE_CMD requested_state=NORMAL
requested_mode=PRECIPITATION range_km=80` does the same field by field.

**From the mission**: when the mission computer's phase moves to INGRESS, OBJECTIVE or EGRESS the radar computer
puts the weather radar in SURVEILLANCE, and keeps it there at COMPLETE (chapter 10).

## 2.5 What the displays show

- The **radar window** and the **MFD's weather page** draw the products block with the original
  `WeatherRadarDisplay`. Its particle drawing was replaced by one that paints each pass once and lays it down as often
  as the original asked (the original took 7 to 30 s a repaint); the picture is the same, pixel for pixel
  (`fmofp_display/weather_fast.py`).
- The **EICAS** weather rows and the crew alert list read the scan summary.

## 2.6 Tests and code

- `fmofp_bus/tests/test_weather_oracle.py`: every stage against the frozen generators and processors, through
  `fmofp_radar_tool`.
- `fmofp_bus/tests/test_radar_e2e.py`: the radar computer and the plant under the controller.
- `ofp/tests/weather_model_test.cpp`, `weather_products_test.cpp`, `weather_radar_test.cpp`.
- From the prompt: `test weather` (or `test 5`).

## 2.7 Troubleshooting

| Symptom | Check |
|---|---|
| The picture stays empty | `msg RDR_WX_STATUS`: is the state NORMAL and the mode not NONE? `msg RDR_WX_SCAN`: is `scan_id` counting? Is the plant running (`status plant`)? |
| A command is ignored | `msg RDR_WX_STATUS`: `last_cmd_seq` and `cmd_rejected`. A repeated number is ignored by design; the prompt lets the controller number it |
| The window is slow | the particle count grows with the weather; the window repaints in about 0.3 s. `FMOFP_FROZEN_PARTICLES=1` brings back the original drawing for comparison |
