"""The bus controller's command port (ICD README section 7, v1.23).

A client (the scenario engine, the debug CLI, a test) sends a COMMAND frame to port_base + 34: the command word it
wants sent and the data words. The controller queues the receive transaction for its next frame and answers a
COMMAND_ACK frame with the outcome and its frame count. The first class needs no binary: the client refuses what
it can see is wrong and reports an absent controller. The second runs the real fmofp_bc with a Python terminal at
RT 24 (FMOFP_BC names the binary; CI sets it).

The third (v1.24) is what a user does: several client programs at once, beside a listener on the fixed monitor
port as the demo's dashboard is. Until v1.24 a second listener could not open the monitor port at all, and a
second client's first command carried the first client's number and was dropped by the terminal. It runs fmofp_bc
and the communications computer (FMOFP_COMMS), the smallest partition that numbers its commands.
"""

import os
import socket
import subprocess
import threading
import time
import unittest

from fmofp_bus.bus_view import BusView
from fmofp_bus.command_port import FIRST_CLIENT_NUMBER, LAST_CLIENT_NUMBER, CommandClient, sequence_place
from fmofp_bus.command_word import CommandWord, encode_command_word
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import CmdStatus, CommsCommand, TerminalState
from fmofp_bus.monitor import Monitor
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, LOOPBACK, RtProcess
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base
from fmofp_bus.transport import FrameType, decode_frame

PORT_BASE = free_port_base(57500)
CLIENTS_PORT_BASE = free_port_base(60500)
RT = 24  # a free address: RT 1 is the avionics terminal, RT 4 the ECS
FRAMES = 150


class StubTerminal(threading.Thread):
    """Answers the bus and refreshes TERM_STATUS with every sync word (test_bus_integration's)."""

    def __init__(self, process):
        super().__init__(daemon=True)
        self.process = process
        self.stop = threading.Event()
        self.syncs = 0

    def run(self):
        while not self.stop.is_set():
            self.process.poll(0.002)
            got, sync = self.process.terminal.take_sync()
            if got:
                self.syncs += 1
                status, words = m.TermStatus(state=TerminalState.NORMAL, healthy=True, last_sync=sync,
                                             icd_major=m.ICD_MAJOR, icd_minor=m.ICD_MINOR).encode()
                if status == Status.OK:
                    self.process.terminal.set_transmit(m.TermStatus.SUBADDRESS, words)


class CommandClientTest(unittest.TestCase):
    """The client on its own."""

    def test_a_closed_client_and_an_absent_controller(self):
        client = CommandClient(PORT_BASE + 200, timeout_s=0.2)
        self.assertEqual(Status.NOT_READY, client.send_words(RT, 20, [1]).status)
        self.assertEqual(Status.OK, client.open())
        try:
            ack = client.send_words(RT, 20, [1, 2])
            self.assertIn(ack.status, (Status.TIMEOUT, Status.IO_ERROR))  # Windows reports the closed port, Linux waits
            self.assertFalse(ack.queued)
            self.assertEqual(Status.INVALID_ARGUMENT, client.send_words(RT, 20, []).status)
            self.assertEqual(Status.INVALID_ARGUMENT, client.send_words(RT, 20, [0] * 33).status)
            self.assertEqual(Status.INVALID_ARGUMENT, client.send_words(40, 20, [1]).status)  # no such address
            ack = client.send(m.MsnCmd(cmd_seq=7))
            self.assertIn(ack.status, (Status.TIMEOUT, Status.IO_ERROR))
            self.assertEqual(7, ack.cmd_seq)
        finally:
            client.close()

    def test_the_client_finds_where_every_command_of_the_icd_carries_its_number(self):
        """The controller writes the number into the place the client names (v1.24), so the client must find
        cmd_seq in every command message there is: one byte of one word, wherever the ICD put it."""
        commands = [info.cls for info in m.MESSAGES if info.direction == "R" and hasattr(info.cls(), "cmd_seq")]
        self.assertGreaterEqual(len(commands), 30, "the ICD's commands")
        for cls in commands:
            place = sequence_place(cls)
            self.assertIsNotNone(place, cls.__name__)
            index, lowest = place
            status, words = cls(cmd_seq=0xA5).encode()
            self.assertIn(status, (Status.OK, Status.CLAMPED), cls.__name__)
            self.assertEqual(0xA5, (words[index] >> lowest) & 0xFF, cls.__name__)
            self.assertLessEqual(lowest, 8, cls.__name__)
        self.assertIs(sequence_place(m.MsnCmd), sequence_place(m.MsnCmd), "found once, then remembered")
        self.assertIsNone(sequence_place(m.PlantSensors), "a message without a cmd_seq has no place for one")

    def test_the_client_leaves_the_message_as_it_was(self):
        """Numbering is the controller's: the client writes nothing into the message, so the same object sent
        again is numbered afresh. A number the caller chose is sent, and reported, as it is."""
        client = CommandClient(PORT_BASE + 200)
        message = m.MsnCmd()
        self.assertEqual(Status.NOT_READY, client.send(message).status)  # not open
        self.assertEqual(0, message.cmd_seq)
        kept = m.MsnCmd(cmd_seq=250)
        ack = client.send(kept)
        self.assertEqual((250, 250), (kept.cmd_seq, ack.cmd_seq))


