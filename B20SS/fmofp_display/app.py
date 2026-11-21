"""The display windows and the entry point: py -m fmofp_display radar|pfd|mfd|eicas|tsd|sms [--port-base N].

The windows own a DisplayTerminal (the bus, in a thread) and a feed, and paint
with the Python display classes from FMOFP/Interfaces/userInterface/displays,
unchanged. A timer applies what the feed makes of the latest bus data; the
display classes draw it exactly as they drew the bridge's data before.
"""

import argparse
import functools
import importlib
import importlib.machinery
import importlib.util
import logging
import os
import sys
import time
import types
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from fmofp_bus.icd import blocks as b
from fmofp_bus.icd import messages as m
from fmofp_bus.icd.enums import (AewcMode, SarMode, TargetingMode, TerminalState, TfrMode, TrackFilter,
                                 WeatherMode)
from fmofp_bus.status import Status
from fmofp_display import weather_fast
from fmofp_display.flight_feed import FlightDataFeed
from fmofp_display.radar_feed import RadarFeed
from fmofp_display.systems_feed import SystemsFeed, TerrainClearance, WeatherSeverity
from fmofp_display.terminal_process import TerminalProcess

B20SS = Path(__file__).resolve().parent.parent
RADAR_RT = m.DspRadarStatus.RT
PFD_RT = m.DspPfdStatus.RT
MFD_RT = m.DspMfdStatus.RT
EICAS_RT = m.DspEicasStatus.RT
TSD_RT = m.DspTsdStatus.RT
SMS_RT = m.DspSmsStatus.RT
TICK_MS = 50
DEFAULT_RANGE_KM = 200.0


def bootstrap():
    """The FMOFP display code expects B20SS as the working directory (its config paths are relative) and on
    sys.path, and a folder for its logger to write into (`ensure_fmofp_logs_dir`)."""
    os.chdir(B20SS)
    if str(B20SS) not in sys.path:
        sys.path.insert(0, str(B20SS))
    ensure_fmofp_logs_dir()


