#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_klv_schema.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 587
#  Abhängigkeiten     : argparse, ctypes, dataclasses, datetime, enum, fractions, http, inspect, logging, pathlib
#                       platform, re, sys, tempfile, textwrap, traceback, typing, zoneinfo
#  Externe Frameworks : requests, tzlocal, yaml
#  Eigene Frameworks  : rpg_utils
#  Klassen            : ACCLData, ANYData, ConsolidatedDEVCBlock, DEVCBlock, FACEData, GPSData, GYROData, KLVItem
#                       NESTEDData, STRMBlock
# ------------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, replace, field
from datetime import datetime
from typing import Final, Any, ClassVar, Self

from rpg_utils.utils_filepath import ENCODING_UTF8


# ---------------------------------------------------------------------------------------
# Globale Konfigurationen / Standardwerte
# ---------------------------------------------------------------------------------------
DEFAULT_HEROVERSION: Final[int] = 3

# ---------------------------------------------------------------------------------------
# GPMF-MAPPINGS: Typ-Codes, Größen und Geräteversionen
# ---------------------------------------------------------------------------------------

# Mapping von GPMF-Typzeichen (Bytes) zu Python-struct Formatcodes (String).
# Die Kommentare basieren auf der offiziellen GPMF-Spezifikation (Type Char, Definition, typedef).
GPMF_TYPE_MAP: Final[dict[bytes | None, str | None]] = {
    b"b": "b",  # 'b': int8_t (single byte signed integer)
    b"B": "B",  # 'B': uint8_t (single byte unsigned integer)
    b"c": "c",  # 'c': char (single byte 'c' style ASCII character string)
    b"d": "d",  # 'd': double (64-bit double precision, IEEE 754)
    b"f": "f",  # 'f': float (32-bit float, IEEE 754)
    b"F": "4s",  # 'F': FourCC (32-bit four character key)
    b"G": "16s",  # 'G': GUID (128-bit ID)
    b"j": "q",  # 'j': int64_t (64-bit signed number)
    b"J": "Q",  # 'J': uint64_t (64-bit unsigned number)
    b"l": "i",  # 'l': int32_t (32-bit signed integer)
    b"L": "I",  # 'L': uint32_t (32-bit unsigned integer)
    b"q": "I",  # 'q': Q15.16 (32-bit Q Number)
    b"Q": "Q",  # 'Q': Q31.32 (64-bit Q Number)
    b"s": "h",  # 's': int16_t (16-bit signed integer)
    b"S": "H",  # 'S': uint16_t (16-bit unsigned integer)
    b"U": "16s",  # 'U': UTC Date and Time string (16 chars)
    b"?": "?",  # '?': komplexe Struktur, kein direct mapping
    b"\x00": "",  # Null-Byte-Typ (oft für NEST-Container)
    None: None,  # None-Typ
}

# Byte-Längen-Tabelle für Python struct-Formatcodes.
STRUCT_SIZES_MAP: Final[dict[str, int]] = {
    "b": 1, "B": 1, "c": 1,
    "h": 2, "H": 2,
    "i": 4, "I": 4, "l": 4, "L": 4, "f": 4, "4s": 4,
    "q": 8, "Q": 8, "d": 8,
    "16s": 16,
}

# GoPro Version Mapping (FOURCC-Prefix zu Version)
GOPRO_VERSION_MAP: Final[dict[str, int]] = {
    'HERO5': 0,
    'FUSIO': 1,
    'HERO6': 2,
    'HERO7': 2,
    'HERO8': 3,
    'HERO9': 3,
    'HERO1': 3,  # Deckt HERO10, HERO11, HERO12, HERO13 ab
}

# ----------------------------------------------------------------------
# Konstanten für Metadaten-Dictionary-Schlüssel
# ----------------------------------------------------------------------
KEY_CLASS_NAME: Final[str] = "class"  # Verweis auf die Datenklasse
KEY_DESCRIPTION: Final[str] = "desc"  # Beschreibungstext
KEY_TYPE: Final[str] = "type"  # Typangabe für einfache Werte

# Häufige FourCCs (GPMF-Schlüssel)
FOURCC_DEVC: Final[str] = "DEVC"
# Das 'B' als Präfix ist eine super Konvention für Byte-Varianten
BFOURCC_DEVC: Final[bytes] = FOURCC_DEVC.encode("ascii")
FOURCC_DVID: Final[str] = "DVID"
FOURCC_DVNM: Final[str] = "DVNM"
FOURCC_STRM: Final[str] = "STRM"
FOURCC_STNM: Final[str] = "STNM"
FOURCC_SCAL: Final[str] = "SCAL"
FOURCC_TYPE: Final[str] = "TYPE"
FOURCC_UNIT: Final[str] = "UNIT"
FOURCC_SIUN: Final[str] = "SIUN"
FOURCC_STMP: Final[str] = "STMP"

