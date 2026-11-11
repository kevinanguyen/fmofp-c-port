"""The tests' own support: where an e2e test's bus goes when its usual UDP ports cannot be bound."""

import socket
import unittest

from fmofp_bus.tests import _support
from fmofp_bus.tests._support import BUS_PORTS, free_port_base


class FreePortBaseTest(unittest.TestCase):
    def setUp(self):
        # A base nobody's test owns, found free: the test then takes ports inside it away.
        self.base = next(b for b in range(40500, 48000, 500) if _support._bus_ports_free(b)
                         and _support._bus_ports_free(b - 150))
        self.held = []

    def tearDown(self):
        for sock in self.held:
            sock.close()

    def hold(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", port))
        self.held.append(sock)

    def test_a_free_base_is_kept(self):
        self.assertEqual(self.base, free_port_base(self.base))

    def test_a_taken_port_anywhere_in_the_bus_moves_it_below(self):
        for port in (self.base + 1, self.base + 27, self.base + BUS_PORTS):
            with self.subTest(port=port):
                self.hold(port)
                self.assertEqual(self.base - 150, free_port_base(self.base))
                self.held.pop().close()
        self.hold(self.base + BUS_PORTS + 1)
        self.assertEqual(self.base, free_port_base(self.base), "the port after the bus's last is not the bus's")

    def test_the_next_fallback_when_the_first_is_taken_too(self):
        self.hold(self.base + 32)
        self.hold(self.base - 150 + 33)
        self.assertEqual(self.base - 100, free_port_base(self.base))

    def test_with_nothing_free_the_preferred_base_comes_back(self):
        for offset in _support._FALLBACK_OFFSETS:
            self.hold(self.base + offset + 5)
        self.assertEqual(self.base, free_port_base(self.base), "the test then fails with its own 'port in use?'")

    def test_the_fallbacks_stay_clear_of_the_other_tests(self):
        """Bases are multiples of 500 and a few tests use base+100 or base+200 as well: a bus moved below its
        base must not reach the base before's +200 bus, nor run into its own base."""
        for offset in _support._FALLBACK_OFFSETS[1:]:
            self.assertGreater(500 + offset, 200 + BUS_PORTS, offset)
            self.assertLess(offset + BUS_PORTS, 1, offset)
        spans = sorted((offset + 1, offset + BUS_PORTS) for offset in _support._FALLBACK_OFFSETS)
        for (_, last), (first, _) in zip(spans, spans[1:]):
            self.assertLess(last, first, "no two candidate buses share a port")


if __name__ == "__main__":
    unittest.main()
