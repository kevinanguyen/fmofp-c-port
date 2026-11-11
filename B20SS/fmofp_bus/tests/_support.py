"""Shared bits for the tests that run the C++ binaries.

The binaries are named by environment variables (CI sets them):
    FMOFP_BC        bc/fmofp_bc
    FMOFP_FCS       partitions/fmofp_fcs
    FMOFP_NAV       partitions/fmofp_nav
    FMOFP_NAV_TOOL  partitions/fmofp_nav_tool
    FMOFP_FMS       partitions/fmofp_fms
    FMOFP_RADAR     partitions/fmofp_radar
    FMOFP_RADAR_TOOL partitions/fmofp_radar_tool
    FMOFP_ENGINE    partitions/fmofp_engine
    FMOFP_ENGINE_TOOL partitions/fmofp_engine_tool
    FMOFP_MISSION   partitions/fmofp_mission
    FMOFP_MISSION_TOOL partitions/fmofp_mission_tool
    FMOFP_COMMS     partitions/fmofp_comms
    FMOFP_DEFENSIVE partitions/fmofp_defensive
    FMOFP_DEFENSIVE_TOOL partitions/fmofp_defensive_tool
    FMOFP_SENSOR    partitions/fmofp_sensor
    FMOFP_SENSOR_TOOL partitions/fmofp_sensor_tool
    FMOFP_POWER     partitions/fmofp_power
    FMOFP_POWER_TOOL partitions/fmofp_power_tool
    FMOFP_SURFACES  partitions/fmofp_surfaces
    FMOFP_SURFACES_TOOL partitions/fmofp_surfaces_tool
    FMOFP_ECS       partitions/fmofp_ecs
    FMOFP_HYDRAULICS partitions/fmofp_hydraulics
    FMOFP_AIRFRAME  partitions/fmofp_airframe
    FMOFP_FDM       partitions/fmofp_fdm
    FMOFP_UTILITIES_TOOL partitions/fmofp_utilities_tool
    FMOFP_AVIONICS  partitions/fmofp_avionics
    FMOFP_AVIONICS_TOOL partitions/fmofp_avionics_tool
"""

import os
import socket
import subprocess
import sys
import unittest


def binary_env():
    """The environment to run a MinGW binary in: its DLLs on PATH on Windows."""
    env = dict(os.environ)
    if sys.platform == "win32" and os.path.isdir(r"C:\msys64\ucrt64\bin"):
        env["PATH"] = r"C:\msys64\ucrt64\bin;" + env.get("PATH", "")
    return env


def needs(*names):
    """Skip the test class unless every named binary is configured."""
    missing = [n for n in names if not os.environ.get(n)]
    return unittest.skipIf(missing, f"set {', '.join(missing)} to the binaries to run")


# A bus at port base B uses UDP ports B+1 .. B+34 (the terminals, the controller at +32, the monitor at +33, the
# command port at +34). Each e2e test owns a base, a multiple of 500, and a few also use base+100 or base+200.
BUS_PORTS = 34
# Where a test's bus goes when its own base cannot be bound: below it, clear of the base before's +200.
_FALLBACK_OFFSETS = (0, -150, -100, -200, -250)


def _bus_ports_free(port_base):
    """True when every UDP port of a bus at `port_base` can be bound on the loopback right now."""
    sockets = []
    try:
        for port in range(port_base + 1, port_base + BUS_PORTS + 1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sockets.append(sock)
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        for sock in sockets:
            sock.close()


def free_port_base(preferred):
    """`preferred` when a bus can be opened there, else the first base just below it where one can.

    Windows reserves blocks of a hundred UDP ports at boot (`netsh int ipv4 show excludedportrange
    protocol=udp`: Hyper-V, WSL and Docker take them), a different set on each machine and after each restart; a
    bind inside one fails with "access denied" although no process holds the port. On 2026-11-11 the block
    55967-56066 sat on test_nav_e2e's 56000 and the gate was red for a reason no code could fix (unit 30). If
    nothing nearby is free either, the preferred base is returned and the test fails with its own message.
    """
    for offset in _FALLBACK_OFFSETS:
        if _bus_ports_free(preferred + offset):
            return preferred + offset
    return preferred


class RadarTool:
    """One fmofp_radar_tool run; answers are read back command by command."""

    def __init__(self):
        self.lines = []
        self.out = []
        self.pos = 0

    def send(self, *commands):
        self.lines += commands

    def run(self):
        result = subprocess.run([os.environ["FMOFP_RADAR_TOOL"]], input="\n".join(self.lines) + "\n",
                                capture_output=True, text=True, timeout=600, env=binary_env())
        assert result.returncode == 0, result.stderr
        self.out = result.stdout.splitlines()
        self.pos = 0
        return self

    def line(self):
        self.pos += 1
        return self.out[self.pos - 1].split()

    def block(self):
        rows = []
        while True:
            row = self.line()
            if row == ["end"]:
                return rows
            rows.append(row)
