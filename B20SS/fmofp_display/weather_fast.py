"""The weather picture's particles, drawn once a repaint and laid down as often as the display asks.

WeatherRadarDisplay._draw_particles(painter, data_type) draws every particle of a type: the clouds of every
storm cell, or of every precipitation reading, or of every VIL reading. The frozen display calls it once per
storm cell, once per precipitation reading and once per VIL reading, some sixty times a repaint, so every
particle is painted about twenty times over; and each call first looks every particle up in a list of the six
thousand ids the spatial grid returns, a search of the whole list per particle. Measured in the radar window on
2026-11-14: 64 calls and 69,000 ellipses a repaint, 0.15 s of list searching per call, 7 to 30 s per repaint. The
window, which is the radars' control panel, answered a click only between repaints.

The picture depends on the repetition (a particle painted once is a faint speck: the clouds a user knows are the
twentyfold ones), so the repetition is kept and its cost removed. One pass of the frozen method is painted into
an image of its own, with the frozen method's own particles, order, culling, colours and gradients; each call
then lays that image down once. Laying one pass down n times is what painting the particles n times does, the
"over" operator being associative, so the picture is the frozen one to within the rounding of eight-bit colour
(fmofp_bus/tests/test_weather_fast.py holds the two against each other). The ids are looked up in a set.

The image is painted again when a new repaint finds the particles moved, recoloured, added or gone; a repaint in
which nothing changed only lays it down. Particles generated in the middle of a repaint (the display makes a
reading's particles just before it draws that reading) join the picture at the next repaint, a twentieth of a
second later.

Nothing in the frozen file is edited: install() replaces two methods of the class in this process, as
fmofp_display.app replaces the modules the displays read their data from. FMOFP_FROZEN_PARTICLES=1 in the
environment leaves the frozen drawing in place, for comparing the two.
"""

import logging
import os
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QGradient, QImage, QPainter, QRadialGradient, QTransform

logger = logging.getLogger(__name__)

STATE = "_fmofp_particle_layers"  # on each display instance: its repaint count and one Layer per particle type
STALE_S = 2.0                     # a layer nobody counted a repaint for (a caller other than
                                  # draw_radar_elements) is looked at again after this long
_BRUSHES = {}                     # (rgb, alpha) -> the particle brush of that colour and opacity
MARGIN = 2                        # device pixels kept around the particles for their antialiased edges
MAX_LAYER_PIXELS = 16_000_000     # a layer larger than any screen is a mistake: the frozen method takes over
BLIT_BIAS = 0.25                  # device pixels: keeps a rounding error from moving the image a whole pixel

_frozen = {}                      # the class's own methods, kept for uninstall() and for the fallback
_reported = set()                 # failures already logged, by kind


class Layer:
    """One pass of one particle type: the image, where it lies in device pixels, and what it was painted from."""

    __slots__ = ("serial", "painted_at", "fingerprint", "image", "origin", "brush", "paints")

    def __init__(self):
        self.serial = -1
        self.painted_at = 0.0
        self.fingerprint = None
        self.image = None      # None: no particle passed the culling
        self.origin = (0, 0)
        self.brush = None      # the last particle's brush, which the frozen method leaves on the painter
        self.paints = 0        # how many times the image was painted (the tests count)


def state_of(display):
    state = display.__dict__.get(STATE)
    if state is None:
        state = {"serial": 0, "layers": {}}
        display.__dict__[STATE] = state
    return state


def kept_particles(display, painter, data_type):
    """The particles one pass of the frozen method draws, in its order: every particle of the type, the larger
    first (a stable sort, as its own), less those the spatial grid does not report for the painter's surface
    and those the dirty region tracker does not mark. Pairs of (particle, data id)."""
    viewport_rect = display.viewport_rect(painter)
    entries = [(particle, data_id) for data_id, particle_list in display._particles[data_type].items()
               for particle in particle_list]
    entries.sort(key=lambda entry: entry[0]["size"], reverse=True)
    if display._use_spatial_partitioning:
        # One question to the grid per repaint serves the three types, and its answer is kept as a set: the
        # frozen method asked at every call and searched the list it got for every particle.
        state = state_of(display)
        asked = (state["serial"], viewport_rect.x(), viewport_rect.y(), viewport_rect.width(), viewport_rect.height())
        if state.get("visible_for") != asked:
            state["visible"] = set(display._spatial_grid.query_visible(viewport_rect))
            state["visible_for"] = asked
        visible = state["visible"]
        entries = [entry for entry in entries if f"{data_type}_{entry[1]}_{id(entry[0])}" in visible]
    if display._use_dirty_regions:
        tracker = display._dirty_region_tracker
        # The tracker answers yes to everything while its whole-surface flag is up (the display never lowers it).
        if not getattr(tracker, "full_redraw_needed", False):
            entries = [(p, data_id) for p, data_id in entries
                       if tracker.is_dirty(QRectF(p["x"] - p["size"] / 2, p["y"] - p["size"] / 2, p["size"],
                                                  p["size"]))]
    return entries


