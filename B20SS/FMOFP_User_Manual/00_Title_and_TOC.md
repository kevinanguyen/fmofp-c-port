# Flight Management Operating Flight Program (FMOFP)
## User Manual

**Edition:** C++ port, 2026-11-22 (ICD v1.29)
**Applies to:** branch `port/cpp` of the FMOFP repository

---

## What this manual describes

FMOFP is a training avionics suite: a simulated military aircraft whose flight software runs as separate
programs that talk only over a simulated MIL-STD-1553B data bus. Since the C++ port (2026) the flight logic
(flight control, navigation, flight management, the five radars, engines and fuel, mission, communications,
defensive systems, sensors, power, surfaces, environmental control, hydraulics, airframe, flight data recording,
avionics health, crew alerting, stores management) is C++; the cockpit displays, the simulated world (the
"plant"), the scenario engine, the debug prompt, the data recorder and the tests are Python. Earlier editions of
this manual described a single Python application with its own messaging library; that application is retired
(its `py FMOFP/Main.py` now starts the demo described here).

Every command in this manual was run on the port before it was written.

---

## Document Organization

| File | Chapter |
|---|---|
| [00a_Getting_Started.md](00a_Getting_Started.md) | Getting started: install, build, fly the demo in ten minutes |
| [00b_Legal_Information.md](00b_Legal_Information.md) | Legal information and development status |
| [01_System_Overview.md](01_System_Overview.md) | 1. System overview and architecture |
| [02_Weather_Radar_System.md](02_Weather_Radar_System.md) | 2. Weather radar |
| [03_Targeting_Radar_System.md](03_Targeting_Radar_System.md) | 3. Targeting radar and track fusion |
| [04_SAR_Radar_System.md](04_SAR_Radar_System.md) | 4. Synthetic aperture radar |
| [05_TFR_Radar_System.md](05_TFR_Radar_System.md) | 5. Terrain-following radar |
| [06_AEWC_Radar_System.md](06_AEWC_Radar_System.md) | 6. Airborne early warning and control radar |
| [07_Primary_Flight_Display.md](07_Primary_Flight_Display.md) | 7. Primary flight display |
| [08_Multi_Function_Display.md](08_Multi_Function_Display.md) | 8. Multi-function display, EICAS, TSD and SMS |
| [09_Holographic_Display_System.md](09_Holographic_Display_System.md) | 9. Themes and the holographic displays |
| [10_Flight_Management_Integration.md](10_Flight_Management_Integration.md) | 10. Flight management, flight control and the aircraft |
| [11_Communication_Messaging.md](11_Communication_Messaging.md) | 11. The bus: messages, the ICD and the tools that read it |
| [12_Operational_Procedures.md](12_Operational_Procedures.md) | 12. Operating procedures: the demo, scenarios, the prompt, recording |
| [13_System_Maintenance.md](13_System_Maintenance.md) | 13. Building, testing, debugging and troubleshooting |
| [14_Appendices.md](14_Appendices.md) | 14. Appendices: terminal addresses, ports, commands, glossary |

---

## Document Conventions

- `monospace` is a command, a file, a program or an ICD message name (`RDR_WX_MODE_CMD`).
- Commands are run from the `B20SS` folder unless the text says otherwise. On Windows the Python launcher is
  `py`; on the maintainers' machine with a free-threaded default, `py -3.14`.
- *RT n* is a remote terminal address on the bus (chapter 14 lists them). A *partition* is one C++ program, a
  *terminal* anything with an address.
- "The frozen Python" is the original Python code the C++ was translated from, kept under `B20SS/FMOFP/` and used
  by the tests as the reference.

## How to Use This Manual

- **New interns**: read [Getting Started](00a_Getting_Started.md), then [chapter 1](01_System_Overview.md) and
  [chapter 12](12_Operational_Procedures.md). Fly the demo before reading any radar chapter.
- **Working on a subsystem**: its chapter says what it does, what it reads and publishes on the bus, how to drive
  it from the prompt and where its code and tests are. [Chapter 13](13_System_Maintenance.md) says how to build,
  test and debug it.
- **Deeper reference**: `B20SS/icd/README.md` (every bus decision and every place the port departs from the frozen
  Python), `B20SS/icd/ICD_TABLES.md` (every message, field by field), `B20SS/ofp/docs/ARCHITECTURE.md` and
  `B20SS/ofp/docs/DEBUGGING.md`.