@unittest.skipUnless(os.environ.get("FMOFP_BC"), "set FMOFP_BC to the fmofp_bc binary to run")
class CommandPortTest(unittest.TestCase):
    def setUp(self):
        self.process = RtProcess()
        self.assertEqual(Status.OK, self.process.init(RT, PORT_BASE), "RT port in use?")
        self.stub = StubTerminal(self.process)
        self.stub.start()
        self.client = CommandClient(PORT_BASE, timeout_s=1.0)
        self.assertEqual(Status.OK, self.client.open())

    def tearDown(self):
        self.client.close()
        self.stub.stop.set()
        self.stub.join(timeout=2)
        self.process.shutdown()

    def start_bus(self, *extra, frames=FRAMES):
        return subprocess.Popen([os.environ["FMOFP_BC"], "--rt", str(RT), "--port-base", str(PORT_BASE), "--frames",
                                 str(frames), "--timeout-ms", "20", "--no-monitor", *extra],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())

    @staticmethod
    def finish(bc):
        output = bc.stdout.read()
        bc.stdout.close()
        return bc.wait(timeout=60), output

    def wait_for_syncs(self, count, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while self.stub.syncs < count and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(self.stub.syncs, count, "the bus did not start")

    def test_a_client_queues_commands_and_is_answered(self):
        bc = self.start_bus()
        try:
            self.wait_for_syncs(5)
            # Raw words to the stub's subaddress 20: queued, acknowledged with the controller's frame count.
            ack = self.client.send_words(RT, 20, [0xCAFE, 0x0002, 0xBEEF])
            self.assertEqual(Status.OK, ack.status, ack)
            self.assertTrue(ack.queued)
            self.assertGreaterEqual(ack.frame, 4)
            self.assertEqual(0, ack.cmd_seq)
            # An ICD message defined for every terminal, given its address: the controller numbers it (v1.24),
            # the first for a destination from where its frame count stands, and says which number it gave.
            ack2 = self.client.send(m.TermCmd(requested_state=TerminalState.NORMAL), rt=RT)
            self.assertTrue(ack2.queued, ack2)
            self.assertEqual(FIRST_CLIENT_NUMBER + ack2.frame % 100, ack2.cmd_seq)
            self.assertGreaterEqual(ack2.frame, ack.frame)
            time.sleep(0.1)  # the next frames' aperiodic slots (20 ms frames)
            status, words, fresh = self.process.terminal.get_received(20)
            self.assertEqual(Status.OK, status)
            self.assertTrue(fresh)
            self.assertEqual([0xCAFE, 0x0002, 0xBEEF], list(words))
            status, words, fresh = self.process.terminal.get_received(m.TermCmd.SUBADDRESS)
            self.assertEqual(Status.OK, status)
            self.assertTrue(fresh)
            status, command = m.TermCmd.decode(words)
            self.assertEqual(Status.OK, status)
            self.assertEqual((TerminalState.NORMAL, ack2.cmd_seq), (command.requested_state, command.cmd_seq))
            # A transmit is the controller's business, not a client's: refused, the command word echoed.
            status, transmit = encode_command_word(CommandWord(rt=RT, transmit=True, subaddress=20, count_or_mode=1))
            self.assertEqual(Status.OK, status)
            refused = self.client.send_command_word(transmit, [1])
            self.assertEqual(Status.INVALID_ARGUMENT, refused.status)
            self.assertEqual(transmit, refused.command_word)
            # Bytes that are no frame: counted malformed, answered with the decoder's complaint.
            junk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            junk.settimeout(1.0)
            try:
                junk.bind((LOOPBACK, 0))
                junk.sendto(b"\x01\x02\x03\x04", (LOOPBACK, PORT_BASE + COMMAND_PORT_OFFSET))
                data, _ = junk.recvfrom(256)
            finally:
                junk.close()
            status, frame = decode_frame(data)
            self.assertEqual(Status.OK, status)
            self.assertEqual(FrameType.COMMAND_ACK, frame.type)
            self.assertEqual(Status.BAD_LENGTH, Status(frame.words[1]))
        finally:
            code, output = self.finish(bc)
        self.assertEqual(0, code, output)
        self.assertIn(f"bc: command port on {PORT_BASE + COMMAND_PORT_OFFSET}", output)
        self.assertIn("bc: command port: received=4 queued=2 refused=1 malformed=1 numbered=1 monitor_requests=0",
                      output)

    def test_without_the_port_nobody_answers(self):
        self.client.timeout_s = 0.3
        bc = self.start_bus("--no-command-port", frames=100)
        try:
            self.wait_for_syncs(3)
            ack = self.client.send_words(RT, 20, [1])
            self.assertIn(ack.status, (Status.TIMEOUT, Status.IO_ERROR))
        finally:
            code, output = self.finish(bc)
        self.assertEqual(0, code, output)
        self.assertNotIn("command port", output)


@unittest.skipUnless(os.environ.get("FMOFP_BC") and os.environ.get("FMOFP_COMMS"),
                     "set FMOFP_BC and FMOFP_COMMS to the binaries to run")
class ClientsBesideEachOtherTest(unittest.TestCase):
    """The bus as a user has it: the communications computer under the controller in real time, a listener on
    the fixed monitor port (the demo's dashboard is one), and client programs coming and going."""

    FRAMES = 350  # seven seconds: the steps below take four on a desktop

    def setUp(self):
        self.comms = subprocess.Popen([os.environ["FMOFP_COMMS"], "--port-base", str(CLIENTS_PORT_BASE), "--quiet"],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())
        self.dashboard = Monitor(CLIENTS_PORT_BASE)
        self.assertEqual(Status.OK, self.dashboard.open(), "monitor port in use?")
        self.opened = []
        time.sleep(0.3)
        self.bc = subprocess.Popen([os.environ["FMOFP_BC"], "--rt", str(m.ComStatus.RT), "--port-base",
                                    str(CLIENTS_PORT_BASE), "--frames", str(self.FRAMES), "--timeout-ms", "20"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=binary_env())

    def tearDown(self):
        for thing in self.opened:
            thing.close()
        self.dashboard.close()
        for process in (self.bc, self.comms):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            process.stdout.close()

    def view(self):
        """A client program's picture of the bus, as the prompt and the scenario engine open it."""
        view = BusView(CLIENTS_PORT_BASE)
        self.assertEqual(Status.OK, view.open())
        view.start()
        self.opened.append(view)
        return view

    def client(self):
        client = CommandClient(CLIENTS_PORT_BASE, timeout_s=1.0)
        self.assertEqual(Status.OK, client.open())
        self.opened.append(client)
        return client

    def comms_status(self, view, wanted, timeout_s=2.0):
        """COM_STATUS once its comms_cmd_status is `wanted` (the status comes round five times a second)."""
        deadline = time.monotonic() + timeout_s
        status = None
        while time.monotonic() < deadline:
            status = view.snapshot()["latest"].get(m.ComStatus)
            if status is not None and status.comms_cmd_status == wanted:
                break
            time.sleep(0.02)
        return status

    def test_clients_listen_beside_the_dashboard_and_their_commands_are_all_acted_on(self):
        first_view = self.view()
        self.assertTrue(first_view.wait_for_frame(0, 5.0), "a client beside the dashboard saw no frame")
        self.assertEqual(Status.OK, first_view.monitor.granted)
        self.assertIsNotNone(self.dashboard.read(1.0), "the listener on the fixed monitor port still has its stream")

        # One client program's command: the radio volume, which the communications computer accepts.
        first = self.client()
        ack = first.send(m.ComCmd(command=CommsCommand.SET_RADIO_VOLUME, volume=50))
        self.assertTrue(ack.queued, ack)
        self.assertTrue(FIRST_CLIENT_NUMBER <= ack.cmd_seq <= LAST_CLIENT_NUMBER, ack)
        status = self.comms_status(first_view, CmdStatus.ACCEPTED)
        self.assertEqual(CmdStatus.ACCEPTED, status.comms_cmd_status)

        # A second program, started later, knows nothing of the first. Its view joins a bus that has run for a
        # second: it has the controller's frame count all the same, the number its acknowledgements carry.
        self.assertTrue(first_view.wait_for_frame(60, 5.0))
        second_view = self.view()
        self.assertTrue(second_view.wait_until_watched(3, 5.0), "a second client saw no frame")
        self.assertGreaterEqual(second_view.current_frame(), 60, "the controller's count, not the view's own")
        second = self.client()
        # Its first command to the same destination: a frequency of zero, which the computer rejects. Numbered by
        # the client it would be the first client's number over again, and the computer would not look at it.
        ack2 = second.send(m.ComCmd(command=CommsCommand.SET_RADIO_FREQUENCY, frequency=0.0))
        self.assertTrue(ack2.queued, ack2)
        self.assertEqual(ack.cmd_seq + 1 if ack.cmd_seq < LAST_CLIENT_NUMBER else FIRST_CLIENT_NUMBER, ack2.cmd_seq)
        self.assertLessEqual(abs(second_view.current_frame() - ack2.frame), 10, "one frame count for both")
        status = self.comms_status(second_view, CmdStatus.REJECTED_INVALID)
        self.assertEqual(CmdStatus.REJECTED_INVALID, status.comms_cmd_status,
                         "the second client's command was acted on")
        self.assertEqual(CmdStatus.REJECTED_INVALID, self.comms_status(first_view, CmdStatus.REJECTED_INVALID)
                         .comms_cmd_status, "and both clients see it")

        # A view that has watched a major frame has every terminal's status: what the prompt waits for.
        self.assertTrue(second_view.wait_until_watched(50, 5.0))
        self.assertIn(m.ComStatus.RT, second_view.snapshot()["term_status"])

        # A number of the caller's own is sent as it is; the same number again is the terminal's to ignore.
        own = second.send(m.ComCmd(command=CommsCommand.SET_RADIO_VOLUME, volume=10, cmd_seq=7))
        self.assertEqual((True, 7), (own.queued, own.cmd_seq))
        self.assertEqual(CmdStatus.ACCEPTED, self.comms_status(second_view, CmdStatus.ACCEPTED).comms_cmd_status)
        again = second.send(m.ComCmd(command=CommsCommand.SET_RADIO_FREQUENCY, frequency=0.0, cmd_seq=7))
        self.assertTrue(again.queued, again)
        time.sleep(0.5)
        self.assertEqual(CmdStatus.ACCEPTED, second_view.snapshot()["latest"][m.ComStatus].comms_cmd_status,
                         "a repeated number is no new command: the rule the controller's numbering works with")

        output = self.bc.stdout.read()
        self.assertEqual(0, self.bc.wait(timeout=30), output)
        self.assertIn("received=4 queued=4 refused=0 malformed=0 numbered=2", output)


if __name__ == "__main__":
    unittest.main()
