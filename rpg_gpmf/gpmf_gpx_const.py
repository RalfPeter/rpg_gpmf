#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_gpx_const.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 100
#  Abhängigkeiten    : typing
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

from typing import Final


# -----------------------------------------------------------
# Globale Konstanten
# -----------------------------------------------------------
DEFAULT_TYPE: Final[str] = '-'
DEFAULT_STR: Final[str] = ''
DEFAULT_DOC_NAME: Final[str] = "Demo"
DEFAULT_DOC_DESC: Final[str] = "Description Demo"
DEFAULT_TRACK_TITLE: Final[str] = "Track Title"
DEFAULT_TRACK_DESC: Final[str] = "Track Description"

# -----------------------------------------------------------
# Globale Konstanten für die GPX-Formatierung
# -----------------------------------------------------------
GPX_DEFAULT_TRACK_NAME: Final[str] = "exercise"
# Wiederverwendung der strukturellen XML-Konstanten (analog zu GPXGenerator)
GPX_XML_DECLARATION: Final[str] = '<?xml version="1.0" encoding="UTF-8"?>\n'
GPX_TRK_OPEN: Final[str] = '<trk>\n'
GPX_TRK_CLOSE: Final[str] = "</trk>\n"
GPX_GPX_CLOSE: Final[str] = "</gpx>\n"
GPX_SRC_TAG: Final[str] = '\t<src>GoPro Hero Cam</src>\n'
GPX_TRKSEG_OPEN: Final[str] = '\t<trkseg>\n'
GPX_TRKSEG_CLOSE: Final[str] = '\t</trkseg>\n'

# -----------------------------------------------------------
# Globale Konstanten für die JSON- HEX-JSON-Formatierung
# -----------------------------------------------------------
JSON_INDENT: Final[int] = 4
# JSON-Schlüsselnamen zur Vermeidung von String-Literalen im Code
JSON_KEY_FOUR_CC: Final[str] = "fourCC"
JSON_KEY_TYPE: Final[str] = "type"
JSON_KEY_SIZE: Final[str] = "size"
JSON_KEY_REPEAT: Final[str] = "repeat"
JSON_KEY_DATA: Final[str] = "data"
JSON_KEY_RAWB: Final[str] = "rawb"

# -----------------------------------------------------------
# Globale Konstanten für die KML-Formatierung
# -----------------------------------------------------------
KML_NAMESPACE: Final[str] = "https://www.opengis.net/kml/2.2"
KML_STYLE_ID: Final[str] = "yellowLineGreenPoly"
KML_LINE_COLOR: Final[str] = "FF1400BE"
KML_LINE_WIDTH: Final[str] = "4"
KML_POLY_COLOR: Final[str] = "7f00ff00"
KML_COORDS_PREFIX: Final[str] = "\t\t\t\t\t"


# -----------------------------------------------------------
# Globale Konstanten für das CSV-Modul
# -----------------------------------------------------------
CSV_NEWLINE: Final[str] = '\n'


# -----------------------------------------------------------
# Globale Konstanten für das GPX header
# -----------------------------------------------------------
GPX_HEADER_XMLNS_SHORT: Final[tuple[str, ...]] = (
    f'xmlns="http://www.topografix.com/GPX/1/1"',
    'xmlns:gpxacc="http://www.garmin.com/xmlschemas/AccelerationExtension/v1"',
    'version="1.1"',
    'creator="https://github.com/RalfPeter/gpmf2file"'
)

GPX_HEADER_XMLNS: Final[tuple[str, ...]] = (
    f'xmlns="http://www.topografix.com/GPX/1/1"',
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
    'xmlns:wptx1="http://www.garmin.com/xmlschemas/WaypointExtension/v1"',
    'xmlns:gpxtrx="http://www.garmin.com/xmlschemas/GpxExtensions/v3"',
    'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v2"',
    'xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3"',
    'xmlns:trp="http://www.garmin.com/xmlschemas/TripExtensions/v1"',
    'xmlns:adv="http://www.garmin.com/xmlschemas/AdventuresExtensions/v1"',
    'xmlns:prs="http://www.garmin.com/xmlschemas/PressureExtension/v1"',
    'xmlns:tmd="http://www.garmin.com/xmlschemas/TripMetaDataExtensions/v1"',
    'xmlns:vptm="http://www.garmin.com/xmlschemas/ViaPointTransportationModeExtensions/v1"',
    'xmlns:ctx="http://www.garmin.com/xmlschemas/CreationTimeExtension/v1"',
    'xmlns:gpxacc="http://www.garmin.com/xmlschemas/AccelerationExtension/v1"',
    'xmlns:gpxpx="http://www.garmin.com/xmlschemas/PowerExtension/v1"',
    'xmlns:vidx1="http://www.garmin.com/xmlschemas/VideoExtension/v1"',
    'creator="Garmin Desktop App"',
    'version="1.1"'
)

GPX_SCHEMA_LOCATION: Final[tuple[str, ...]] = (
    f'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd',
    'http://www.garmin.com/xmlschemas/WaypointExtension/v1 http://www8.garmin.com/xmlschemas/WaypointExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/TrackPointExtension/v2 http://www8.garmin.com/xmlschemas/TrackPointExtensionv2.xsd',
    'http://www.garmin.com/xmlschemas/GpxExtensions/v3 http://www8.garmin.com/xmlschemas/GpxExtensionsv3.xsd',
    'http://www.garmin.com/xmlschemas/ActivityExtension/v1 http://www8.garmin.com/xmlschemas/ActivityExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/AdventuresExtensions/v1 http://www8.garmin.com/xmlschemas/AdventuresExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/PressureExtension/v1 http://www.garmin.com/xmlschemas/PressureExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/TripExtensions/v1 http://www.garmin.com/xmlschemas/TripExtensionsv1.xsd',
    'http://www.garmin.com/xmlschemas/TripMetaDataExtensions/v1 http://www.garmin.com/xmlschemas/TripMetaDataExtensionsv1.xsd',
    'http://www.garmin.com/xmlschemas/ViaPointTransportationModeExtensions/v1 http://www.garmin.com/xmlschemas/ViaPointTransportationModeExtensionsv1.xsd',
    'http://www.garmin.com/xmlschemas/AccelerationExtension/v1 http://www.garmin.com/xmlschemas/AccelerationExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/PowerExtension/v1 http://www.garmin.com/xmlschemas/PowerExtensionv1.xsd',
    'http://www.garmin.com/xmlschemas/VideoExtension/v1 http://www.garmin.com/xmlschemas/VideoExtensionv1.xsd"',
)
