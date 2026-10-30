"""Drum kit vocabulary and its standard staff placement.

Staff positions follow the widely used drum-set key (PAS / Weinberg guideline):
feet below in the down-stem voice, hands above in the up-stem voice.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    key: str          # short id used in the text IR
    name: str
    gm: int           # General MIDI percussion note
    step: str         # display-step on the percussion staff
    octave: int
    notehead: str     # MusicXML notehead
    voice: int        # 1 = hands (stems up), 2 = feet (stems down)
    articulation: str = ""


INSTRUMENTS = {i.key: i for i in (
    Instrument("CR", "Crash Cymbal", 49, "A", 5, "x", 1),
    Instrument("RD", "Ride Cymbal", 51, "F", 5, "x", 1),
    Instrument("HH", "Closed Hi-Hat", 42, "G", 5, "x", 1),
    Instrument("HO", "Open Hi-Hat", 46, "G", 5, "x", 1, "open"),
    Instrument("T1", "High Tom", 50, "E", 5, "normal", 1),
    Instrument("T2", "Mid Tom", 47, "D", 5, "normal", 1),
    Instrument("SD", "Snare Drum", 38, "C", 5, "normal", 1),
    Instrument("XS", "Side Stick", 37, "C", 5, "x", 1),
    Instrument("FT", "Floor Tom", 43, "A", 4, "normal", 1),
    Instrument("BD", "Bass Drum", 36, "F", 4, "normal", 2),
    Instrument("HP", "Hi-Hat Pedal", 44, "D", 4, "x", 2),
)}

# Row order in the text IR, top of the staff first.
ORDER = ("CR", "RD", "HH", "HO", "T1", "T2", "SD", "XS", "FT", "BD", "HP")

CLASS_DEFAULT = {"kick": "BD", "snare": "SD", "hi-hat": "HH", "toms": "T2", "cymbals": "CR"}
INSTRUMENT_CLASS = {"BD": "kick", "HP": "hi-hat", "SD": "snare", "XS": "snare", "HH": "hi-hat", "HO": "hi-hat",
                    "T1": "toms", "T2": "toms", "FT": "toms", "CR": "cymbals", "RD": "cymbals"}
