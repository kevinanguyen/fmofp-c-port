"""A display's command and another sender's on one radar command subaddress.

The radar window's mode buttons load a command on the display's transmit subaddress and the controller relays
it to the radar ten times a second. A radar takes a command when its number differs from the last one it
accepted, so a command left standing there was taken again a tenth of a second after any scripted or client
command to the same radar: found on the bus on 2026-11-14 (ICD README section 2). The display now withdraws its
command after a second. Here the real radar computer and the real controller run with a display terminal at
RT 15 that asks for SURVEILLANCE, and the controller's script sends MAPPING to the same radar three seconds of
bus later: the radar must go to MAPPING and stay there.

Needs FMOFP_BC and FMOFP_RADAR (CI sets them).
"""

import os
import subprocess
import tempfile
import time
import unittest

from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import TerminalState, WeatherMode
from fmofp_bus.monitor import Monitor
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base, needs
from fmofp_display.terminal import COMMAND_HOLD_FRAMES, LAST_COMMAND_SEQ, DisplayTerminal, withdrawn

PORT_BASE = free_port_base(61500)
FRAMES = 300
SCRIPT_FRAME = 150
SCRIPT_SEQ = 201
SYNC_MODE_CODE = 17
RADAR_RT = m.RdrWxStatus.RT
DISPLAY_RT = m.DspRadarStatus.RT


def survey(seq):
    return m.DspRdrWxCmd(payload=m.RdrWxModeCmd(cmd_seq=seq, requested_state=TerminalState.NORMAL,
                                                 requested_mode=WeatherMode.SURVEILLANCE, range_km=200.0, tilt=0.0))


class WithdrawnTest(unittest.TestCase):
    def test_a_withdrawn_command_is_the_same_words_with_no_number(self):
        command = survey(7)
        gone = withdrawn(command)
        self.assertEqual(0, gone.payload.cmd_seq)
        self.assertEqual(dataclass_without_seq(command), dataclass_without_seq(gone))
        self.assertEqual(7, command.payload.cmd_seq, "the original is left alone")
        plain = m.RdrWxModeCmd(cmd_seq=9, requested_state=TerminalState.STANDBY)
        self.assertEqual(0, withdrawn(plain).cmd_seq)
        self.assertIsNone(withdrawn(m.DspRadarStatus()), "a message with no cmd_seq is not a command")

    def test_the_displays_count_below_the_other_senders(self):
        terminal = DisplayTerminal(DISPLAY_RT, PORT_BASE + 200, m.DspRadarStatus, m.DspRadarModeCmd)
        numbers = [terminal.next_command_seq() for _ in range(LAST_COMMAND_SEQ + 2)]
        self.assertEqual(list(range(1, LAST_COMMAND_SEQ + 1)) + [1, 2], numbers)
        self.assertLess(max(numbers), 101, "101 to 200 are the controller's for its clients, 201 up the scripts'")


def dataclass_without_seq(command):
    payload = command.payload
    return (payload.requested_state, payload.requested_mode, payload.range_km, payload.tilt)