def fingerprint_of(display, painter, data_type, entries):
    """What a layer was painted from: the particles' number and the sums of their places, sizes and opacities
    (any that moves, grows, fades, comes or goes changes them), the colours of the type and the painter's mapping
    to device pixels."""
    sum_x = sum_y = sum_size = sum_opacity = 0.0
    for particle, _ in entries:
        sum_x += particle["x"]
        sum_y += particle["y"]
        sum_size += particle["size"]
        sum_opacity += particle["opacity"]
    colors = display._particle_colors.get(data_type, {})
    color_part = tuple(sorted((str(key), QColor(color).rgba()) for key, color in colors.items()))
    t = painter.deviceTransform()
    return (len(entries), sum_x, sum_y, sum_size, sum_opacity, color_part,
            t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def particle_brush(rgb, alpha):
    """The frozen method's brush for a particle of this colour and opacity: the colour at the centre, clear at the
    rim. Written in the ellipse's own coordinates (centre a half, radius a half of its box), so that one brush
    serves every particle of that colour and opacity wherever it lies and whatever its size; the frozen method
    built a gradient, two colours and a brush for each particle at each call."""
    color = QColor(rgb)
    color.setAlpha(alpha)
    edge_color = QColor(color)
    edge_color.setAlpha(0)
    gradient = QRadialGradient(0.5, 0.5, 0.5)
    gradient.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
    gradient.setColorAt(0, color)
    gradient.setColorAt(1, edge_color)
    return QBrush(gradient)


def paint_layer(display, painter, data_type, entries, layer, unknown_color):
    """One pass of the frozen method, painted into the layer's image instead of onto the surface."""
    layer.paints += 1
    layer.image = None
    layer.brush = None
    if not entries:
        return
    left = min(p["x"] - p["size"] / 2 for p, _ in entries)
    top = min(p["y"] - p["size"] / 2 for p, _ in entries)
    right = max(p["x"] + p["size"] / 2 for p, _ in entries)
    bottom = max(p["y"] + p["size"] / 2 for p, _ in entries)
    to_device = painter.deviceTransform()
    area = to_device.mapRect(QRectF(left, top, right - left, bottom - top)).toAlignedRect().adjusted(
        -MARGIN, -MARGIN, MARGIN, MARGIN)
    if area.width() * area.height() > MAX_LAYER_PIXELS:
        raise ValueError(f"a particle layer of {area.width()} x {area.height()} pixels")
    image = QImage(area.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    colors = display._particle_colors.get(data_type, {})
    rgb_of = {data_id: QColor(color).rgb() for data_id, color in colors.items()}
    unknown_rgb = QColor(unknown_color).rgb()
    layer_painter = QPainter(image)
    try:
        # The painter's own mapping, moved to the image's corner: the particles fall on the same device pixels.
        layer_painter.setTransform(to_device * QTransform.fromTranslate(-area.x(), -area.y()))
        layer_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layer_painter.setPen(Qt.PenStyle.NoPen)
        for particle, data_id in entries:
            size = particle["size"]
            key = (rgb_of.get(data_id, unknown_rgb), int(255 * particle["opacity"]))
            brush = _BRUSHES.get(key)
            if brush is None:
                brush = _BRUSHES[key] = particle_brush(*key)
            layer_painter.setBrush(brush)
            layer_painter.drawEllipse(QRectF(particle["x"] - size / 2, particle["y"] - size / 2, size, size))
    finally:
        layer_painter.end()
    layer.image = image
    layer.origin = (area.x(), area.y())
    # The frozen method leaves the last particle's brush on the painter, written in the surface's coordinates.
    last, last_id = entries[-1]
    color = QColor(colors.get(last_id, unknown_color))
    color.setAlpha(int(255 * last["opacity"]))
    gradient = QRadialGradient(last["x"], last["y"], last["size"] / 2)
    gradient.setColorAt(0, color)
    edge_color = QColor(color)
    edge_color.setAlpha(0)
    gradient.setColorAt(1, edge_color)
    layer.brush = QBrush(gradient)


def lay_down(painter, layer):
    """One call of the frozen method: the pass onto the surface, and the painter left as that method leaves it
    (antialiasing on, no pen, the last particle's brush)."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    if layer.image is None:
        return
    to_device = painter.deviceTransform()
    from_device, invertible = to_device.inverted()
    if not invertible:
        raise ValueError("the painter's transform cannot be inverted")
    painter.save()
    # A world transform under which the image's pixels are the surface's device pixels, one for one.
    painter.setWorldTransform(QTransform.fromTranslate(layer.origin[0], layer.origin[1]) * from_device
                              * painter.worldTransform())
    painter.drawImage(QPointF(BLIT_BIAS, BLIT_BIAS), layer.image)
    painter.restore()
    painter.setBrush(layer.brush)


def draw_particles(display, painter, data_type):
    """In place of WeatherRadarDisplay._draw_particles: the same picture, each particle painted once a repaint."""
    try:
        if not hasattr(display, "_particles") or not display._particles.get(data_type):
            return
        state = state_of(display)
        layer = state["layers"].get(data_type)
        if layer is None:
            layer = state["layers"][data_type] = Layer()
        now = time.monotonic()
        if layer.serial != state["serial"] or now - layer.painted_at > STALE_S:
            entries = kept_particles(display, painter, data_type)
            fingerprint = fingerprint_of(display, painter, data_type, entries)
            if fingerprint != layer.fingerprint:
                paint_layer(display, painter, data_type, entries, layer, _frozen["unknown_color"])
                layer.fingerprint = fingerprint
            layer.serial = state["serial"]
            layer.painted_at = now
        lay_down(painter, layer)
    except Exception as error:  # the frozen method swallows its own errors too; ours hand the call back to it
        kind = type(error).__name__
        if kind not in _reported:
            _reported.add(kind)
            logger.warning("fast weather particles gave up (%s: %s): the frozen drawing takes over", kind, error)
        _frozen["particles"](display, painter, data_type)


def draw_radar_elements(display, *args, **kwargs):
    """In place of WeatherRadarDisplay.draw_radar_elements: counts the repaint, then the frozen method."""
    state_of(display)["serial"] += 1
    return _frozen["elements"](display, *args, **kwargs)


def install():
    """Replaces the two methods on the frozen class for this process: every weather display in it, the radar
    window's and the one the MFD builds for its radar page, draws its particles the fast way. Does nothing the
    second time, or when FMOFP_FROZEN_PARTICLES=1 asks for the frozen drawing. Returns whether it is installed."""
    if _frozen:
        return True
    if os.environ.get("FMOFP_FROZEN_PARTICLES") == "1":
        return False
    from FMOFP.Interfaces.userInterface.displays.radar import weather_radar_display as frozen_module
    cls = frozen_module.WeatherRadarDisplay
    _frozen["class"] = cls
    _frozen["particles"] = cls._draw_particles
    _frozen["elements"] = cls.draw_radar_elements
    _frozen["unknown_color"] = frozen_module.UNKNOWN_SEVERITY_COLOR
    cls._draw_particles = draw_particles
    cls.draw_radar_elements = draw_radar_elements
    return True


def uninstall():
    """Puts the frozen methods back (the tests compare the two)."""
    if not _frozen:
        return
    cls = _frozen["class"]
    cls._draw_particles = _frozen["particles"]
    cls.draw_radar_elements = _frozen["elements"]
    _frozen.clear()


def frozen_draw_particles():
    """The frozen class's own _draw_particles, whether or not install() has replaced it."""
    if _frozen:
        return _frozen["particles"]
    from FMOFP.Interfaces.userInterface.displays.radar.weather_radar_display import WeatherRadarDisplay
    return WeatherRadarDisplay._draw_particles
