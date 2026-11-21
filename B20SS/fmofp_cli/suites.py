"""The prompt's `test` command: upstream's nine test suites, and the rest, as the port's test modules (unit 35).

Upstream's `test` asked which of nine suites to run and ran it inside the live program, against its own objects. The
port's tests build their own bus (each e2e test its own controller, partitions and plant on a port base of its own),
so the prompt runs them in a child process beside whatever bus it is watching, with the environment the gate gives
them (`verify.sh`'s `export_binaries`): FMOFP_BC and one FMOFP_<NAME> per C++ program of the build.
"""

import glob
import os
import subprocess
import sys
from collections import namedtuple

B20SS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Suite = namedtuple("Suite", "name title modules")

# Upstream's menu, in its order, then the port's other subsystems.
SUITES = (
    Suite("precip-vil", "Combined Precipitation & VIL Flow Test", ("test_weather_oracle", "test_radar_e2e")),
    Suite("fms", "FMS System Test", ("test_fms_e2e",)),
    Suite("fcs", "Flight Control System Test", ("test_fcs_e2e",)),
    Suite("messages", "Predefined Messages Test", ("test_cli", "test_messages", "test_command_port")),
    Suite("weather", "Weather Radar Test (All Modes)", ("test_weather_oracle", "test_radar_e2e", "test_plant_weather")),
    Suite("tfr", "TFR Radar Test (All Modes)", ("test_tfr_oracle", "test_tfr_e2e", "test_plant_terrain")),
    Suite("sar", "SAR Radar Test (All Modes)", ("test_sar_oracle", "test_sar_e2e", "test_plant_ground")),
    Suite("targeting", "Targeting Radar Test (All Modes)", ("test_targeting_oracle", "test_targeting_e2e",
                                                            "test_plant_traffic")),
    Suite("aewc", "AEWC Radar Test (All Modes)", ("test_aewc_oracle",)),
    Suite("bus", "The simulated MIL-STD-1553B bus (upstream's test_1553b)",
          ("test_word", "test_command_word", "test_transport", "test_remote_terminal", "test_block",
           "test_bus_integration")),
    Suite("nav", "Navigation", ("test_nav_oracle", "test_nav_e2e")),
    Suite("engine", "Engine management and fuel", ("test_engine_oracle", "test_engine_e2e", "test_plant_engine")),
    Suite("mission", "Mission computer and communications", ("test_mission_oracle", "test_mission_e2e",
                                                             "test_comms_e2e", "test_plant_rf")),
    Suite("defensive", "Defensive systems and sensor management", ("test_defensive_oracle", "test_defensive_e2e",
                                                                   "test_sensor_oracle", "test_sensor_e2e")),
    Suite("systems", "Power, surfaces, utilities, avionics, crew alerting, stores",
          ("test_power_oracle", "test_power_e2e", "test_surfaces_oracle", "test_surfaces_e2e",
           "test_utilities_oracle", "test_utilities_e2e", "test_avionics_oracle", "test_avionics_e2e",
           "test_cas_oracle", "test_cas_e2e", "test_stores_oracle", "test_stores_e2e")),
    Suite("displays", "The display terminals and windows", ("test_display_feeds", "test_display_render",
                                                            "test_display_e2e", "test_holographic")),
    Suite("scenario", "The scenario engine and the recorder", ("test_scenario_oracle", "test_scenario_e2e",
                                                               "test_recorder", "test_recorder_e2e")),
)
BY_NAME = {s.name: s for s in SUITES}


def resolve(words):
    """Suite names (or upstream's menu numbers 1-9, or test module names) to module names, in order, each once.
    `all` is every suite. ValueError for a word that is none of these."""
    modules = []
    for word in words:
        key = word.lower()
        if key == "all":
            chosen = [m for s in SUITES for m in s.modules]
        elif key.isdigit() and 1 <= int(key) <= 9:
            chosen = list(SUITES[int(key) - 1].modules)
        elif key in BY_NAME:
            chosen = list(BY_NAME[key].modules)
        elif os.path.isfile(os.path.join(B20SS, "fmofp_bus", "tests", f"{key}.py")):
            chosen = [key]
        else:
            raise ValueError(f"no suite {word!r}: 'test list' shows them")
        modules.extend(mod for mod in chosen if mod not in modules)
    return modules


def listing():
    lines = []
    for i, suite in enumerate(SUITES, 1):
        number = f"{i})" if i <= 9 else "  "
        lines.append(f"  {number:3} {suite.name:11} {suite.title}: {', '.join(suite.modules)}")
    lines.append("  all         every suite above")
    return lines


def binary_env(build_dir, env=None):
    """The environment the tests read the C++ programs from: FMOFP_BC and FMOFP_<NAME> for each fmofp_<name>
    program of the build (as verify.sh's export_binaries), the MSYS2 runtime on PATH on Windows, offscreen Qt."""
    env = dict(os.environ if env is None else env)
    exe = ".exe" if sys.platform == "win32" else ""
    bc = os.path.join(build_dir, "bc", "fmofp_bc" + exe)
    if os.path.isfile(bc):
        env["FMOFP_BC"] = bc
    for path in glob.glob(os.path.join(build_dir, "partitions", "fmofp_*" + exe)):
        name = os.path.basename(path)[len("fmofp_"):]
        if exe:
            name = name[:-len(exe)]
        env[f"FMOFP_{name.upper()}"] = path
    msys = r"C:\msys64\ucrt64\bin"
    if sys.platform == "win32" and os.path.isdir(msys):
        env["PATH"] = msys + os.pathsep + env.get("PATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def command(modules):
    return [sys.executable, "-m", "unittest"] + [f"fmofp_bus.tests.{mod}" for mod in modules]


def run(modules, build_dir, out=print, popen=subprocess.Popen):
    """Runs the modules in a child process from B20SS, each output line to `out`; returns its exit code."""
    process = popen(command(modules), cwd=B20SS, env=binary_env(build_dir), stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    with process.stdout:
        for line in process.stdout:
            line = line.rstrip("\n")
            # The frozen display code logs at INFO and DEBUG through its own handler: keep what a reader needs.
            if " - INFO - " in line or " - DEBUG - " in line:
                continue
            out(line)
    return process.wait()
