"""Scenario files, read as scenarioEngine.py read them.

A scenario is an XML file of `<event id type time_s>` elements, each with parameter children (`<lat>35.60</lat>`);
`ScenarioEngine._parse` turned each child into a float when its text had a point, an int when it had none, and
the text itself when neither parsed, and `load` sorted the events by time. This module does the same, so that
`test_scenario_oracle.py` can hold the two side by side; the engine (engine.py) is what differs.
"""

import os
import uuid
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

B20SS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO_DIR = os.path.join(B20SS, "FMOFP", "Interfaces", "scenarios")
TRAINING = os.path.join(SCENARIO_DIR, "trainingScenario.xml")
FAILURE = os.path.join(SCENARIO_DIR, "failureScenario.xml")

EVENT_TYPES = ("message", "waypoint", "phase_change", "weather_cell", "radar_contact", "threat_launch",
               "system_failure")


@dataclass
class ScenarioEvent:
    """scenarioEngine.ScenarioEvent, field for field."""
    event_id: str
    event_type: str
    trigger_s: float
    params: dict = field(default_factory=dict)
    fired: bool = False


@dataclass
class Scenario:
    name: str
    path: str
    events: list  # ScenarioEvent, sorted by trigger_s (a stable sort: equal times keep the file's order)


def parse_value(text):
    """_parse's conversion of a parameter's text: a float with a point, an int without, else the text."""
    text = text or ""
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def parse_events(root):
    """Every `event` element under `root` as a ScenarioEvent, in file order (_parse)."""
    events = []
    for elem in root.findall(".//event"):
        event_id = elem.get("id", str(uuid.uuid4())[:8])
        event_type = elem.get("type", "message")
        trigger_s = float(elem.get("time_s", "0"))
        params = {child.tag: parse_value(child.text) for child in elem}
        events.append(ScenarioEvent(event_id, event_type, trigger_s, params))
    return events


def resolve(filename):
    """A relative name is looked up in the frozen scenarios directory, as the Python's load did."""
    return filename if os.path.isabs(filename) else os.path.join(SCENARIO_DIR, filename)


def load_scenario(filename):
    """The scenario in `filename` (a path, or a name in the scenarios directory), its events sorted by time.
    Raises FileNotFoundError or xml.etree.ElementTree.ParseError (the Python logged and returned False)."""
    path = resolve(filename)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    root = ET.parse(path).getroot()
    events = sorted(parse_events(root), key=lambda e: e.trigger_s)
    return Scenario(root.get("name", os.path.basename(path)), path, events)
