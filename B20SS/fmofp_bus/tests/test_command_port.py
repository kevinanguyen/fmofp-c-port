"""The bus controller's command port (ICD README section 7, v1.23).

A client (the scenario engine, the debug CLI, a test) sends a COMMAND frame to port_base + 34: the command word it
wants sent and the data words. The controller queues the receive transaction for its next frame and answers a
COMMAND_ACK frame with the outcome and its frame count. The first class needs no binary: the client refuses what
it can see is wrong and reports an absent controller. The second runs the real fmofp_bc with a Python terminal at
RT 24 (FMOFP_BC names the binary; CI sets it).
"""

import os
import socket
import subprocess
import threading
import time
import unittest

from fmofp_bus.command_port import FIRST_CMD_SEQ, CommandClient
from fmofp_bus.command_word import CommandWord, encode_command_word
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import TerminalState
from fmofp_bus.rt_process import COMMAND_PORT_OFFSET, LOOPBACK, RtProcess
from fmofp_bus.status import Status
from fmofp_bus.tests._support import binary_env, free_port_base
from fmofp_bus.transport import FrameType, decode_frame

PORT_BASE = free_port_base(57500)
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

    def test_sequence_numbers_start_at_201_per_destination_and_wrap_past_zero(self):
        client = CommandClient(PORT_BASE + 200)
        self.assertEqual(201, client.next_cmd_seq(6, 11))
        self.assertEqual(202, client.next_cmd_seq(6, 11))
        self.assertEqual(201, client.next_cmd_seq(22, 12))
        seq = 0
        for _ in range(53):
            seq = client.next_cmd_seq(6, 11)
        self.assertEqual(255, seq)
        self.assertEqual(1, client.next_cmd_seq(6, 11))  # 0 is "no command"
        message = m.MsnCmd()
        self.assertEqual(Status.NOT_READY, client.send(message).status)  # not open, but numbered first
        self.assertEqual(2, message.cmd_seq)
        kept = m.MsnCmd(cmd_seq=250)
        client.send(kept)
        self.assertEqual(250, kept.cmd_seq)
        self.assertEqual(251, client.next_cmd_seq(6, 11))  # the numbering follows the caller's own


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
            # An ICD message defined for every terminal, given its address: cmd_seq numbered from 201 by the client.
            ack2 = self.client.send(m.TermCmd(requested_state=TerminalState.NORMAL), rt=RT)
            self.assertTrue(ack2.queued, ack2)
            self.assertEqual(FIRST_CMD_SEQ, ack2.cmd_seq)
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
            self.assertEqual((TerminalState.NORMAL, FIRST_CMD_SEQ), (command.requested_state, command.cmd_seq))
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
        self.assertIn("bc: command port: received=4 queued=2 refused=1 malformed=1", output)

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


if __name__ == "__main__":
    unittest.main()
