"""FMOFP entry point: starts the aircraft on the bus.

    python FMOFP/Main.py [options]        (from B20SS/; the same options as `python -m fmofp_demo`)

This file used to boot the all-Python application: core/system_manager.py started every subsystem as a
Python service, wired together by local_messaging and the Python MIL_STD_1553B library. Those were retired
when the flight software was ported to C++ (B20SS/ofp, one process per subsystem on a simulated
MIL-STD-1553B bus; the port's unit 29). The aircraft is now started by fmofp_demo: the plant, every C++
partition, the six display windows and the bus controller, with one dashboard line a second. This file hands
over to it so the documented command keeps working.

It needs the C++ built first (B20SS/ofp/README.md). `--help` lists the options; Ctrl-C stops everything.
"""
import os
import sys


def main(argv=None):
    # fmofp_demo is a sibling of the FMOFP package: make B20SS/ importable however this file was started.
    b20ss = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if b20ss not in sys.path:
        sys.path.insert(0, b20ss)
    from fmofp_demo.demo import main as demo_main
    return demo_main(argv)


if __name__ == "__main__":
    sys.exit(main())