FOURCC_GPS5: Final[str] = "GPS5"
FOURCC_GPSU: Final[str] = "GPSU"
FOURCC_GPSF: Final[str] = "GPSF"
FOURCC_GPSP: Final[str] = "GPSP"
FOURCC_GPS9: Final[str] = "GPS9"
FOURCC_ACCL: Final[str] = "ACCL"
FOURCC_GYRO: Final[str] = "GYRO"
FOURCC_FACE: Final[str] = "FACE"


# ---------------------------------------------------------------------------------------
# Allgemeine Daten-Klassen (Container für geparste Daten)
# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class NESTEDData:
    """Repräsentiert einen verschachtelten GPMF-Container (z.B. DEVC oder STRM)."""
    description: str
    content: object


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class ANYData:
    """Basis-Datenstruktur für alle unbekannten oder einfachen KLV-Elemente."""
    description: str
    klv: object  # Der rohe KLVItem oder der Wert
    timestamp: int | None = field(default=None)  # Optionaler Zeitstempel
    no: int | None = field(default=None)  # Optionaler Sample-Index


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class GPSData:
    """Repräsentiert einen einzelnen, vollständig geparsten GPS-Datenpunkt."""
    device_id: int  # str
    device_name: str
    description: str
    timestamp: int
    datetime: datetime
    latitude: float
    longitude: float
    altitude: float
    speed2d: float
    speed3d: float
    units: list[str] | str | None  # Kann String oder Liste von Strings sein
    distance: float
    days2k: int
    secs: int
    DOP: float  # Dilution of Precision
    fix: int  # GPS Fix Status (0: no lock, 2: 2D, 3: 3D)
    no: int  # Sample-Index


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class ACCLData:
    """Repräsentiert einen einzelnen 3-Achsen-Beschleunigungssensor-Datenpunkt."""
    device_id: int  # str
    device_name: str
    description: str
    timestamp: int
    datetime: datetime
    z: float
    x: float
    y: float
    no: int

    # --------------------------------------------------------------------------------
    def with_coords(self, z: float | None = None, x: float | None = None, y: float | None = None) -> Self:
        """Erzeugt eine Kopie mit optional aktualisierten x/y/z-Koordinaten.

        :param z: (float | None) Die neue Z-Koordinate. Default ist None.
        :param x: (float | None) Die neue X-Koordinate. Default ist None.
        :param y: (float | None) Die neue Y-Koordinate. Default ist None.
        :return: Eine neue Instanz von ACCLData mit den aktualisierten Werten.
        """
        # Wir sammeln nur die Werte, die NICHT None sind
        updates: dict[str, float] = {}

        if z is not None: updates["z"] = z
        if x is not None: updates["x"] = x
        if y is not None: updates["y"] = y

        # **updates übergibt nur die validen float-Werte, die Warnung verschwindet
        return replace(self, **updates)


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class GYROData:
    """Repräsentiert einen einzelnen 3-Achsen-Gyroskop-Datenpunkt."""
    device_id: int  # str
    device_name: str
    description: str
    timestamp: int
    datetime: datetime
    z: float
    x: float
    y: float
    no: int

    # --------------------------------------------------------------------------------
    def with_coords(self, z: float | None = None, x: float | None = None, y: float | None = None) -> Self:
        """Erzeugt eine Kopie mit optional aktualisierten x/y/z-Koordinaten.

        :param z: (float | None) Die neue Z-Koordinate. Default ist None.
        :param x: (float | None) Die neue X-Koordinate. Default ist None.
        :param y: (float | None) Die neue Y-Koordinate. Default ist None.
        :return: Eine neue Instanz von ACCLData mit den aktualisierten Werten.
        """
        # Wir sammeln nur die Werte, die NICHT None sind
        updates: dict[str, float] = {}

        if z is not None: updates["z"] = z
        if x is not None: updates["x"] = x
        if y is not None: updates["y"] = y

        # **updates übergibt nur die validen float-Werte, die Warnung verschwindet
        return replace(self, **updates)


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class FACEData:
    """Repräsentiert einen einzelnen Datenpunkt zur Gesichtserkennung (einfache Form)."""
    device_id: int  # str
    device_name: str
    description: str
    timestamp: int
    datetime: datetime
    project: str  # Kann JSON-Daten oder String enthalten
    no: int

    # --------------------------------------------------------------------------------
    def with_coords(self, project: str | None = None) -> Self:
        """Erzeugt eine Kopie mit optional aktualisiertem 'project'-Wert.

        :param project: (str | None) Der neue Projektname. Default ist None.
        :return: Eine neue Instanz mit dem aktualisierten Projektnamen.
        """
        # Wenn nichts übergeben wurde, wird keine Kopie benötigt
        if project is None:
            return self
        else:
            return replace(self, project=project)


