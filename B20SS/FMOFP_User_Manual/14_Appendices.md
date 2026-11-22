# 14. Appendices

**Navigation:** [← Building and Testing](13_System_Maintenance.md) | [Table of Contents](00_Title_and_TOC.md)

---

## A. Terminal addresses

The prompt accepts the number or the name (`status radar`, `status 9`).

| RT | Name | Program | Language |
|---|---|---|---|
| 1 | avionics | `fmofp_avionics` | C++ |
| 2 | comms | `fmofp_comms` | C++ |
| 3 | engine | `fmofp_engine` | C++ |
| 4 | ecs | `fmofp_ecs` | C++ |
| 5 | fcs | `fmofp_fcs` | C++ |
| 6 | mission | `fmofp_mission` | C++ |
| 7 | nav | `fmofp_nav` | C++ |
| 8 | power | `fmofp_power` | C++ |
| 9 | radar | `fmofp_radar` (weather, terrain-following, targeting and fusion, AEWC, SAR) | C++ |
| 10 | sensors | `fmofp_sensor` | C++ |
| 11 | pfd | `py -m fmofp_display pfd` | Python |
| 12 | fms | `fmofp_fms` | C++ |
| 13 | mfd | `py -m fmofp_display mfd` | Python |
| 14 | eicas | `py -m fmofp_display eicas` | Python |
| 15 | radar display | `py -m fmofp_display radar` | Python |
| 16 | tsd | `py -m fmofp_display tsd` | Python |
| 17 | sms | `py -m fmofp_display sms` | Python |
| 18 | hud | none (the Python HUD was an empty placeholder) | |
| 19 | hydraulics | `fmofp_hydraulics` | C++ |
| 20 | airframe | `fmofp_airframe` | C++ |
| 21 | surfaces | `fmofp_surfaces` | C++ |
| 22 | defensive | `fmofp_defensive` | C++ |
| 23 | fdm | `fmofp_fdm` | C++ |
| 26 | cas | `fmofp_cas` | C++ |
| 27 | plant | `py -m fmofp_plant` | Python |
| 28 | stores | `fmofp_stores` | C++ |
| 31 | broadcast | | |

Free: 24, 25 (the gate tests' stub terminals), 29, 30. The bus controller is `fmofp_bc`.

## B. Ports

| Port | What |
|---|---|
| 51000 | the default port base (`--port-base N` everywhere) |
| base + RT | each terminal |
| base + 32 | the bus controller |
| base + 33 | the fixed monitor port |
| base + 34 | the command port |

## C. Timing

A 20 ms minor frame, 50 to a one-second major frame; terminals step on the controller's synchronise mode code. Rates
are 50, 25, 10, 5 and 1 Hz or aperiodic. The schedule's worst minor frame is 8784 us of the 10000 us budget (ICD
v1.29, 25 terminals).

## D. The prompt's shortcuts (`do`)

| Name | Sends |
|---|---|
| `wx MODE [range_km] [tilt]` | the weather radar's mode command |
| `tfr MODE [clearance_ft]` | the terrain-following radar's |
| `sar MODE [resolution_m]` | the SAR's |
| `tgt MODE` | the targeting radar's |
| `tgt-lock TRACK` | the targeting radar to TARGET_TRACK on that track |
| `aewc MODE`, `aewc-sector START END [elevation]` | the AEWC radar's mode and sector scan |
| `attitude roll= pitch= yaw=` | the FMS's attitude command |
| `nav ...`, `autopilot altitude= airspeed= heading= vertical_speed=` | the FMS's navigation update and autopilot targets |
| `maneuver NAME [dive_angle]` | the FMS's maneuver command |
| `flight-mode MODE` | the FMS's flight mode |
| `surface SURFACE PERCENT` | the FCS's surface command (it flies the plant under `--dynamics`) |
| `objective TEXT`, `roe TEXT`, `intel KEY TEXT` | the mission briefing |
| `clear-objectives`, `clear-roe`, `clear-intel` | the briefing's lists emptied |
| `precipitation`, `vil`, `echo-top`, `elevation`, `imagery`, `tracks` | readings of the messages that carry those products |

`do` alone lists them with their help; any field may also be given as `field=value`.

## E. The prompt's test suites (`test`)

Upstream's nine, by name or number: `precip-vil` (1), `fms` (2), `fcs` (3), `messages` (4), `weather` (5), `tfr` (6),
`sar` (7), `targeting` (8), `aewc` (9). The port's others: `bus`, `nav`, `engine`, `mission`, `defensive`, `systems`,
`displays`, `scenario`. `test all` runs every one; `test test_<module>` runs one module.

## F. Documents

| Document | Where |
|---|---|
| The ICD and its decisions | `B20SS/icd/fmofp_icd.xml`, `B20SS/icd/README.md`, `B20SS/icd/ICD_TABLES.md` |
| The C++ | `B20SS/ofp/README.md`, `ofp/CLAUDE.md`, `ofp/docs/ARCHITECTURE.md`, `ofp/docs/DEBUGGING.md` |
| Intern tickets (draft) | `B20SS/ofp/docs/TICKETS.md` |
| The project's working file | `CLAUDE.md` at the repository root |
| The display code's design notes | `B20SS/FMOFP/docs/Displays/` |

## G. Glossary

| Term | Meaning |
|---|---|
| Bus | the simulated MIL-STD-1553B data bus every program talks over |
| Bus controller (BC) | the one program that drives the bus and keeps its clock |
| Remote terminal (RT) | a program on the bus, addressed 1 to 30 |
| Subaddress (SA) | a terminal's mailbox for one message |
| ICD | interface control document: what every message holds |
| Partition | one C++ flight program |
| Plant | the simulated aircraft and its world |
| Relay | the controller copying a message from its producer to a consumer |
| Broadcast | a message sent to RT 31 for several listeners |
| Block | a transfer longer than one message, in segments |
| SSM | sign/status matrix: a value's validity |
| `cmd_seq` | a command's number; a terminal ignores a repeat of the last one it accepted |
| Oracle test | a test that runs the frozen Python beside the C++ and compares their answers |
| Frozen Python | the original Python application under `B20SS/FMOFP/`, kept as the reference |
| Overrun | a minor frame that took longer than 20 ms |
