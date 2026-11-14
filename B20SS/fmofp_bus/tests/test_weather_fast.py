"""The weather picture's particles: fmofp_display.weather_fast against the frozen WeatherRadarDisplay.

The frozen display paints every particle of a type once per reading it draws, about twenty times a repaint, and
searches a list of every particle's id for each one: 7 to 30 s a repaint in the radar window (2026-11-14). The
fast drawing paints one pass into an image and lays it down as often as the display asks. These tests hold the
two against each other, offscreen: the same particles, called as the display calls them, must give the same
picture to within the rounding of eight-bit colour, leave the painter as the frozen method leaves it, and paint
each particle once a repaint.

Skipped where PyQt6, numpy or the FMOFP display code cannot be imported.
"""

import logging
import os
import random
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import numpy as np
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_QT = False

from fmofp_display import weather_fast

COLORS = ((0, 200, 0), (255, 255, 0), (255, 0, 255), (255, 60, 60), (0, 120, 255))


def pixels(image):
    """The image as an array of rows x columns x 4 colour levels."""
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    data = np.frombuffer(bits, dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    return data[:, :image.width(), :].astype(np.int16)


def surface(dpr):
    image = QImage(int(800 * dpr), int(600 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor(0, 0, 0))
    return image


def draw(method, display, dpr, offset, calls):
    """The method called as the display calls it: once per reading, with the dark box of the reading's label
    drawn over the particles after each call."""
    image = surface(dpr)
    painter = QPainter(image)
    painter.translate(*offset)
    for index, data_type in enumerate(calls):
        method(display, painter, data_type)
        painter.fillRect(QRectF(250 + 7 * index, 220 + 4 * index, 30, 10), QColor(0, 0, 0, 180))
    painter.end()
    return image


@unittest.skipUnless(HAVE_QT, "PyQt6 and numpy are needed")
class WeatherParticlesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fmofp_display import app as display_app
            display_app.bootstrap()
            from FMOFP.Interfaces.userInterface.displays.radar.weather_radar_display import WeatherRadarDisplay
        except Exception as error:  # pragma: no cover - depends on the machine
            raise unittest.SkipTest(f"the FMOFP weather display cannot be imported: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.was_installed = bool(weather_fast._frozen)
        weather_fast.uninstall()
        cls.display_class = WeatherRadarDisplay
        cls.frozen = staticmethod(WeatherRadarDisplay._draw_particles)
        logging.disable(logging.ERROR)  # the frozen display logs each batch of particles it generates

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        weather_fast.uninstall()
        if cls.was_installed:
            weather_fast.install()

    def setUp(self):
        weather_fast.uninstall()
        self.assertTrue(weather_fast.install())
        random.seed(7)
        self.display = self.display_class()
        # Four precipitation readings, five VIL readings and two storm cells, of five colours, overlapping.
        for n in range(4):
            self.display._particle_colors["precipitation"][f"p{n}"] = QColor(*COLORS[n % 5])
            self.display._generate_particles(300.0 + 14 * n, 250.0 + 9 * n, 0.4 + 0.15 * n, QColor(*COLORS[n % 5]),
                                             "precipitation", f"p{n}", 40.0)
        for n in range(5):
            self.display._particle_colors["vil"][f"v{n}"] = QColor(*COLORS[(n + 2) % 5])
            self.display._generate_particles(270.0 + 11 * n, 290.0 + 7 * n, 0.3 + 0.12 * n,
                                             QColor(*COLORS[(n + 2) % 5]), "vil", f"v{n}", 30.0)
        for n in range(2):
            self.display._generate_cell_particles(330.0 + 25 * n, 235.0 + 12 * n, 0.5 + 0.3 * n,
                                                  QColor(*COLORS[(n + 3) % 5]), f"c{n}", 45.0, 0.0)
        self.calls = ["cells"] * 2 + ["precipitation"] * 4 + ["vil"] * 5

    def tearDown(self):
        self.display.cleanup()  # its two timers
        # The spatial grid is one for the process: this display's particles leave it with the display.
        for data_type, readings in self.display._particles.items():
            for data_id, particle_list in readings.items():
                for particle in particle_list:
                    self.display._spatial_grid.remove(f"{data_type}_{data_id}_{id(particle)}")

    def layers(self):
        return weather_fast.state_of(self.display)["layers"]

    def test_the_fast_drawing_gives_the_frozen_picture(self):
        for dpr, offset in ((1.0, (0.0, 0.0)), (1.25, (37.0, 21.0)), (2.0, (0.0, 0.0))):
            with self.subTest(dpr=dpr, offset=offset):
                self.display.__dict__.pop(weather_fast.STATE, None)
                frozen = pixels(draw(self.frozen, self.display, dpr, offset, self.calls))
                fast = pixels(draw(weather_fast.draw_particles, self.display, dpr, offset, self.calls))
                lit = int((frozen[..., :3].sum(axis=2) > 30).sum())
                self.assertGreater(lit, 2000, "the particles make a picture at all")
                difference = np.abs(frozen - fast)
                # One pass laid down n times against n passes painted: the same compositing, rounded at
                # different places. A shifted or blurred image, or a pass too many, would be tens of levels
                # over thousands of pixels.
                self.assertLess(float(difference.mean()), 0.05)
                self.assertLessEqual(int(difference.max()), 40)
                self.assertLess(int((difference.max(axis=2) > 8).sum()), max(40, lit // 100))

    def test_the_painter_is_left_as_the_frozen_method_leaves_it(self):
        """What the display draws next inherits the pen, the hints and the brush."""
        states = []
        for method in (self.frozen, weather_fast.draw_particles):
            image = surface(1.0)
            painter = QPainter(image)
            painter.setPen(QColor(255, 255, 255))
            method(self.display, painter, "vil")
            gradient = painter.brush().gradient()
            where = (gradient.center().x(), gradient.center().y(), gradient.radius()) if hasattr(gradient, "center") \
                else None
            states.append((painter.pen().style(), painter.testRenderHint(QPainter.RenderHint.Antialiasing),
                           painter.brush().style(), gradient.type(), where,
                           [(position, color.rgba()) for position, color in gradient.stops()],
                           painter.worldTransform().dx(), painter.opacity()))
            painter.end()
        self.assertEqual(states[0], states[1])
        self.assertEqual(Qt.PenStyle.NoPen, states[1][0])
        # A type with no particle: neither method touches the painter.
        self.display._particles["vil"] = {}
        image = surface(1.0)
        painter = QPainter(image)
        painter.setPen(QColor(255, 255, 255))
        weather_fast.draw_particles(self.display, painter, "vil")
        self.assertEqual(Qt.PenStyle.SolidLine, painter.pen().style())
        painter.end()

    def test_each_particle_is_painted_once_a_repaint(self):
        """The frozen method painted every particle at every call. The pass is painted when a new repaint finds
        the particles changed, and only then."""
        def repaint():
            weather_fast.state_of(self.display)["serial"] += 1  # what draw_radar_elements does
            draw(weather_fast.draw_particles, self.display, 1.0, (0.0, 0.0), self.calls)
            return {kind: layer.paints for kind, layer in self.layers().items()}

        self.assertEqual({"cells": 1, "precipitation": 1, "vil": 1}, repaint(), "eleven calls, one pass a type")
        self.assertEqual({"cells": 1, "precipitation": 1, "vil": 1}, repaint(), "nothing moved: nothing painted")
        first = next(iter(self.display._particles["vil"].values()))[0]
        first["x"] += 3.0
        self.assertEqual({"cells": 1, "precipitation": 1, "vil": 2}, repaint(), "a particle moved")
        self.display._particle_colors["precipitation"]["p0"] = QColor(10, 20, 30)
        self.assertEqual({"cells": 1, "precipitation": 2, "vil": 2}, repaint(), "a reading changed colour")
        self.display._generate_cell_particles(400.0, 300.0, 0.6, QColor(255, 0, 0), "c9", 45.0, 0.0)
        self.assertEqual({"cells": 2, "precipitation": 2, "vil": 2}, repaint(), "a new storm cell")
        del self.display._particles["cells"]["c9"]
        self.assertEqual({"cells": 3, "precipitation": 2, "vil": 2}, repaint(), "and gone again")

    def test_install_replaces_the_two_methods_and_the_frozen_file_is_not_touched(self):
        cls = self.display_class
        self.assertIs(weather_fast.draw_particles, cls._draw_particles)
        self.assertIs(weather_fast.draw_radar_elements, cls.draw_radar_elements)
        self.assertTrue(weather_fast.install(), "a second install changes nothing")
        self.assertIs(self.frozen, weather_fast.frozen_draw_particles())
        # A repaint through the display's own entry point is counted.
        before = weather_fast.state_of(self.display)["serial"]
        image = surface(1.0)
        painter = QPainter(image)
        self.display.draw_radar_elements(painter, QRectF(0, 0, 800, 600), {})
        painter.end()
        self.assertEqual(before + 1, weather_fast.state_of(self.display)["serial"])
        weather_fast.uninstall()
        self.assertIs(self.frozen, cls._draw_particles)
        self.assertNotEqual(weather_fast.draw_radar_elements, cls.draw_radar_elements)
        with mock.patch.dict(os.environ, {"FMOFP_FROZEN_PARTICLES": "1"}):
            self.assertFalse(weather_fast.install(), "the frozen drawing was asked for")
            self.assertIs(self.frozen, cls._draw_particles)
        self.assertTrue(weather_fast.install())

    def test_a_failure_hands_the_call_back_to_the_frozen_method(self):
        weather_fast._reported.clear()
        with mock.patch.object(weather_fast, "paint_layer", side_effect=ValueError("no layer today")):
            with self.assertLogs(weather_fast.logger, level="WARNING") as logs:
                logging.disable(logging.NOTSET)
                try:
                    image = draw(weather_fast.draw_particles, self.display, 1.0, (0.0, 0.0), ["cells", "cells"])
                finally:
                    logging.disable(logging.ERROR)
        self.assertEqual(1, len(logs.records), "said once, not at every call")
        self.assertGreater(int((pixels(image)[..., :3].sum(axis=2) > 30).sum()), 500, "the frozen method drew")


if __name__ == "__main__":
    unittest.main()