# ---------------------------------------------------------------------------------------
# KLVItem: Einzelnes GPMF-Metadaten-Element (Key-Length-Value)
# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
@dataclass(frozen=True, slots=True)
class KLVItem:
    """Repräsentiert ein einzelnes GPMF-KLV-Element (Key-Length-Value)."""

    # Konstanten für Attributnamen, falls sie als Dictionary-Keys verwendet werden
    REPEAT: ClassVar[str] = "repeat"
    VALUE: ClassVar[str] = "value"

    fourCC: str
    type: str
    size: int
    repeat: int
    value: bytes | list[KLVItem]

    # --------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """Überprüft die Integrität des fourCC-Schlüssels.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        if len(self.fourCC) != 4:
            raise ValueError(f"fourCC muss genau 4 Zeichen haben, erhalten: {self.fourCC!r}")

    # --------------------------------------------------------------------------------
    def __eq__(self, other: Any) -> bool:
        """Kurzbeschreibung für __eq__.
        
        :param other: (Any) Beschreibung von other.
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        if isinstance(other, str):
            return self.fourCC == other
        if isinstance(other, KLVItem):
            return self.fourCC == other.fourCC
        return False

    # --------------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Kompakte Darstellung mit gekürztem value für bessere Lesbarkeit.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        v = self.value
        if isinstance(v, bytes) and len(v) > 16:
            v_preview = f"{v[:8]!r}...{v[-4:]!r} ({len(v)} bytes)"
        elif isinstance(v, list):
            v_preview = f"[list with {len(v)} items]"
        else:
            v_preview = repr(v)

        return (
            f"KLVItem(fourCC={self.fourCC!r}, type={self.type!r}, "
            f"size={self.size}, repeat={self.repeat}, value={v_preview})"
        )

    # --------------------------------------------------------------------------------
    @property
    def as_str(self) -> str:
        """Dekodiert den Value-Bytes als String (Standard-Dekodierung, Fehler ersetzt).
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if isinstance(self.value, bytes):
            return self.value.decode(ENCODING_UTF8, errors="replace")
        return str(self.value)

    # --------------------------------------------------------------------------------
    @property
    def as_ints(self) -> list[int]:
        """Gibt den Value-Bytes als Liste von Integer-Werten (0-255) zurück.
        
        :return: (list[int]) Beschreibung des Rückgabewerts.
        """

        if isinstance(self.value, bytes):
            return list(self.value)
        return []

    # --------------------------------------------------------------------------------
    def with_value(self, value: bytes | list[KLVItem]) -> KLVItem:
        """Erzeugt eine Kopie des KLVItem mit einem neuen 'value'.
        
        :param value: (bytes | list[KLVItem]) Beschreibung von value.
        :return: (KLVItem) Beschreibung des Rückgabewerts.
        """

        return replace(self, value=value)


# ---------------------------------------------------------------------------------------
# GPMF-Blockstrukturen
# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
@dataclass(slots=True)
class STRMBlock:
    """Strukturierte Daten für einen einzelnen, unverarbeiteten STRM-Block (Stream)."""

    strm_name: str | None
    strm_scal: KLVItem | None
    strm_type: str | None
    strm_unit: str | list[str] | None
    chunks: list[list[KLVItem]] | None


# ================================================================================
# ================================================================================
@dataclass(slots=True)
class DEVCBlock:
    """Strukturierte Daten für einen unverarbeiteten DEVC-Block (Device/Gerät)."""

    devc_id: int  # int | str | None
    devc_name: str  # | None
    devc_version: int

    attributes: dict[str, KLVItem]
    # Streams sind hier als Liste von STRMBlock-Listen organisiert, da ein DEVC
    # mehrere STRM-Container des gleichen Typs enthalten kann.
    streams: dict[str, list[STRMBlock]] = field(default_factory=dict)