def ensure_fmofp_logs_dir():
    """Makes the folder FMOFP's logger writes into, before the frozen logger looks for it; returns its path.

    The frozen `SysLogger.ensure_logs_directory` asks whether the folder is there and then makes it. Git ignores
    the folder, so a fresh clone has none: six display programs started together all saw "not there", one made
    it, and the others died with FileExistsError before the bus started (`py -m fmofp_demo` failed on its first
    start in four fresh checkouts of four, 2026-11-17). Made here first, with `exist_ok`, the frozen test finds
    it. The path is the frozen code's own (`resolve_data_dir`, which honours FMOFP_DATA_DIR); that module imports
    nothing of FMOFP, so asking it does not start the logger."""
    from FMOFP.Utils.common.fetching import resolve_data_dir
    logs_dir = resolve_data_dir("logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def quiet_fmofp_logging():
    """Drops INFO and DEBUG records in this process, whatever level the FMOFP logger sets itself.

    The frozen display code logs every item it draws at INFO (the MFD's radar data coordinator wrote 520 KB in
    a thirty-second demo, 2 MB in three minutes) and FMOFP's SysLogger puts the root logger at DEBUG when it is
    first imported, so a level set here beforehand would be undone. logging.disable is the process-wide
    threshold above every logger's own. Warnings and errors still reach the log. `--verbose` leaves it out.
    """
    logging.disable(logging.INFO)


THEMES = ("classic", "modern", "night")


def apply_theme(name):
    """Sets the frozen theme manager's theme (`visual/theme_manager.py`: CLASSIC, MODERN, NIGHT) for this process
    before any display is built: the standard displays read their colours, fonts and gradients from it, and its
    `display_types` choose the PFD's and the MFD's class (MODERN: the holographic ones, as upstream's factories
    meant; unit 34). Returns the theme's name."""
    bootstrap()
    from FMOFP.Interfaces.userInterface.displays.visual.theme_manager import DisplayTheme, get_theme_manager
    theme = DisplayTheme[name.upper()]
    if not get_theme_manager().set_theme(theme):
        raise ValueError(f"theme {name} not loaded by the theme manager")
    return theme.value


def holographic(category):
    """Whether the current theme builds the holographic class for this display ("pfd" or "mfd")."""
    bootstrap()
    from FMOFP.Interfaces.userInterface.displays.visual.theme_manager import get_theme_manager
    return get_theme_manager().get_display_type(category, "standard") == "holographic"


def radar_terminal(port_base):
    return TerminalProcess(RADAR_RT, port_base, m.DspRadarStatus, m.DspRadarModeCmd,
                           receives=(m.BcastRdrWxStatus, m.BcastRdrWxScan, m.BcastRdrTfrStatus, m.BcastRdrTfrGuidance,
                                     m.BcastRdrTgtStatus, m.BcastRdrAewcStatus, m.BcastRdrSarStatus),
                           blocks=(b.BcastRdrWxProducts, b.BcastRdrTfrElevation))


def pfd_terminal(port_base):
    return TerminalProcess(PFD_RT, port_base, m.DspPfdStatus, m.DspPfdModeCmd,
                           receives=(m.BcastFmsFlightData, m.BcastFmsStatus, m.BcastFmsAttitudeStatus,
                                     m.BcastEngFuelStatus),
                           blocks=(b.BcastDefRwrContacts,))  # the fuel and the contacts: the holographic PFD (v1.27)


def weather_command(terminal, state, mode, range_km=DEFAULT_RANGE_KM):
    cmd = m.RdrWxModeCmd(cmd_seq=terminal.next_command_seq(), requested_state=state, requested_mode=mode,
                         range_km=range_km, tilt=0.0)
    return m.DspRdrWxCmd(payload=cmd)


def tfr_command(terminal, state, mode, set_clearance_ft):
    cmd = m.RdrTfrModeCmd(cmd_seq=terminal.next_command_seq(), requested_state=state, requested_mode=mode,
                          set_clearance=float(set_clearance_ft))
    return m.DspRdrTfrCmd(payload=cmd)


def targeting_command(terminal, state, mode, lock_track_id=0, track_filter=TrackFilter.ALL):
    cmd = m.RdrTgtModeCmd(cmd_seq=terminal.next_command_seq(), requested_state=state, requested_mode=mode,
                          track_filter=track_filter, lock_track_id=int(lock_track_id))
    return m.DspRdrTgtCmd(payload=cmd)


def aewc_command(terminal, state, mode, azimuth_start=0.0, azimuth_end=90.0, elevation=0.0):
    cmd = m.RdrAewcModeCmd(cmd_seq=terminal.next_command_seq(), requested_state=state, requested_mode=mode,
                           azimuth_start=float(azimuth_start), azimuth_end=float(azimuth_end),
                           elevation=float(elevation))
    return m.DspRdrAewcCmd(payload=cmd)


def sar_command(terminal, state, mode, resolution_m=1.0):
    cmd = m.RdrSarModeCmd(cmd_seq=terminal.next_command_seq(), requested_state=state, requested_mode=mode,
                          resolution=float(resolution_m))
    return m.DspRdrSarCmd(payload=cmd)


class RadarPicture(QWidget):
    """Both radar pictures side by side: the weather display on the left, the terrain display on the right."""

    def __init__(self, feed, parent=None):
        super().__init__(parent)
        bootstrap()
        weather_fast.install()  # the weather display's particles painted once a repaint, not once per reading
        from FMOFP.Interfaces.userInterface.displays.radar.tfr_radar_display import TFRRadarDisplay
        from FMOFP.Interfaces.userInterface.displays.radar.weather_radar_display import WeatherRadarDisplay
        from FMOFP.Systems.radarManagement.radar_enums import tfr_radarMode, weather_radarMode
        self.feed = feed
        self.weather = WeatherRadarDisplay()
        self.terrain = TFRRadarDisplay()
        self._weather_modes = weather_radarMode
        self._terrain_modes = tfr_radarMode
        self._weather_mode_name = None
        self.paint_errors = 0
        self.setMinimumSize(1200, 600)

    def apply(self):
        """Puts the weather display into the mode and range the radar reports, then repaints."""
        name = self.feed.weather_draw_mode
        if name != self._weather_mode_name:
            self.weather._current_mode = self._weather_modes[name]
            self.weather._settings_manager.apply_mode_settings(name)
            self.weather._visual_elements = self.weather._settings_manager.get_settings()
            self._weather_mode_name = name
        self.weather.range_scale = max(10.0, self.feed.weather_range_nm)
        self.update()

    def terrain_display_data(self):
        """The terrain display's dictionary: the feed's data with the display's enum and no None values."""
        data = self.feed.tfr_data()
        data["mode"] = self._terrain_modes[data.pop("mode_name")]
        for key in ("current_altitude", "clearance_altitude"):
            if data.get(key) is None:
                data.pop(key, None)
        if data.get("terrain_clearance") is None:
            data["terrain_clearance"] = 0.0  # the display compares it; None would stop the whole picture
        return data

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            half = self.width() / 2.0
            left = QRectF(0.0, 0.0, half, float(self.height()))
            right = QRectF(half, 0.0, half, float(self.height()))
            painter.save()
            painter.setClipRect(left)
            self.weather.draw_radar_elements(painter, left, {})
            painter.restore()
            painter.save()
            painter.setClipRect(right)
            self.terrain.draw_display(painter, right, self.terrain_display_data())
            painter.restore()
        except Exception:  # noqa: BLE001 - a display class raised; the window must stay up
            self.paint_errors += 1
        finally:
            if painter.isActive():
                painter.end()


class RadarWindow(QWidget):
    """The radar display, RT 15: the pictures, the bus status, and the radars' control panel."""

    def __init__(self, terminal, feed=None):
        super().__init__()
        bootstrap()
        from FMOFP.Interfaces.userInterface.displays.radar.radar_display_data_coordinator import (
            get_radar_display_data_coordinator)
        self.terminal = terminal
        self.feed = feed if feed is not None else RadarFeed(terminal, get_radar_display_data_coordinator())
        self.setWindowTitle(f"FMOFP radar display - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.picture = RadarPicture(self.feed)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.picture, 1)
        layout.addLayout(self._weather_controls())
        layout.addLayout(self._terrain_controls())
        layout.addLayout(self._targeting_controls())
        layout.addLayout(self._aewc_controls())
        layout.addLayout(self._sar_controls())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

    def _weather_controls(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Weather radar:"))
        standby = QPushButton("STANDBY")
        standby.clicked.connect(lambda: self.terminal.send(weather_command(self.terminal, TerminalState.STANDBY,
                                                                           WeatherMode.NONE)))
        row.addWidget(standby)
        for mode in (WeatherMode.SURVEILLANCE, WeatherMode.MAPPING, WeatherMode.PRECIPITATION, WeatherMode.WINDSHEAR,
                     WeatherMode.TURBULENCE):
            button = QPushButton(mode.name)
            button.clicked.connect(lambda _=False, mode=mode: self.terminal.send(
                weather_command(self.terminal, TerminalState.NORMAL, mode)))
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _terrain_controls(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Terrain-following radar:"))
        self.clearance = QSpinBox()
        self.clearance.setRange(30, 5000)
        self.clearance.setValue(1000)
        self.clearance.setSuffix(" ft")
        standby = QPushButton("STANDBY")
        standby.clicked.connect(lambda: self.terminal.send(tfr_command(self.terminal, TerminalState.STANDBY, TfrMode.NONE,
                                                                       self.clearance.value())))
        row.addWidget(standby)
        for mode in (TfrMode.TFR_SEARCH, TfrMode.TFR_TRACK, TfrMode.TERRAIN_FOLLOWING, TfrMode.GROUND_MAPPING):
            button = QPushButton(mode.name)
            button.clicked.connect(lambda _=False, mode=mode: self.terminal.send(
                tfr_command(self.terminal, TerminalState.NORMAL, mode, self.clearance.value())))
            row.addWidget(button)
        row.addWidget(QLabel("set clearance"))
        row.addWidget(self.clearance)
        row.addStretch(1)
        return row

    def _targeting_controls(self):
        """The targeting radar's buttons; its picture is the MFD's radar page, as it was in the Python."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Targeting radar:"))
        self.lock_track = QSpinBox()
        self.lock_track.setRange(0, 65535)
        self.lock_track.setValue(1)
        self.lock_track.setSpecialValueText("none")
        standby = QPushButton("STANDBY")
        standby.clicked.connect(lambda: self.terminal.send(targeting_command(self.terminal, TerminalState.STANDBY,
                                                                             TargetingMode.NONE)))
        row.addWidget(standby)
        search = QPushButton("TARGET_SEARCH")
        search.clicked.connect(lambda: self.terminal.send(targeting_command(self.terminal, TerminalState.NORMAL,
                                                                            TargetingMode.TARGET_SEARCH)))
        row.addWidget(search)
        follow = QPushButton("TARGET_TRACK")
        follow.clicked.connect(lambda: self.terminal.send(targeting_command(self.terminal, TerminalState.NORMAL,
                                                                            TargetingMode.TARGET_TRACK,
                                                                            self.lock_track.value())))
        row.addWidget(follow)
        row.addWidget(QLabel("lock track"))
        row.addWidget(self.lock_track)
        row.addWidget(QLabel("(picture: the MFD's radar page)"))
        row.addStretch(1)
        return row

    def _aewc_controls(self):
        """The AEWC radar's buttons; its picture is the MFD's radar page too."""
        row = QHBoxLayout()
        row.addWidget(QLabel("AEWC radar:"))
        standby = QPushButton("STANDBY")
        standby.clicked.connect(lambda: self.terminal.send(aewc_command(self.terminal, TerminalState.STANDBY,
                                                                        AewcMode.NONE)))
        row.addWidget(standby)
        for mode in (AewcMode.AEWC_SEARCH, AewcMode.AEWC_SURVEILLANCE, AewcMode.AEWC_TRACK):
            button = QPushButton(mode.name)
            button.clicked.connect(lambda _=False, mode=mode: self.terminal.send(
                aewc_command(self.terminal, TerminalState.NORMAL, mode)))
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _sar_controls(self):
        """The synthetic aperture radar's buttons and its resolution; its picture is the MFD's radar page."""
        from PyQt6.QtWidgets import QDoubleSpinBox
        row = QHBoxLayout()
        row.addWidget(QLabel("SAR:"))
        self.sar_resolution = QDoubleSpinBox()
        self.sar_resolution.setRange(0.1, 10.0)
        self.sar_resolution.setSingleStep(0.1)
        self.sar_resolution.setDecimals(1)
        self.sar_resolution.setValue(1.0)
        self.sar_resolution.setSuffix(" m")
        standby = QPushButton("STANDBY")
        standby.clicked.connect(lambda: self.terminal.send(sar_command(self.terminal, TerminalState.STANDBY,
                                                                       SarMode.NONE, self.sar_resolution.value())))
        row.addWidget(standby)
        for mode in (SarMode.STRIPMAP, SarMode.SPOTLIGHT, SarMode.SCANSAR):
            button = QPushButton(mode.name)
            button.clicked.connect(lambda _=False, mode=mode: self.terminal.send(
                sar_command(self.terminal, TerminalState.NORMAL, mode, self.sar_resolution.value())))
            row.addWidget(button)
        row.addWidget(QLabel("resolution"))
        row.addWidget(self.sar_resolution)
        row.addStretch(1)
        return row

    def tick(self):
        self.feed.update()
        self.picture.apply()
        self.terminal.take_mode_request()  # the radar picture has no lighting modes; the status reports it
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{self.feed.weather_status_text()}  |  {self.feed.tfr_status_text()}  |  "
                            f"{self.feed.targeting_status_text()}  |  {self.feed.aewc_status_text()}  |  "
                            f"{self.feed.sar_status_text()}")


def make_pfd(feed):
    """A PrimaryFlightDisplay whose FMS and FMS control are the bus feed."""
    bootstrap()
    import FMOFP.Interfaces.userInterface.displays.pfd as pfd_module
    pfd_module.get_flightManagementSystem = lambda: feed
    pfd_module.get_fms_control = lambda: feed
    pfd = pfd_module.PrimaryFlightDisplay()
    pfd.start()
    return pfd


def make_holographic_pfd(feed, systems_feed):
    """The holographic PFD (the MODERN theme's) fed from the bus (unit 34, fmofp_display.holographic)."""
    bootstrap()
    from fmofp_display.holographic import bus_holographic_pfd_class
    pfd = bus_holographic_pfd_class()(feed, systems_feed)
    pfd.start()
    return pfd


class PfdWindow(QWidget):
    """The primary flight display, RT 11: the standard PFD, or the holographic one when the theme asks for it."""

    def __init__(self, terminal, feed=None, holographic_pfd=None):
        super().__init__()
        self.terminal = terminal
        self.feed = feed if feed is not None else FlightDataFeed(terminal)
        self.holographic = holographic("pfd") if holographic_pfd is None else holographic_pfd
        self.setWindowTitle(f"FMOFP primary flight display - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        if self.holographic:
            self.systems = SystemsFeed(terminal)
            self.pfd = make_holographic_pfd(self.feed, self.systems)
        else:
            self.pfd = make_pfd(self.feed)
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode as PfdDisplayMode
        self._display_modes = PfdDisplayMode
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.pfd, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)

    def tick(self):
        if self.holographic:
            self.pfd.apply_bus()
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.pfd.set_mode(self._display_modes[requested.name])
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{self.feed.status_text()}")

    def closeEvent(self, event):
        self.pfd.cleanup()
        super().closeEvent(event)


# ---- the MFD, RT 13 --------------------------------------------------------------------

def mfd_terminal(port_base):
    return TerminalProcess(MFD_RT, port_base, m.DspMfdStatus, m.DspMfdModeCmd,
                           receives=(m.BcastRdrWxStatus, m.BcastRdrWxScan, m.BcastRdrTfrStatus, m.BcastRdrTfrGuidance,
                                     m.BcastFcsGcasAlerts, m.BcastFcsPerfStatus, m.BcastFmsFlightData,
                                     m.BcastEngEngineStatus, m.BcastEngFuelStatus, m.BcastRdrTgtStatus,
                                     m.BcastRdrAewcStatus, m.BcastRdrSarStatus, m.BcastMsnStatus,
                                     m.MfdComLinkStatus, m.MfdSmsStores),
                           blocks=(b.BcastRdrWxProducts, b.BcastRdrTfrElevation, b.MfdRdrTgtTracks,
                                   b.MfdRdrAewcTracks, b.MfdRdrSarImage, b.BcastMsnPlan))


# The getters mfd.py imports inside its page functions and eicas.py inside its poll, and the feed attribute each
# answers with (BuiltInTestController is a class the EICAS constructs; the stand-in returns the feed's object).
SYSTEM_GETTERS = {
    "FMOFP.Systems.engineManagement.ecu.engineControlUnit": ("get_engine_control_unit", "engine"),
    "FMOFP.Systems.flightControlSys.groundCollisionAvoidanceSys.groundCollisionAvoidanceSys": ("get_gcas", "gcas"),
    "FMOFP.Systems.flightControlSys.performaneMonitoring.performaneMonitoring": ("get_performance_monitor",
                                                                                 "performance"),
    "FMOFP.Systems.comms.messaging_service": ("get_comms_service", "comms"),
    "FMOFP.Systems.missionPlanning.missionService": ("get_mission_service", "mission"),
    "FMOFP.Systems.radarManagement.radarControl": ("get_radar_management_system", "radar_management"),
    "FMOFP.Systems.flightManagementSys.flightManagementSystem": ("get_flightManagementSystem", "fms"),
    "FMOFP.Systems.flightManagementSys.fmsControl": ("get_fms_control", "fms_control"),
    "FMOFP.Systems.builtInTestSystems.bitControl": ("BuiltInTestController", "bit"),
    "FMOFP.Systems.defensiveSys.defensiveService": ("get_defensive_service", "defensive"),
    "FMOFP.Systems.sensorManagement.sensorService": ("get_sensor_service", "sensors"),
    "FMOFP.Systems.radarManagement.radar_data_fusion": ("get_radar_data_fusion", "fusion"),
}
TFR_RADAR_MODULE = "FMOFP.Systems.radarManagement.terrainFollowing.tfr_radar"
WEATHER_RADAR_MODULE = "FMOFP.Systems.radarManagement.weather.weather_radar"
_installed = []  # what install_system_sources() changed, for uninstall_system_sources()


def _load_real_attribute(module, name):
    """A stand-in module's answer for anything but the getter: the real module's attribute, loaded on first need
    (from its file, since the stand-in holds its place in sys.modules), so other code in the same process still
    gets the real classes."""
    if name.startswith("__"):
        raise AttributeError(name)
    real = module.__dict__.get("_fmofp_real_module")
    if real is None:
        parent = importlib.import_module(module.__name__.rpartition(".")[0])
        spec = importlib.machinery.PathFinder.find_spec(module.__name__, parent.__path__)
        if spec is None:
            raise AttributeError(name)
        real = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real)
        module.__dict__["_fmofp_real_module"] = real
    return getattr(real, name)


def _install_attribute(module_name, attribute, value):
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module._fmofp_stand_in = True
        module.__getattr__ = functools.partial(_load_real_attribute, module)  # PEP 562
        sys.modules[module_name] = module
    _installed.append((module_name, module, attribute, module.__dict__.get(attribute)))
    setattr(module, attribute, value)


def install_system_sources(feed):
    """Points the getters mfd.py and eicas.py import at the feed's stand-ins, without importing the aircraft's
    systems.

    The pages (and the EICAS's poll) do `from FMOFP.Systems... import get_x`
    when they run, which reads the attribute off whatever module is registered
    under that name. A stand-in module is registered for each, so the display
    process never loads the engine, GCAS, performance, comms, mission, FMS,
    built-in test, defensive, sensor, fusion or radar management code, which
    belongs to the flight computers; the terrain picture's lookup finds
    TerrainClearance where it expects the tfr_radar class, and the EICAS's
    weather lookup finds WeatherSeverity where it expects the weather_radar class.
    """
    for module_name, (getter, attribute) in SYSTEM_GETTERS.items():
        _install_attribute(module_name, getter, lambda feed=feed, attribute=attribute: getattr(feed, attribute))
    _install_attribute(TFR_RADAR_MODULE, "tfr_radar", TerrainClearance)
    _install_attribute(WEATHER_RADAR_MODULE, "weather_radar", WeatherSeverity)


def uninstall_system_sources():
    """Undoes install_system_sources() (the tests share one process with code that wants the real modules)."""
    while _installed:
        module_name, module, attribute, previous = _installed.pop()
        if module.__dict__.get("_fmofp_stand_in"):
            if sys.modules.get(module_name) is module:
                del sys.modules[module_name]
        elif previous is None:
            delattr(module, attribute)
        else:
            setattr(module, attribute, previous)


class _NoDisplayTree:
    """What the MFD's radar-type switch asks of the display tree manager, when there is none."""

    async def reset_radar_branch(self, radar_type):
        return None


def install_plain_radar_displays():
    """The MFD's radar page gets its pictures from RadarDisplayFactory, whose weather path starts the in-process
    weather widget (event bus, display tree). On the bus the pictures are the plain display classes from the
    factory's own table, one per radar, fed by the feeds; the factory's methods and the display tree are replaced
    by that, in this process only."""
    from FMOFP.Interfaces.userInterface.displays.display_nodes import display_tree_manager
    from FMOFP.Interfaces.userInterface.displays.radar.radar_display_factory import RadarDisplayFactory
    classes = dict(RadarDisplayFactory._display_classes)
    cache = {}

    def create_display(cls, mode):
        kind = type(mode)
        if kind not in cache:
            cache[kind] = classes[kind]()
        return cache[kind]

    def clear_cache(cls, mode_type=None):
        if mode_type is None:
            cache.clear()
        else:
            cache.pop(mode_type, None)

    RadarDisplayFactory.create_display = classmethod(create_display)
    RadarDisplayFactory.clear_cache = classmethod(clear_cache)
    RadarDisplayFactory.invalidate_cache = classmethod(clear_cache)
    display_tree_manager.get_display_tree_manager = lambda: _NoDisplayTree()


def make_mfd(systems_feed):
    """A MultiFunctionDisplay whose in-process sources are the bus feeds: the display tree and the weather widget
    machinery are not started. (Its old-bus radar handler, which this used to switch off, went with unit 29.)"""
    bootstrap()
    install_system_sources(systems_feed)
    import FMOFP.Interfaces.userInterface.displays.mfd as mfd_module
    install_plain_radar_displays()
    mfd = mfd_module.MultiFunctionDisplay()
    mfd.start()
    return mfd


class MfdWindow(QWidget):
    """The multi-function display, RT 13: the unchanged MFD, its radar page fed like the radar display's."""

    def __init__(self, terminal, radar_feed=None, systems_feed=None):
        super().__init__()
        bootstrap()
        weather_fast.install()  # the MFD builds its own weather display for its radar page: the same repair
        from FMOFP.Interfaces.userInterface.displays.radar.radar_display_data_coordinator import (
            get_radar_display_data_coordinator)
        from FMOFP.Systems.radarManagement.radar_enums import (aewc_radarMode, sar_radarMode, targeting_radarMode,
                                                               tfr_radarMode, weather_radarMode)
        self.terminal = terminal
        self.systems = systems_feed if systems_feed is not None else SystemsFeed(terminal)
        self.radar = radar_feed if radar_feed is not None else RadarFeed(terminal, get_radar_display_data_coordinator())
        self.setWindowTitle(f"FMOFP multi-function display - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.mfd = make_mfd(self.systems)
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode, DisplayPage
        from FMOFP.Interfaces.userInterface.displays.mfd import RadarType
        self._display_modes = DisplayMode
        self._pages = DisplayPage
        self._radar_types = RadarType
        self._weather_modes = weather_radarMode
        self._terrain_modes = tfr_radarMode
        self._targeting_modes = targeting_radarMode
        self._aewc_modes = aewc_radarMode
        self._sar_modes = sar_radarMode
        self._radar_display_seen = None
        self._weather_mode_name = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.mfd, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

    def tick(self):
        self.radar.update()
        self._apply_radar_page()
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.mfd.set_mode(self._display_modes[requested.name])
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{self.systems.status_text()}  |  {self.radar.weather_status_text()}  |  "
                            f"{self.radar.tfr_status_text()}")

    def _apply_radar_page(self):
        """Keeps the embedded radar picture in step with the bus: the weather display's mode and range, the terrain
        display's profile, mode and clearance."""
        terrain = self.radar.tfr_data()
        self.systems.terrain = (terrain["terrain_clearance"], terrain["level"])
        display = self.mfd._current_radar_display
        if display is not self._radar_display_seen:
            # The MFD switched radar type: it emptied the coordinator and built a new picture.
            self._radar_display_seen = display
            self._weather_mode_name = None
            self.radar.invalidate()
            self.radar.update()
        if self.mfd.current_page != self._pages.RADAR or display is None:
            return
        kind = self.mfd.current_radar_type
        if kind == self._radar_types.WEATHER:
            name = self.radar.weather_draw_mode
            if name != self._weather_mode_name:
                display._current_mode = self._weather_modes[name]
                display._settings_manager.apply_mode_settings(name)
                display._visual_elements = display._settings_manager.get_settings()
                self._weather_mode_name = name
            display.range_scale = max(10.0, self.radar.weather_range_nm)
            self.mfd.radar_data.mode = self._weather_modes[name]
        elif kind == self._radar_types.TFR:
            self.mfd.radar_data.mode = self._terrain_modes[terrain["mode_name"]]
            self.mfd.radar_data.tfr_data = terrain["tfr_data"]
        elif kind == self._radar_types.TARGETING:
            targeting = self.radar.targeting_data()
            display.range_scale = targeting["range_nm"]
            self.mfd.radar_data.mode = self._targeting_modes[targeting["mode_name"]]
            self.mfd.radar_data.targets = targeting["targets"]
        elif kind == self._radar_types.AEWC:
            aewc = self.radar.aewc_data()
            display.range_scale = aewc["range_nm"]
            self.mfd.radar_data.mode = self._aewc_modes[aewc["mode_name"]]
            self.mfd.radar_data.aewc_tracks = aewc["targets"]
        elif kind == self._radar_types.SAR:
            sar = self.radar.sar_data()
            display.range_scale = sar["range_nm"]
            self.mfd.radar_data.mode = self._sar_modes[sar["mode_name"]]
            # _get_radar_data merges this dictionary into the picture's data when it is truthy.
            self.mfd.radar_data.sar_data = ({"image_data": sar["image_data"], "corner_points": sar["corner_points"],
                                             "resolution": sar["resolution"], "scan_progress": sar["scan_progress"]}
                                            if sar["image_data"] else None)

    def closeEvent(self, event):
        self.mfd.stop()
        super().closeEvent(event)


class HolographicMfdWindow(QWidget):
    """The multi-function display, RT 13, as the MODERN theme builds it: the holographic MFD, its tactical picture,
    systems, communications and weapons pages from the bus (unit 34). Its pages are its own buttons."""

    def __init__(self, terminal, systems_feed=None, radar_feed=None):
        super().__init__()
        bootstrap()
        self.terminal = terminal
        self.systems = systems_feed if systems_feed is not None else SystemsFeed(terminal)
        self.systems.stores_message = m.MfdSmsStores
        self.radar = radar_feed if radar_feed is not None else RadarFeed(terminal, _NullCoordinator())
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode
        from fmofp_display.holographic import bus_holographic_mfd_class
        self._display_modes = DisplayMode
        self.setWindowTitle(f"FMOFP multi-function display (holographic) - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.mfd = bus_holographic_mfd_class()(self.systems, self.radar)
        self.mfd.start()
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.mfd, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)

    def tick(self):
        picture = self.mfd.apply_bus()
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.mfd.set_mode(self._display_modes[requested.name])
        tactical = picture["tactical"]
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{len(tactical['targets'])} targets, {len(tactical['waypoints'])} waypoints  |  "
                            f"{self.systems.status_text()}")

    def closeEvent(self, event):
        self.mfd.cleanup()
        super().closeEvent(event)


class _NullCoordinator:
    """The radar feed's coordinator for a window that draws no weather (the holographic MFD reads only the
    terrain-following radar's profile from the feed)."""

    def store_data(self, data_type, items, request_id):
        return len(items)

    def reset_data(self, data_type=None):
        pass


# ---- the EICAS, RT 14 ------------------------------------------------------------------

def eicas_terminal(port_base):
    return TerminalProcess(EICAS_RT, port_base, m.DspEicasStatus, m.DspEicasModeCmd,
                           receives=(m.BcastFmsFlightData, m.BcastFmsStatus, m.BcastFcsGcasAlerts, m.BcastFcsPerfStatus,
                                     m.BcastEngEngineStatus, m.BcastEngFuelStatus, m.BcastRdrWxScan,
                                     m.EicasDefStatus, m.EicasSnsStatus, m.EicasPwrStatus, m.EicasHydStatus,
                                     m.EicasEcsStatus, m.EicasAvnStatus, m.EicasCasAlerts),
                           blocks=(b.BcastRdrFusedTracks, b.BcastDefRwrContacts))


def make_eicas(systems_feed):
    """An EICASDisplay whose sources are the bus feeds: the FMS and the FMS control, the GCAS, the performance
    monitor, the engine control unit, the built-in test controller, the defensive, sensor and fusion services and
    the weather radar it polls ten times a second all answer from the feed's stand-ins. Its hydraulic rows A and
    B belong to the hydraulics terminal (v1.22): the display's own g-load model of them, a stand-in from before
    the terminal existed, is overwritten with the terminal's readings right after each poll. Its alert list belongs
    to the crew alerting terminal (v1.25): the display's own rules are switched off and the list is put in place,
    under the display's lock, right after each poll."""
    bootstrap()
    install_system_sources(systems_feed)
    import FMOFP.Interfaces.userInterface.displays.eicas as eicas_module

    class BusEicas(eicas_module.EICASDisplay):
        # The rules eicas.py ran in its poll are the crew alerting terminal's now (RT 26, ICD README section 2).
        def _compute_alerts(self, thrust):
            return []

        def _compute_defensive_alerts(self):
            return []

        def _compute_sensor_alerts(self):
            return []

        def _compute_weather_alerts(self):
            return []

        def _poll_data(self):
            super()._poll_data()
            readings = systems_feed.hydraulic_readings()
            if readings:
                self.set_system_readings(**readings)
            alerts = systems_feed.cas_alerts()
            with self._lock:
                self._alerts = alerts

    eicas = BusEicas()
    eicas.start()
    return eicas


class EicasWindow(QWidget):
    """The engine indicating and crew alerting display, RT 14: the unchanged EICAS over the bus feeds."""

    def __init__(self, terminal, systems_feed=None):
        super().__init__()
        bootstrap()
        self.terminal = terminal
        self.systems = systems_feed if systems_feed is not None else SystemsFeed(terminal)
        self.setWindowTitle(f"FMOFP EICAS - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.eicas = make_eicas(self.systems)
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode
        self._display_modes = DisplayMode
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.eicas, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

    def tick(self):
        # The oil readings, the fuel quantity and the balance have no getter the EICAS polls: it takes them through
        # set_engine_readings(), which marks them valid, so they age out like everything else when the bus goes quiet.
        readings = self.systems.engine_readings()
        if readings:
            self.eicas.set_engine_readings(**readings)
        # The electrical (v1.19), hydraulic and ECS rows (v1.22) the same way: the power management, hydraulics
        # and environmental control terminals' statuses through set_system_readings().
        readings = self.systems.system_readings()
        if readings:
            self.eicas.set_system_readings(**readings)
        # The BITS rows (v1.20): eicas.py has no setter for them and wrote "<id>: PASS" for whatever tests a
        # BuiltInTestController listed, so the stand-in lists none and the rows are the avionics terminal's
        # power-on results, set here; none while its status is stale.
        self.eicas._bits_results = self.systems.bit_results()
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.eicas.set_mode(self._display_modes[requested.name])
        alerts = self.eicas._alerts
        warnings = sum(1 for a in alerts if a["severity"] == "WARNING")
        cautions = sum(1 for a in alerts if a["severity"] == "CAUTION")
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{warnings} warnings {cautions} cautions  |  {self.systems.status_text()}")

    def closeEvent(self, event):
        self.eicas.stop()
        super().closeEvent(event)


# ---- the TSD, RT 16 --------------------------------------------------------------------

def tsd_terminal(port_base):
    return TerminalProcess(TSD_RT, port_base, m.DspTsdStatus, m.DspTsdModeCmd,
                           receives=(m.BcastFmsFlightData, m.BcastFmsStatus, m.BcastFmsAttitudeStatus, m.TsdFmsEnergy,
                                     m.BcastMsnStatus),
                           blocks=(b.BcastRdrFusedTracks, b.BcastMsnPlan, b.BcastDefRwrContacts))


def make_tsd(systems_feed):
    """A TacticalSituationDisplay whose sources are the bus feeds: the FMS and the FMS control (flight data, tactical
    systems, envelope warnings, energy metrics), the radar data fusion (the fused tracks), the mission computer (the
    route and the order of battle, from v1.16) and the defensive systems terminal (the radar warning contacts,
    from v1.17). Its own 10 Hz poll reads them."""
    bootstrap()
    install_system_sources(systems_feed)
    import FMOFP.Interfaces.userInterface.displays.tsd as tsd_module
    tsd = tsd_module.TacticalSituationDisplay()
    tsd.start()
    return tsd


class TsdWindow(QWidget):
    """The tactical situation display, RT 16: the unchanged TSD over the bus feeds."""

    def __init__(self, terminal, systems_feed=None):
        super().__init__()
        bootstrap()
        self.terminal = terminal
        self.systems = systems_feed if systems_feed is not None else SystemsFeed(terminal)
        self.setWindowTitle(f"FMOFP tactical situation display - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.tsd = make_tsd(self.systems)
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode
        self._display_modes = DisplayMode
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.tsd, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)

    def tick(self):
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.tsd.set_mode(self._display_modes[requested.name])
        fused = self.systems.fused_summary()
        tracks = "fusion: no data" if fused is None else f"fused {fused[0]} ({fused[1]} hostile), epoch {fused[2]}"
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{self.systems.flight.status_text()}  |  {tracks}")

    def closeEvent(self, event):
        self.tsd.stop()
        super().closeEvent(event)


# ---- the SMS, RT 17 --------------------------------------------------------------------

def sms_terminal(port_base):
    return TerminalProcess(SMS_RT, port_base, m.DspSmsStatus, m.DspSmsModeCmd,
                           receives=(m.BcastFmsStatus, m.DspSmsStores))


def make_sms(systems_feed):
    """A StoresManagementDisplay whose sources are the bus feeds: the FMS and the FMS control it polls five times a
    second for the flight mode and the tactical systems (its ECM cell the countermeasures state, its signature the
    stealth bit). Its stations, master arm, release and delivery modes, selected station, load and armed count are the
    stores management terminal's (v1.26, DSP_SMS_STORES), put in place right after each poll; while that terminal is
    not heard the display keeps the last table it had (its own at start, which is the terminal's starting table) and
    its own master arm."""
    bootstrap()
    install_system_sources(systems_feed)
    import FMOFP.Interfaces.userInterface.displays.sms as sms_module

    class BusSms(sms_module.StoresManagementDisplay):
        def _poll_data(self):
            super()._poll_data()
            status = systems_feed.stores_status()
            stations = systems_feed.stores_stations()
            if status is None or stations is None:
                return
            with self._lock:
                self._master_arm = status.master_arm.name
                self._release_mode = status.release_mode.name
                self._delivery_mode = status.delivery_mode.name
                self._selected_sta = status.selected_station
                for station, store in zip(self._stations, stations):
                    station.store = None if store is None else sms_module._Store(store[0], store[1], store[2],
                                                                                 store[3], store[4])
            self._safe_update()

        def _total_weight_kg(self):
            status = systems_feed.stores_status()
            return super()._total_weight_kg() if status is None else float(status.total_weight)

        def _armed_count(self):
            status = systems_feed.stores_status()
            return super()._armed_count() if status is None else status.armed_count

    sms = BusSms()
    sms.start()
    return sms


class SmsWindow(QWidget):
    """The stores management display, RT 17: the unchanged SMS over the bus feeds."""

    def __init__(self, terminal, systems_feed=None):
        super().__init__()
        bootstrap()
        self.terminal = terminal
        self.systems = systems_feed if systems_feed is not None else SystemsFeed(terminal)
        self.setWindowTitle(f"FMOFP stores management display - RT {terminal.rt}")
        self.status = QLabel("waiting for the bus")
        self.sms = make_sms(self.systems)
        from FMOFP.Interfaces.userInterface.displays.base_display import DisplayMode
        self._display_modes = DisplayMode
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.sms, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)

    def tick(self):
        requested = self.terminal.take_mode_request()
        if requested is not None and requested.name in self._display_modes.__members__:
            self.sms.set_mode(self._display_modes[requested.name])
        sms = self.sms
        self.status.setText(f"RT {self.terminal.rt} {self.terminal.state.name}  frames {self.terminal.syncs}  |  "
                            f"{self.systems.flight.tactical_text()}  |  MASTER ARM {sms._master_arm}, "
                            f"{sms._armed_count()} stations armed, {sms._total_weight_kg():.0f} kg"
                            + ("" if self.systems.stores_status() is not None else "  |  stores computer: no data"))

    def closeEvent(self, event):
        self.sms.stop()
        super().closeEvent(event)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("display", choices=["radar", "pfd", "mfd", "eicas", "tsd", "sms"])
    parser.add_argument("--port-base", type=int, default=51000)
    parser.add_argument("--seconds", type=float, default=0.0, help="close after this long (0 = until the window is closed)")
    parser.add_argument("--verbose", action="store_true",
                        help="keep the FMOFP display code's INFO and DEBUG log lines (dropped by default)")
    parser.add_argument("--theme", choices=THEMES, default="classic",
                        help="the displays' theme (modern: the holographic PFD and MFD)")
    args = parser.parse_args(argv)
    if not args.verbose:
        quiet_fmofp_logging()
    bootstrap()
    apply_theme(args.theme)
    app = QApplication(sys.argv[:1])
    terminals = {"radar": radar_terminal, "pfd": pfd_terminal, "mfd": mfd_terminal, "eicas": eicas_terminal,
                 "tsd": tsd_terminal, "sms": sms_terminal}
    terminal = terminals[args.display](args.port_base)
    status = terminal.start()
    if status != Status.OK:
        print(f"display: terminal init failed: {status.name} (port {args.port_base + terminal.rt} in use?)",
              file=sys.stderr)
        return 1
    windows = {"radar": RadarWindow, "pfd": PfdWindow,
               "mfd": HolographicMfdWindow if holographic("mfd") else MfdWindow, "eicas": EicasWindow,
               "tsd": TsdWindow, "sms": SmsWindow}
    window = windows[args.display](terminal)
    window.show()
    if args.seconds > 0.0:
        QTimer.singleShot(int(args.seconds * 1000.0), app.quit)
    started = time.time()
    try:
        code = app.exec()
    finally:
        terminal.stop()
    print(f"display: RT {terminal.rt} ran {time.time() - started:.0f} s, {terminal.syncs} frames, "
          f"{terminal.blocks_completed} blocks, {terminal.resets} resets")
    return code


if __name__ == "__main__":
    sys.exit(main())
