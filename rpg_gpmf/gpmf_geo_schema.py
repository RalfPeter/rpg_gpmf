#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_geo_schema.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 38
#  Abhängigkeiten    : dataclasses
#  Klassen           : GeoInfo, GeoNeighbor
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, field


# ================================================================================
# ================================================================================
@dataclass(slots=True, frozen=True)
class GeoInfo:
    """Zusammenfassung der Geoinformationen (immutable, speichereffizient)."""

    latitude: float | None = None
    longitude: float | None = None
    neighbor: GeoNeighbor | None = None
    # Korrektur: Wenn die Factory eine Liste liefert, ist der Typ 'list[GeoNeighbor]' ohne '| None'
    neighbors: list[GeoNeighbor] = field(default_factory=list)


# ================================================================================
# ================================================================================
@dataclass(slots=True, frozen=True)
class GeoNeighbor:
    """Geoinformationen zum nächsten Nachbarn (immutable, speichereffizient)."""

    geonameid: int
    latitude: float | None = None
    longitude: float | None = None
    countrycode2: str | None = None
    countrycode3: str | None = None
    country: str | None = None
    state: str | None = None            # ADM1
    region: str | None = None           # ADM2
    county: str | None = None           # ADM3
    municipality: str | None = None     # ADM4
    city: str | None = None
    elevation: float | None = None
    timezone: str | None = None
    population: int | None = None
    haversine: float | None = None
