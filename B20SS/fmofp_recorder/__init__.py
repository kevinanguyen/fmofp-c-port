"""The data recorder: what upstream's Python services wrote into SQLite, written from the bus (unit 33).

    py -m fmofp_recorder [--port-base N] [--out DIR] [--seconds S] [--fixed-monitor]

A client of the bus controller like the debug prompt: it asks the command port for a copy of the monitor stream,
so it runs beside `py -m fmofp_demo`. `tables.py` lists the tables, their database files, their rates and how each
row is made; `py -m fmofp_cli` reads them back (`tables`, `table NAME [N]`).
"""
