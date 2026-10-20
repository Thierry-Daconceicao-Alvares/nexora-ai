"""Baselines for the spend category, to compare the model with.

- declared: the category the requester chose in the form, taken as it is.
- keywords: the first category whose keywords appear in the description,
  otherwise the declared one. Written once from the item vocabulary of the
  catalogue, not tuned on the evaluation set.
"""

from __future__ import annotations

import re

KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("capital_equipment", ("press", "storage tower", "machine tool")),
    ("lab_equipment", ("spectrometer", "laboratory", "microscope")),
    ("electrical_services", ("rewiring", "wiring", "electrical installation")),
    ("calibration_services", ("calibration", "calibrate")),
    ("engineering_services", ("engineering", "consultant", "study")),
    ("it_services", ("migration", "monitoring", "patching", "service desk")),
    ("software", ("software", "licence", "license", "subscription")),
    ("it_hardware", ("laptop", "monitor", "switch", "docking", "server", "tablet")),
    ("automation", ("plc", "logic controller", "automation", "robot")),
    ("ppe", ("glove", "helmet", "safety shoe", "goggles", "ppe")),
    ("logistics_services", ("transport", "truck", "freight", "pallet")),
    ("facility_services", ("cleaning", "ventilation", "hvac", "canteen")),
    ("office_supplies", ("paper", "toner", "stationery", "office chair")),
    ("tools", ("wrench", "drill", "grinder", "tool", "driver kit")),
    ("machining", ("machining", "machined")),
    ("spare_parts", ("bearing", "seal", "shaft", "bushing", "gearbox")),
    ("mro_supplies", ("oil", "grease", "fastener", "cable tie", "anchor")),
]


def declared(payload: dict) -> str:
    return payload.get("item_category", "")


def keywords(payload: dict) -> str:
    text = payload.get("description", "").lower()
    for category, words in KEYWORDS:
        if any(re.search(rf"\b{re.escape(word)}", text) for word in words):
            return category
    return declared(payload)