@needs("FMOFP_BC", "FMOFP_RADAR")
class DisplayAndScriptOnOneRadarTest(unittest.TestCase):
    def setUp(self):
        self.script = os.path.join(tempfile.mkdtemp(prefix="fmofp_two_senders_"), "commands.txt")
        mapping = m.RdrWxModeCmd(cmd_seq=SCRIPT_SEQ, requested_state=TerminalState.NORMAL,
                                 requested_mode=WeatherMode.MAPPING, range_km=200.0, tilt=0.0)
        status, words = mapping.encode()
        self.assertEqual(Status.OK, status)
        with open(self.script, "w", encoding="utf-8") as f:
            f.write(f"{SCRIPT_FRAME} {mapping.RT} {mapping.SUBADDRESS} " + " ".join(f"{w:04X}" for w in words) + "\n")
        self.monitor = Monitor(PORT_BASE)
        self.assertEqual(Status.OK, self.monitor.open(), "monitor port in use?")
        self.display = DisplayTerminal(DISPLAY_RT, PORT_BASE, m.DspRadarStatus, m.DspRadarModeCmd)
        self.assertEqual(Status.OK, self.display.start(), "display port in use?")
        self.radar = subprocess.Popen([os.environ["FMOFP_RADAR"], "--port-base", str(PORT_BASE), "--quiet"],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        time.sleep(0.3)

    def tearDown(self):
        self.radar.kill()
        self.radar.wait(timeout=10)
        self.radar.stdout.close()
        self.display.stop()
        self.monitor.close()

    def test_the_script_command_holds_after_the_displays(self):
        self.display.send(survey(self.display.next_command_seq()))  # the user's click, before the bus starts
        bc = subprocess.Popen(
            [os.environ["FMOFP_BC"], "--rt", str(RADAR_RT), "--rt", str(DISPLAY_RT), "--port-base", str(PORT_BASE),
             "--frames", str(FRAMES), "--free-run", "--timeout-ms", "40", "--script", self.script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        records = self.monitor.read_until(lambda: bc.poll() is not None)
        output = bc.stdout.read()
        bc.stdout.close()
        self.assertEqual(0, bc.wait(timeout=60), output)
        self.assertIn("script: 1 commands", output)

        frame = -1
        radar_status = []     # (frame, RDR_WX_STATUS) as the radar transmitted it
        display_numbers = []  # (frame, cmd_seq) of DSP_RDR_WX_CMD as the display transmitted it for the relay
        for record in records:
            cw = record.command
            if cw.is_mode_code and cw.count_or_mode == SYNC_MODE_CODE:
                frame += 1
                continue
            if not (cw.transmit and not cw.is_mode_code and record.answered):
                continue
            if cw.rt == RADAR_RT and cw.subaddress == m.RdrWxStatus.SUBADDRESS:
                status, message = m.RdrWxStatus.decode(record.received)
                self.assertEqual(Status.OK, status)
                radar_status.append((frame, message))
            elif cw.rt == DISPLAY_RT and cw.subaddress == m.DspRdrWxCmd.SUBADDRESS:
                status, message = m.DspRdrWxCmd.decode(record.received)
                self.assertEqual(Status.OK, status)
                display_numbers.append((frame, message.payload.cmd_seq))

        # The display's command is relayed for a second of bus and then withdrawn.
        held = [f for f, seq in display_numbers if seq == 1]
        gone = [f for f, seq in display_numbers if seq == 0 and f > (held[0] if held else 0)]
        self.assertGreaterEqual(len(held), 8, f"relays of the standing command: {display_numbers[:30]}")
        self.assertLess(max(held), SCRIPT_FRAME - 20, "withdrawn well before the script's command")
        self.assertLessEqual(max(held) - min(held), COMMAND_HOLD_FRAMES + 10)
        self.assertTrue(gone, "the display's command was never withdrawn")
        self.assertEqual(1, self.display.commands_withdrawn)

        # The radar took the display's command...
        before = [s for f, s in radar_status if 60 <= f < SCRIPT_FRAME]
        self.assertTrue(before, "no radar status before the script's command")
        for s in before:
            self.assertEqual((TerminalState.NORMAL, WeatherMode.SURVEILLANCE, 1), (s.state, s.mode, s.last_cmd_seq))
        # ...and then the script's, for good: before the display withdrew its command the radar was back in
        # SURVEILLANCE with last_cmd_seq 1 a tenth of a second later.
        after = [(f, s) for f, s in radar_status if f >= SCRIPT_FRAME + 20]
        self.assertGreaterEqual(len(after), 10, "too few radar statuses after the script's command")
        for f, s in after:
            self.assertEqual((TerminalState.NORMAL, WeatherMode.MAPPING, SCRIPT_SEQ), (s.state, s.mode, s.last_cmd_seq),
                             f"frame {f}")


if __name__ == "__main__":
    unittest.main()
