# 9. Themes and the Holographic Displays

**Navigation:** [← Multi-Function Display](08_Multi_Function_Display.md) | [Table of Contents](00_Title_and_TOC.md) | [Flight Management →](10_Flight_Management_Integration.md)

---

## 9.1 Themes

The display code's theme manager (`visual/theme_manager.py`) has three themes: **CLASSIC** (green monochrome, the
default), **MODERN** (blue-teal, gradients) and **NIGHT** (dimmed for night operations). Each display program and the
demo take the theme at start:

```bash
py -m fmofp_demo --theme modern
py -m fmofp_display pfd --theme night
```

The theme sets the standard displays' colours and fonts. Under MODERN the theme's `display_types` build the
**holographic PFD and MFD** instead of the standard ones, as upstream's display factories meant to.

## 9.2 What changed from upstream

Upstream never fed the holographic displays: the holographic PFD had no data source (its factory refused to build it,
`PROVIDES_FLIGHT_DATA = False`), and the holographic MFD drew an empty tactical picture beside panels of fixed values
(THRUST 92 %, fuel 85 %, AIM-120C x4, six radio channels, "MESSAGES: 2 NEW"). The port feeds both from the bus
(`fmofp_display/holographic.py`) without editing the frozen files, and marks as missing anything the bus does not
carry.

## 9.3 The holographic PFD

- Altitude, airspeed, Mach, heading, pitch, roll, vertical speed, g, AoA and energy from the FMS's flight data each
  tick.
- The whole picture is crossed out (`NO FMS DATA`) whenever any of altitude, airspeed, heading, pitch or roll is
  missing or stale.
- The mode line is the FMS's flight mode; the status corner says `FMS OK` or `NO FMS`.
- The fuel state is the engine computer's total as a percent of the three tanks; `--` while it is silent.
- The threat ring is the radar warning receiver's most urgent hostile contact, at its bearing relative to the nose.
- The tapes' target bugs sit on the present value: no autopilot target reaches the PFD.
- The bus's DAY/NIGHT/NVG command is kept but not applied: the holographic displays have no lighting modes.

## 9.4 The holographic MFD

Pages: TACTICAL, NAVIGATION, SYSTEMS, COMMUNICATIONS, WEAPONS, RADAR (its own buttons).

- **Tactical picture**: the targeting radar's (`T`n) and the AEWC radar's (`A`n) tracks within 100 nm; hostile tracks
  are threats; the route's waypoints. Heading and speed are relative to the aircraft, as the radars measure them. No
  track is drawn without the aircraft's altitude.
- **Panels**: engine (thrust, EGT, N1, oil), fuel (total, centre tank, flow, endurance), radar (mode, range, targets),
  weapons and inventory (the stores computer, by a second relay `MFD_SMS_STORES`), selected station, radio, satcom
  and data link. The seven frozen panel methods are rebuilt at start with each fixed value replaced by a bus value; if
  the frozen file changes so that a value is not found, the display refuses to build rather than show a fixed value.
- **Missing**: the INS reads `INS: NOT CARRIED`; the encryption and IFF rows are gone; the navigation page's terrain
  is the terrain-following radar's profile, crossed out without one.
- **The RADAR page is crossed out** (`NOT FED: SEE THE RADAR WINDOW`): the embedded holographic weather display has no
  bus feed. The radar window draws the weather.

## 9.5 Tests

`fmofp_bus/tests/test_holographic.py`: the values built from fake bus data, the rewrite of the frozen MFD methods
against the frozen source and its refusal when a value is missing, each theme's windows painted with and without
data.
