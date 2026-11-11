"""The debug CLI on the bus (unit 28): userCLI.py's status, send and scenario commands as a REPL over the bus
controller's monitor port (what every terminal says) and command port (what the operator sends).

    py -m fmofp_cli [--port-base 51000] [-c "status" -c "send MSN_CMD command=SET_PHASE phase=INGRESS"]
"""
