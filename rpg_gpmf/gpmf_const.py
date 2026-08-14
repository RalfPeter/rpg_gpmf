#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_const.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 111
#  Abhängigkeiten     : typing
# ------------------------------------------------------------------------------

from typing import Final

"""
    As taken from https://gopro.com/help/articles/question_answer/GoPro-Camera-File-Naming-Convention

    All Videos
        GHxxxxxx.mp4
        GXxxxxxx.mp4
        “H” = AVC encoding
        “X” = HEVC encoding

    Single Video
        GH01xxxx.mp4
        GX01xxxx.mp4
        ‘xxxx = file number

    Chaptered Video
        GHzzxxxx.mp4
        GXzzxxxx.mp4
        ‘xxxx’ = file number
        ‘zz’ = chapter number

    Looping Video
        GHYYxxxx.mp4
        GXYYxxxx.mp4
        ‘xxxx’ = file number
        ‘YY’ = looped prefix
"""
# -------------------------------------------------------------------------------------------
# Konstanten für benannte Benutzer oder allgemeine Konfigurationen.
# -------------------------------------------------------------------------------------------
# Benutzer-IDs
GOPRO_USER_09: Final[str] = 'Biber'
GOPRO_USER_10: Final[str] = 'Ralf'

# -------------------------------------------------------------------------------------------
# Konstanten für Dateierweiterungen / suffixe.
# -------------------------------------------------------------------------------------------
# Erweiterungen
SUFFIX_JPG: Final[str] = '.jpg'                 # Fileextension .jpg Datei
SUFFIX_JPEG: Final[str] = '.jpeg'               # Fileextension .jpeg Datei (Maps)
SUFFIX_PNG: Final[str] = '.png'                 # Fileextension .png Datei
SUFFIX_HTML: Final[str] = '.html'               # Fileextension .html Datei
SUFFIX_JSON: Final[str] = '.json'               # Fileextension .json Datei
SUFFIX_ZIP: Final[str] = '.zip'                 # Fileextension .zip Datei
SUFFIX_GPX: Final[str] = '.gpx'                 # Fileextension .gpx Datei
SUFFIX_GPS: Final[str] = '.gps'                 # Fileextension .gps Datei
SUFFIX_KML: Final[str] = '.kml'                 # Fileextension .kml Datei
SUFFIX_BIN: Final[str] = '.bin'                 # Fileextension .bin Datei
SUFFIX_GPMF: Final[str] = '.gpmf'               # Fileextension .gpmf Datei
SUFFIX_VIRBGPX: Final[str] = '.virb.gpx'        # Fileextension .virb.gpx Datei
SUFFIX_OVERLAY: Final[str] = '.overlay.mp4'     # Fileextension .overlay.mp4 Datei
SUFFIX_GPXCSV: Final[str] = '.gpx.csv'          # Fileextension .gpx.csv Datei
SUFFIX_HEXCSV: Final[str] = '.hex.csv'          # Fileextension .hex.csv Datei
SUFFIX_GYRCSV: Final[str] = '.gyr.csv'          # Fileextension .gyr.csv Datei
SUFFIX_ACCCSV: Final[str] = '.acc.csv'          # Fileextension .acc.csv Datei
SUFFIX_SRT: Final[str] = '.srt'                 # Fileextension .srt Datei

# Listen
VIDEO_EXTENSIONS: Final[tuple[str, ...]] = ('.mp4', '.mov', '.avi', '.mkv')
GPMF_EXTENSIONS: Final[tuple[str, ...]] = (SUFFIX_GPMF, SUFFIX_BIN)
IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (SUFFIX_JPEG, SUFFIX_JPG)
GPX_EXTENSIONS: Final[tuple[str, ...]] = (SUFFIX_GPX, SUFFIX_GPS)

# Liste von Dateimustern, die gelöscht werden sollen
TRASH_EXTENSIONS: Final[tuple[str, ...]] = ('*.*~', '*virb.jpg', '*virb.html')

# Default result tuple
DEFAULT_RESULT = (None, None)
DEFAULT_RESULT_3 = (None, None, None)


# -------------------------------------------------------------------------------------------
# Parameter und Schwellenwerte für die Datenverarbeitung und Darstellung.
# -------------------------------------------------------------------------------------------
# Farben
TRACK_DEFAULT_COLOR: Final[str] = "magenta"
ROUTE_DEFAULT_COLOR: Final[str] = "blue"

# --- Zeit-Parameter (in Sekunden, wenn nicht anders angegeben) ---
# Zeitdifferenz für das 1. Thumbnail
THUMBNAIL_START_OFFSET_SEC: Final[int] = 3
# Maximale Zeitdifferenz zwischen zwei Punkten, für Time aus GPX
MAX_TIME_DIFFERENCE_SEC: Final[int] = 600  # 10 min
# --- Geodaten (GPS) Parameter ---
# Maximale Distanz zwischen 2 GPS-Punkten
MAX_GPS_DISTANCE_METER: Final[int] = 50
# Maximale Distanz, bevor ein Ereignis getriggert wird
MAX_EVENT_DISTANCE_METER: Final[int] = 200
# Maximal erlaubter DOP-Wert (Dilution of Precision)
GPS_DOP_MAX_THRESHOLD: Final[int] = 10  # (GPSDOPMAX)
# Maximale Geschwindigkeit für Plausibilitätsprüfung
GPS_MAX_SPEED: Final[int] = 250  # (GPSMAXSPEED)
# Einheit für die maximale Geschwindigkeit
GPS_MAX_SPEED_UNITS: Final[str] = 'kph'  # (GPSMAXSPEEDUNITS)
# Formatstring für GPS-Ausgabe (GPSFORMAT)
GPS_PRINT_FORMAT: Final[str] = ' >+12.8f'  # Kann für f-String-Formatierung außerhalb der Klasse verwendet werden

# --- Darstellung (Karte) Parameter ---
# Breite der Karte in Pixeln
MAP_WIDTH_PIXELS: Final[int] = 1920
# Höhe der Karte in Pixeln
MAP_HEIGHT_PIXELS: Final[int] = 1080

# Video Encoders
ENCODER_GOPRO: Final[str]    = 'GoPro'
ENCODER_CONTOUR: Final[str]  = 'Ambarella'
ENCODER_NOVATEK: Final[str]  = 'NOVATEK'
ENCODER_ICATCH: Final[str]   = 'iCatch'

ENCODER_LIST: Final[list[str]] = [ENCODER_GOPRO, ENCODER_CONTOUR, ENCODER_NOVATEK, ENCODER_ICATCH]