# ================================================================================
# ================================================================================
@dataclass(slots=True)
class ConsolidatedDEVCBlock:
    """Finale, zusammengeführte Datenstruktur für alle konsolidierten Streams"""

    devc_id: int = 0    # int | str = 0
    devc_name: str = ''  # | None = None
    devc_version: int = DEFAULT_HEROVERSION    # | str | None = None

    attributes: dict[str, KLVItem] = field(default_factory=dict)
    # Streams sind hier als einfache Map von Name zu STRMBlock (oder finaler Struktur)
    streams: dict[str, STRMBlock | Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------
# FourCC Metadaten-Mapping
# Mapping FourCC -> {Datenklasse, Beschreibung}
# ---------------------------------------------------------------------------------------
FOURCC_METADATA_MAP: Final[dict[str, dict[str, type | str]]] = {
    FOURCC_DEVC: {KEY_CLASS_NAME: NESTEDData, KEY_DESCRIPTION: "Device container"},
    FOURCC_DVID: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Device/track ID"},
    FOURCC_DVNM: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Device name"},
    FOURCC_STRM: {KEY_CLASS_NAME: NESTEDData, KEY_DESCRIPTION: "Nested signal stream"},
    FOURCC_STNM: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Stream name"},
    "RMRK": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Comments for any stream"},
    FOURCC_SCAL: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Scaling factor"},
    FOURCC_SIUN: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Standard Units"},
    FOURCC_UNIT: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Display units"},
    FOURCC_TYPE: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Typedefs for complex structures"},
    "TSMP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Total Samples delivered"},
    "TIMO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Time Offset"},
    "EMPT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Empty payload count"},
    # Since Hero5
    FOURCC_ACCL: {KEY_CLASS_NAME: ACCLData, KEY_DESCRIPTION: "3-axis accelerometer"},
    FOURCC_GYRO: {KEY_CLASS_NAME: GYROData, KEY_DESCRIPTION: "3-axis gyroscope"},
    "ISOG": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Image sensor gain"},
    "SHUT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Exposure time"},
    # Since Hero5 with GPS enabled Adds
    FOURCC_GPS5: {KEY_CLASS_NAME: GPSData, KEY_DESCRIPTION: "GPS data V5"},
    FOURCC_GPSU: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "UTC time and date"},
    FOURCC_GPSF: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "GPS Fix"},
    FOURCC_GPSP: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "GPS Precision"},
    # Fusion Adds and Changes
    # FOURCC_ACCL
    # FOURCC_GYRO
    FOURCC_STMP: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Timestamp in microseconds"},
    "MAGN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Magnetometer"},
    # ISOG
    # SHUT
    # HERO6 Black Adds and Changes, Otherwise Supports All HERO5 metadata
    # FOURCC_ACCL
    # FOURCC_GYRO
    FOURCC_FACE: {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Face detection"},
    "FCNM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Faces counted per frame"},
    "ISOE": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Sensor ISO"},
    "ALLD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Auto Low Light frame duration"},
    "WBAL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "White Balance in Kelvin"},
    "WRGB": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "White Balance RGB gains"},
    # HERO7 Black (v1.8) Adds, Removes, Changes, Otherwise Supports All HERO6 metadata
    # FACE
    # FCNM
    "YAVG": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Luma average"},
    "HUES": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Predominant hues"},
    "UNIF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Image uniformity"},
    "SCEN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Scene classifier"},
    "SROT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Sensor Read Out Time"},
    # HERO8 Black (v2.5) Adds, Removes, Changes, Otherwise Supports All HERO7 metadata
    # FACE
    "CORI": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Camera Orientation"},  # Camera Orientation
    "IORI": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Image Orientation"},   # Image Orientation
    "GRAV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Gravity Vector"},      # Gravity Vector
    "WNDM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Wind Processing"},     # Window Processing
    "MWET": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Microphone is wet"},   # Microphone Wet
    "AALP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Audio Levels"},        # AGC Audio Level
    "GPSA": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Unknown GPS data"},
    # GoPro MAX (v2.0) Adds, Removes, Changes, Otherwise Supports All HERO7 metadata
    # CORI
    # IORI
    # GRAV
    "DISP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Disparity track"},    # Disparity track (360 modes)
    # HERO9 Changes, Otherwise Supports All HERO8 metadata
    "MSKP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Main video frame skip"},
    "LSKP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Low res video frame skip"},
    # hero 9 fix
    "LRVO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "LRVS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "VPTS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "FSKP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    # HERO10 changes, otherwise supports All HERO9 metadata
    # FACE
    # HERO11 changes, otherwise supports All HERO10 metadata
    # GPS5
    FOURCC_GPS9: {KEY_CLASS_NAME: GPSData, KEY_DESCRIPTION: "GPS data V9"},
    # not defined in document
    "GPRO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "HD5.": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "TMPC": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Device temperature"},
    "TICK": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "STPS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "MTRX": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "ORIN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "ORIO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},
    "MFGI": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # hero6+ble
    "acc1": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # hero6+ble
    "FWVS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "KBAT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "GPRI": {KEY_CLASS_NAME: GPSData, KEY_DESCRIPTION: ""},     # Karma Drone (GPS raw!)
    "ATTD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "GLPI": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "VFRH": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "SYST": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "BPOS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "ATTR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "SIMU": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "ESCS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "SCPR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "LNED": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "CYTS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    "CSEN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: ""},     # Karma Drone
    # HERO12 changes, otherwise supports All HERO11 metadata
    # GPS5, GPS9 removed
    # HERO13 changes, otherwise supports All HERO12 metadata
    "LOGS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "GoPro internal"},
    "VERS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Firmware Version Numbers"},
    "FMWR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Firmware String"},
    "LINF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Lens Info"},
    "CINF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Camera Info"},
    "CASN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Camera Serial Number"},
    "MINF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Camera Model Info"},
    "MUID": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Multi-UUID Data"},
    "CPID": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Chip ID"},
    "CPIN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Chip Instance Number"},
    "CMOD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Camera Mode"},
    "MTYP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Media Type"},
    "HDRV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "HDR Mode"},
    "OREN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Orientation?"},
    "DZOM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Digital Zoom"},
    "DZST": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Digital Zoom Step"},
    "SMTR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Smart Trigger?"},
    "PRTN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Print Flag?"},
    "PTWB": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "White Balance Preset"},
    "PTSH": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Shutter Preset"},
    "PTCL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Color Preset"},
    "EXPT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Exposure Preset"},
    "PIMX": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Max ISO"},
    "PIMN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Min ISO"},
    "PTEV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Exposure Value"},
    "RATE": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Frame Rate"},
    "EISE": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "EIS Enabled"},
    "EISA": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "EIS Settings Array"},
    "HCTL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Hardware Control"},
    "AUPT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Audio Processing Type"},
    "APTO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Auto Power Off"},
    "AUDO": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Audio Mode"},
    "AUBT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Audio Button"},
    "BROD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Broadcast Info"},
    "BRID": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Broadcast ID"},
    "PVUL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Preview Unlock"},
    "PRJT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Project Type"},
    "LMOD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Lens Model"},
    "SOFF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Sensor Offset"},
    "CLKS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Clock Speed"},
    "CDAT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Calibration Date"},
    "SCTM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Sensor Timestamp"},
    "PRNA": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Print Name?"},
    "PRNU": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Print Number?"},
    "SCAP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Snapshot?"},
    "CDTM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Calibration Date Time"},
    "DUST": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Dust Removal Interval"},
    "VRES": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Video Resolution"},
    "VFPS": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Video FPS"},
    "HSGT": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Height Setting"},
    "BITR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Bitrate"},
    "MMOD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Microphone Mode"},
    "RAMP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Ramp"},
    "TZON": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Time Zone"},
    "CLKC": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Clock Calibration"},
    "DZMX": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Digital Zoom Max"},
    "CTRL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Controller Config"},
    "PWPR": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Power Profile"},
    "ORDP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Order Preset"},
    "CLDP": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Cloud Preset?"},
    "PIMD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "ISO Mode Manual"},
    "PRCN": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Custom Name"},
    "DNSC": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Display Settings"},
    "ABSC": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Absolute FOV Start"},
    "XFOV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "FOV X"},
    "YFOV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "FOV Y"},
    "ZFOV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "FOV Z"},
    "VFOV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Vertical FOV"},
    "MFOV": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Max FOV"},
    "MXCF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Matrix X"},
    "MAPX": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Map X"},
    "MYCF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Matrix Y"},
    "MAPY": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Map Y"},
    "PYCF": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Point Y Coordinates"},
    "POLY": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Polygon Data"},
    "ZMPL": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Zoom Level"},
    "ARUW": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "AR Upper Width"},
    "ARWA": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "AR Width Average"},
    "FASC": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Fov Adaptation Score (Digital Lens / EIS)"},
    "CSCM": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "Compression Score Main"},
    "USRD": {KEY_CLASS_NAME: ANYData, KEY_DESCRIPTION: "User Data"},
}


# ---------------------------------------------------------------------------------------
# GPS Fix Übersetzungs-Tabelle
# ---------------------------------------------------------------------------------------
GPS_FIX_XLATE: Final[dict[int, str]] = {
    0: 'no lock (invalid GPS info)',
    2: 'lock 2D (ok)',
    3: 'lock 3D (ok)'
}
