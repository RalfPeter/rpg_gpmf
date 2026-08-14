#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_gpx_jpeg.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 610
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : GGPXJpegManager
# ------------------------------------------------------------------------------

from cProfile import Profile
import pstats
from io import StringIO

from dataclasses import replace
from pathlib import Path
from typing import TypeAlias, Final
from datetime import datetime

from rpg_utils.utils_core import TRENNER, CallbackTag as Tag, log_to_callback, ProgressEvent
from rpg_utils.utils_filepath import PathUtils
from rpg_utils.utils_math import MathUtils
from rpg_utils.utils_string import StringUtils
from rpg_gpx.gpx_schema import GeoPointTime, GeoPoint, GeoPointRef
from rpg_gpmf.gpmf_const import GPS_PRINT_FORMAT, IMAGE_EXTENSIONS, GPX_EXTENSIONS, MAX_TIME_DIFFERENCE_SEC, MAX_EVENT_DISTANCE_METER
from rpg_gpmf.gpmf_gpx import GGPX
from rpg_gpmf.gpmf_exif import EExiv2
from rpg_gpmf.gpmf_geo import get_geocities_service

# =======================================================================
# Der Typ erlaubt nun valide Punkte ODER die leere Repräsentation
GeoPointMap: TypeAlias = dict[str, GeoPointRef | None]
# --- Konstanten ---
INFINITY: Final[float] = float('inf')


# ===========================================================================================
# GGPXJpegManager
# ===========================================================================================
class GGPXJpegManager:
    """Verarbeitet eine Liste JPEG mit Geo-Items (den JPEG-Metadaten) und reichert diese."""

    # --------------------------------------------------------------------------------
    def __init__(self,
                 path_jpeg: Path,
                 path_gpx: Path,
                 diff_time: int = MAX_TIME_DIFFERENCE_SEC,
                 diff_dist: int = MAX_EVENT_DISTANCE_METER,
                 verbose: bool = False) -> None:
        """Initialisiert den Prozessor mit den Pfaden zu den Dateien für Suchoperationen.
        
        :param path_jpeg: (Path) Pfad(e) zu den JPEG-Dateien.
        :param path_gpx: (Path) Pfad(e) zu den GPX-Dateien.
        :param diff_time: (int) Maximal erlaubte Zeitdifferenz in Sekunden für die Suche (Default: 10).
        :param diff_dist: (int) Maximal erlaubte Distanzdifferenz in Metern für die Suche (Default: 100).
        :param verbose: (bool) Flag für detaillierte Log-Ausgaben.
        """
        self.path_jpg: Path = path_jpeg
        self.path_gpx: Path = path_gpx
        self.diff_time: int = diff_time
        self.diff_dist: int = diff_dist
        self.verbose: bool = verbose
        self.geocities_service = get_geocities_service(verbose=self.verbose)

        self.files_jpg: list[Path] = self._create_filelist(self.path_jpg, extensions=IMAGE_EXTENSIONS)
        self.files_gpx: list[Path] = self._create_filelist(self.path_gpx, extensions=GPX_EXTENSIONS)
        self.jpg_items: GeoPointMap = self._create_images_library()

    # --------------------------------------------------------------------------------
    @staticmethod
    def _create_filelist(path: Path, extensions: tuple[str, ...]) -> list[Path]:
        """Erstellt eine gefilterte Liste von Dateien, basierend auf einem einzelnen Path oder einer Liste von Paths.
        
        :param path: (Path) Ein einzelner Pfad oder eine Liste von Pfaden (Verzeichnis oder Datei).
        :param extensions: (tuple[str, ...]) Tupel der erlaubten Dateiendungen (ohne Punkt, z.B. ('jpg', 'jpeg')).
        :return: (list[Path]) Beschreibung
        """
        files: list[Path] = []

        # Nutzung eines Sets für extrem schnelle Lookups (O(1)) statt sequentieller Listen
        extensions_set: set[str] = {ext.casefold() for ext in extensions}

        # -------------------------------------------------------------------
        # 1. Fall: Pfad ist eine einzelne Datei
        if path.is_file():
            # Prüfen, ob die einzelne Datei die Kriterien erfüllt
            if path.suffix.casefold() in extensions_set:
                files.append(path.resolve())

        # -------------------------------------------------------------------
        # 2. Fall: Pfad ist ein Verzeichnis
        elif path.is_dir():
            # Durchsuche das Verzeichnis nach allen Dateien.
            # Das Filtern nach Suffixen im Python-Code ist plattformübergreifend
            # sicherer gegen Case-Sensitivity als path.glob() unter Linux.
            for file in path.glob('*'):
                if file.is_file():
                    if file.suffix.casefold() in extensions_set:
                        files.append(file.resolve())

        # Entfernen von Duplikaten (falls path_list doppelte Pfade enthielt) und Sortieren
        return sorted(list(set(files)))

    # --------------------------------------------------------------------------------
    def _add_timezone(self, cd: datetime | None, point: GeoPoint | None) -> datetime | None:
        """Bestimmt die Zeitzone basierend auf den Geokoordinaten und weist sie dem Zeitstempel zu.
        
        :param cd: (datetime | None) Der ursprüngliche Erstellungszeitstempel des Bildes.
        :param point: (GeoPoint | None) Die Geokoordinaten des Bildes zur räumlichen Bestimmung.
        :return: (datetime | None) Beschreibung
        """
        # Überspringe Fotos ohne Aufnahmedatum und ohne Geolocation
        if cd is None:
            return None
        if point is None:
            return cd

        # Wenn point existiert, extrahieren wir die Werte typsicher, ansonsten setzen wir den Fallback
        lat = MathUtils.safe_float(point.latitude) if point and MathUtils.is_valid_float(point.latitude) else None
        lon = MathUtils.safe_float(point.longitude) if point and MathUtils.is_valid_float(point.longitude) else None

        # Bestimme Zeitzone
        tz = cd.tzinfo if cd else None
        timestamp = cd
        # wir suchen die passende Zeitzone
        if self.geocities_service and lat and lon:
            tz = self.geocities_service.get_tzinfo(latitude=lat, longitude=lon) if self.geocities_service else None

        # um später die korrekte Zeitzone finden zu können, konvertieren wir nach UTC
        if tz and timestamp:
            timestamp = timestamp.replace(tzinfo=tz)

        return timestamp

    # --------------------------------------------------------------------------------
    def _create_images_library(self) -> GeoPointMap:
        """Erstellt ein Dictionary mit allen Bildern im Pfad, speichert das Erstellungsdatum und die Geolokalisierung.
        
        :return: (GeoPointMap) Beschreibung des Rückgabewerts.
        """

        library_data: GeoPointMap = {}

        ii = len(self.files_jpg)
        if ii <= 0:
            return library_data

        # Setze das Maximum für das Einlesen
        log_to_callback(Tag.PROGRESS, ProgressEvent.start(ii))
        i = 0
        for file_name in self.files_jpg:
            i += 1
            # Fortschritt an GUI senden
            log_to_callback(Tag.PROGRESS, ProgressEvent.update(i, ii))

            # skip hidden files
            if file_name.name.startswith('.'):
                continue

            try:
                # Neu und sauberer:
                log_to_callback(Tag.PROGRESS, f"Foto {i}/{ii}", f"Lese Exif Daten von [{file_name.name}]")
                jpeg_exif = EExiv2(file_name, verbose=self.verbose)
            except UnicodeDecodeError:
                continue
            except Exception as e:
                log_to_callback(Tag.ERR, GGPXJpegManager.__name__, f"EXIF Fehler: Fehler im Foto {file_name.name}: Typ: {type(e).__name__} - {e.args}")
                continue
            else:
                point = jpeg_exif.read_geolocation()
                cd = jpeg_exif.read_creationdate(point=point)

                # Überspringe Fotos ohne Aufnahmedatum und ohne Geolocation
                if cd is None and point is None:
                    if self.verbose:
                        log_to_callback(Tag.PROGRESS, GGPXJpegManager.__name__, f"Foto {file_name.name} hat weder Aufnahmedatum noch Geolocation, wird übersprungen")
                    jpeg_exif.close()
                    continue

                # Bestimme Zeitzone für JpegMetaData
                timestamp = self._add_timezone(cd=cd, point=point)
                tz = timestamp.tzinfo if timestamp else None

                geo = GeoPointRef(
                    filename=str(file_name),
                    timestamp=timestamp,
                    latitude=point.latitude if point else None,
                    longitude=point.longitude if point else None,
                    elevation=point.elevation if point else None,
                    diff=None,
                    dist=None,
                    tz=tz
                )
                library_data[str(file_name)] = geo

                jpeg_exif.close()

        return library_data

    # --------------------------------------------------------------------------------
    def _get_elevation(self,
                       latitude: float | None = None,
                       longitude: float | None = None) -> float | None:
        """Ruft die Höheninformation für Koordinaten ab, wenn diese noch nicht existiert.
        
        :param latitude: (float | None) Breitengrad des Punktes.
        :param longitude: (float | None) Längengrad des Punktes.
        :return: (float | None) Beschreibung
        """
        service = self.geocities_service
        if service is None:
            return None

        return service.get_elevation(latitude=latitude, longitude=longitude)

    # --------------------------------------------------------------------------------
    def nearest_location_or_time(self) -> tuple[list[GeoPointRef], list[GeoPointRef]]:
        """Füllt fehlende GPS-Daten oder Zeitstempel mittels der geladenen GPX-Dateien auf.
        
        :return: (tuple[list[GeoPointRef], list[GeoPointRef]]) Beschreibung des Rückgabewerts.
        """

        profiling: bool = False
        l_profiler: Profile | None = None

        if profiling:
            l_profiler = Profile()
            if l_profiler:
                l_profiler.enable()

        # Mapping der JPEGs für O(1) Zugriff
        # 1. Wir definieren das Mapping explizit als dict[str, GeoPointRef]
        jpeg_map: dict[str, GeoPointRef] = {}
        # 2. Durch die explizite Prüfung erkennt PyCharm nun 'item' als 'GeoPointRef'
        for item in self.jpg_items.values():
            if item is not None and item.filename is not None:
                jpeg_map[item.filename] = item

        # Engine instanziieren (lädt alle Dateien, aber berechnet Bäume bei Bedarf via _prepare)
        gpx_engine = GGPX(
            path=self.path_gpx,
            diff_time=self.diff_time,
            diff_dist=self.diff_dist,
            load_on_init=True,
            verbose=self.verbose
        )

        # Baut intern die _flat_tracks und _track_trees für alle GPX-Dateien vor
        gpx_engine.prepare_search_structures()

        # O(N * M) Iteration über JPEGs und geladene GPX-Dateien
        for filename, geo_item in jpeg_map.items():
            if geo_item is None or self._is_already_optimal(geo_item):
                continue

            current_best: GeoPointRef = geo_item

            # Durchsuche alle in GGPX geladenen GPX-Dateien
            for gpx_file in gpx_engine.files:
                updated_item = self._match_indexed_data(gpx_engine, gpx_file, current_best)
                if updated_item and self._is_better_than_current(updated_item, current_best):
                    current_best = updated_item

            jpeg_map[filename] = current_best

        # Ergebnis-Trennung
        complemented: list[GeoPointRef] = [v for v in jpeg_map.values() if v.diff is not None or v.dist is not None]
        uncomplemented: list[GeoPointRef] = [v for v in jpeg_map.values() if v not in complemented]

        # 4. Profiling Auswertung
        if l_profiler:
            l_profiler.disable()
            s = StringIO()
            ps = pstats.Stats(l_profiler, stream=s).sort_stats("cumtime")
            print("\n=== TOP 20 PROFILING ZEITFRESSER ===")
            ps.print_stats(20)
            print(s.getvalue())

        return complemented, uncomplemented

    # --------------------------------------------------------------------------------
    def _match_indexed_data(self, gpx_engine: GGPX, gpx_file: Path, item: GeoPointRef) -> GeoPointRef | None:
        """Sucht über die GGPX-Instanz die passenden Abgleichsdaten für ein JPEG-Objekt.

        :param gpx_engine: (GGPX) Die vorbelegte GGPX-Instanz.
        :param gpx_file: (Path) Der Pfad der zu durchsuchenden GPX-Datei.
        :param item: (GeoPointRef) Das abzugleichende Bild-Metadatenobjekt.
        :return: (GeoPointRef | None) Das aktualisierte Metadatenobjekt oder None.
        """
        # Fall 1: Zeitstempel vorhanden (Lookup nach Position)
        if item.timestamp is not None:
            ts: datetime = item.timestamp
            match_res = gpx_engine.find_nearest_by_timestamp(gpx_file, ts)
            if match_res is not None:
                nearest, diff, _ = match_res
                current_diff = item.diff if item.diff is not None else INFINITY
                if diff < current_diff and diff <= self.diff_time:
                    return GeoPointRef(
                        filename=item.filename,
                        timestamp=nearest.timestamp,
                        latitude=nearest.latitude,
                        longitude=nearest.longitude,
                        elevation=nearest.elevation or self._get_elevation(nearest.latitude, nearest.longitude),
                        diff=diff,
                        dist=None,
                        tz=nearest.tz or item.tz
                    )

        # Fall 2: Position vorhanden, Zeit fehlt (Lookup nach Zeitstempel)
        elif item.latitude is not None and item.longitude is not None:
            target_pt = GeoPoint(latitude=item.latitude, longitude=item.longitude)
            match_res = gpx_engine.find_nearest_by_position(gpx_file, target_pt)
            if match_res is not None:
                nearest, dist, _ = match_res
                current_dist = item.dist if item.dist is not None else INFINITY
                if dist < current_dist and dist <= self.diff_dist:
                    return GeoPointRef(
                        filename=item.filename,
                        timestamp=nearest.timestamp,
                        latitude=item.latitude,
                        longitude=item.longitude,
                        elevation=nearest.elevation or self._get_elevation(nearest.latitude, nearest.longitude),
                        diff=None,
                        dist=dist,
                        tz=nearest.tz or item.tz
                    )

        return None

    # --------------------------------------------------------------------------------
    def _is_already_optimal(self, item: GeoPointRef) -> bool:
        """Prüft, ob das Element bereits innerhalb der gewünschten Toleranzgrenzen liegt.
        
        :param item: (GeoPointRef) Das zu prüfende Bild-Metadatenobjekt.
        :return: (bool) Beschreibung
        """
        diff = item.diff if item.diff is not None else INFINITY
        dist = item.dist if item.dist is not None else INFINITY
        return diff <= self.diff_time or dist <= self.diff_dist

    # --------------------------------------------------------------------------------
    @staticmethod
    def _is_better_than_current(new: GeoPointRef, current: GeoPointRef) -> bool:
        """Vergleicht die Qualität zweier GeoPointRef-Objekte basierend auf deren Informationsgehalt.
        
        :param new: (GeoPointRef) Das neu gefundene Datenobjekt aus der aktuellen Suche.
        :param current: (GeoPointRef) Das bisher beste im Speicher befindliche Datenobjekt.
        :return: (bool) Beschreibung
        """

        # 1. Check: Verfügbarkeit von Zeitzonen (Wichtig für die korrekte Zeitrechnung)
        if current.tz is None and new.tz is not None:
            return True
        if current.tz is not None and new.tz is None:
            return False

        # 2. Check: Grundlegende Datenverfügbarkeit
        if current.timestamp is None and new.timestamp is not None:
            return True
        if current.timestamp is not None and new.timestamp is None:
            return False

        if current.latitude is None and new.latitude is not None:
            return True
        if current.latitude is not None and new.latitude is None:
            return False

        # Standardwerte für Vergleiche setzen, falls Werte None sind
        n_diff = new.diff if new.diff is not None else INFINITY
        c_diff = current.diff if current.diff is not None else INFINITY

        n_dist = new.dist if new.dist is not None else INFINITY
        c_dist = current.dist if current.dist is not None else INFINITY

        # ============================================================================
        # ENTSCHEIDUNGSLOGIK (Die Kernkorrektur)
        # ============================================================================

        # SZENARIO 1: Beide haben einen gültigen Zeitstempel (Foto hatte EXIF-Zeit)
        # Die zeitliche Komponente MUSS primär gewinnen.
        if new.timestamp is not None and current.timestamp is not None:
            if n_diff < c_diff:
                return True
            elif n_diff > c_diff:
                return False
            else:
                # Tie-Breaker: Wenn die zeitliche Abweichung exakt identisch ist,
                # entscheidet die räumliche Nähe.
                return n_dist < c_dist

        # SZENARIO 2: Reines Geo-Matching (Fotos ohne Zeitstempel)
        # Hier entscheidet rein die räumliche Nähe zum Zielpunkt.
        return n_dist < c_dist

    # --------------------------------------------------------------------------------
    def _match_gpx_data(self, engine: GGPX, item: GeoPointRef, gpx_file: Path) -> GeoPointRef | None:
        """Ermittelt basierend auf der Datenlage die passende Abgleichsstrategie.
        
        :param engine: (GGPX) Die GGPX-Suchinstanz.
        :param item: (GeoPointRef) Das abzugleichende Bild-Metadatenobjekt.
        :param gpx_file: (Path) Der Pfad zur aktuell durchsuchten GPX-Datei.
        :return: (GeoPointRef | None) Beschreibung
        """

        match (item.timestamp is not None, item.latitude is not None):
            case (True, False):
                return self._process_time_lookup(engine, item, gpx_file)
            case (False, True):
                return self._process_pos_lookup(engine, item, gpx_file)
            case (True, True):
                return self._process_refinement(engine, item, gpx_file)
            case _:
                return None

    # --------------------------------------------------------------------------------
    def _process_time_lookup(self, engine: GGPX, item: GeoPointRef, gpx_file: Path) -> GeoPointRef | None:
        """Sucht nach fehlenden Positionsdaten basierend auf dem Bild-Zeitstempel.
        
        :param engine: (GGPX) Die GGPX-Suchinstanz.
        :param item: (GeoPointRef) Das Bild-Metadatenobjekt mit gültigem Zeitstempel.
        :param gpx_file: (Path) Der Pfad zur aktuell durchsuchten GPX-Datei.
        :return: (GeoPointRef | None) Beschreibung
        """
        if item is None or item.timestamp is None:
            return None

        result = engine.find_nearest_by_timestamp(gpx_file, item.timestamp)
        if result and result[1] < (item.diff or INFINITY):
            nearest, diff, _ = result
            return GeoPointRef(
                filename=item.filename, timestamp=nearest.timestamp,
                latitude=nearest.latitude, longitude=nearest.longitude,
                elevation=nearest.elevation or self._get_elevation(nearest.latitude, nearest.longitude),
                diff=diff, dist=None, tz=nearest.tz or item.tz
            )
        return None

    # --------------------------------------------------------------------------------
    def _process_pos_lookup(self, engine: GGPX, item: GeoPointRef, gpx_file: Path) -> GeoPointRef | None:
        """Sucht nach fehlenden Zeitstempeln basierend auf der bekannten Bild-Position.
        
        :param engine: (GGPX) Die GGPX-Suchinstanz.
        :param item: (GeoPointRef) Das Bild-Metadatenobjekt mit gültigen Positionsdaten.
        :param gpx_file: (Path) Der Pfad zur aktuell durchsuchten GPX-Datei.
        :return: (GeoPointRef | None) Beschreibung
        """

        if item is None or item.latitude is None or item.longitude is None:
            return None

        result = engine.find_nearest_by_position(gpx_file, GeoPoint(latitude=item.latitude, longitude=item.longitude))
        if result and result[1] < (item.dist or INFINITY):
            nearest, dist, _ = result
            return GeoPointRef(
                filename=item.filename, timestamp=nearest.timestamp,
                latitude=item.latitude, longitude=item.longitude,
                elevation=nearest.elevation or self._get_elevation(nearest.latitude, nearest.longitude),
                diff=None, dist=dist, tz=nearest.tz or item.tz
            )
        return None

    # --------------------------------------------------------------------------------
    def _process_refinement(self, engine: GGPX, item: GeoPointRef, gpx_file: Path) -> GeoPointRef | None:
        """Optimiert bestehende vollständige Bildkoordinaten gegen präzisere GPX-Punkte ab.
        
        :param engine: (GGPX) Die GGPX-Suchinstanz.
        :param item: (GeoPointRef) Das vollständige Bild-Metadatenobjekt.
        :param gpx_file: (Path) Der Pfad zur aktuell durchsuchten GPX-Datei.
        :return: (GeoPointRef | None) Beschreibung
        """
        if item is None or item.timestamp is None or item.latitude is None or item.longitude is None:
            return None

        result = engine.find_nearest_by_timestamp(gpx_file, item.timestamp)
        # Nur übernehmen, wenn es innerhalb der Limits liegt
        if result and result[1] < (item.diff or INFINITY) and result[1] < self.diff_time:
            nearest, diff, _ = result
            return GeoPointRef(
                filename=item.filename, timestamp=nearest.timestamp,
                latitude=nearest.latitude, longitude=nearest.longitude,
                elevation=nearest.elevation or self._get_elevation(nearest.latitude, nearest.longitude),
                diff=diff, dist=None, tz=nearest.tz or item.tz
            )
        return None

    # --------------------------------------------------------------------------------
    def rename_jpegfiles(self, list_a: list[GeoPointRef], list_b: list[GeoPointRef]) -> tuple[list[GeoPointRef], list[GeoPointRef]]:
        """Führt das zeitbasierte Umbenennen von Dateien auf zwei separaten Listen aus.
        
        :param list_a: (list[GeoPointRef]) Erste Liste von Bild-Metadatenobjekten.
        :param list_b: (list[GeoPointRef]) Zweite Liste von Bild-Metadatenobjekten.
        :return: (tuple[list[GeoPointRef], list[GeoPointRef]]) Beschreibung
        """
        # Anwendung der rename_jpegfiles-Funktion auf die erste Liste
        result_a = self._rename_jpegfiles(list_a)

        # Anwendung der rename_jpegfiles-Funktion auf die zweite Liste
        result_b = self._rename_jpegfiles(list_b)

        # Rückgabe der Ergebnisse als Tupel
        return result_a, result_b

    # --------------------------------------------------------------------------------
    @staticmethod
    def _rename_jpegfiles(jpegfiles: list[GeoPointRef]) -> list[GeoPointRef]:
        """Benennt Bilddateien physisch auf der Festplatte basierend auf ihrem Zeitstempel um.
        
        :param jpegfiles: (list[GeoPointRef]) Liste der umzubenennenden Bild-Metadatenobjekte.
        :return: (list[GeoPointRef]) Beschreibung
        """
        if not jpegfiles:
            return []

        updated_files: list[GeoPointRef] = []
        i = 0
        ii = len(jpegfiles)
        # Setze das Maximum für das Einlesen
        log_to_callback(Tag.PROGRESS, ProgressEvent.start(ii))

        for jpeg in jpegfiles:
            i += 1
            log_to_callback(Tag.PROGRESS, ProgressEvent.update(i, ii))

            # Die ursprüngliche Datei wird beibehalten, solange sie nicht umbenannt wird
            current_jpeg = jpeg

            # Prüfung auf Existenz der GPX-Datei
            if jpeg.filename is not None and not Path(jpeg.filename).with_suffix('.gpx').exists():

                if jpeg.tz is not None:
                    # Zeitzone der GeoPoint ist utc, wenn reale Zeitzone anders
                    timestamp = jpeg.timestamp.astimezone(jpeg.tz) if jpeg.timestamp is not None and jpeg.tz != jpeg.timestamp.tzinfo else jpeg.timestamp
                    # Umbenennungsversuch
                    renamed, new_filename = PathUtils.rename_file_with_datetime(jpeg.filename, timestamp)

                    # Erfolgreiche Umbenennung führt zur Erstellung eines NEUEN JpegMetaData-Objekts
                    if renamed:
                        log_to_callback(Tag.PROGRESS, GGPXJpegManager.__name__, f"Jpeg umbenannt {i}/{ii}: {str(Path(jpeg.filename).name)} -> {new_filename.name}")
                        current_jpeg = replace(jpeg, filename=str(new_filename))

            updated_files.append(current_jpeg)

        return updated_files

    # --------------------------------------------------------------------------------
    def add_metadata(self, jpegfiles: list[GeoPointRef]):
        """Schreibt die ermittelten Geokoordinaten und Zeitstempel direkt in die EXIF-Daten der Bilder.
        
        :param jpegfiles: (list[GeoPointRef]) Liste der mit EXIF-Metadaten anzureichernden Bildobjekte.
        """
        if not jpegfiles:
            return

        i = 0
        ii = len(jpegfiles)
        # Setze das Maximum für das Einlesen
        log_to_callback(Tag.PROGRESS, ProgressEvent.start(ii))

        for jpeg in jpegfiles:
            i += 1
            log_to_callback(Tag.PROGRESS, ProgressEvent.update(i, ii))

            # Überspringe JPEGs ohne Koordinaten
            if jpeg.latitude is None or jpeg.longitude is None:
                if self.verbose:
                    log_to_callback(Tag.STATUS, GGPXJpegManager.__name__, f"Überspringe {StringUtils.safe_str(jpeg.filename, "Datei")}: Keine Koordinaten")
                continue  # Nächstes Foto

            # Logging mit Callback
            filename: str = Path(jpeg.filename).name if jpeg.filename is not None else "<unbekannt>"
            lat_str = f"{jpeg.latitude:{GPS_PRINT_FORMAT}}" if jpeg.latitude is not None else "---"
            lon_str = f"{jpeg.longitude:{GPS_PRINT_FORMAT}}" if jpeg.longitude is not None else "---"

            log_to_callback(Tag.STATUS, TRENNER)
            message = f"Foto - Standort {i}/{ii} {filename}: [{StringUtils.safe_str(jpeg.timestamp, "")}]"
            log_to_callback(Tag.STATUS, GGPXJpegManager.__name__, message)
            message = f"mit Zeitdiff [{StringUtils.safe_str(jpeg.diff, "NaN")} sec] und Dist [{StringUtils.safe_str(jpeg.dist, "NaN")} m], Lat {lat_str}, Lon {lon_str}"
            log_to_callback(Tag.STATUS, GGPXJpegManager.__name__, message)

            # nahesten Punkt erzeugen
            nearest_point = None
            if jpeg.latitude is not None and jpeg.longitude is not None:
                nearest_point = GeoPointTime(
                    longitude=jpeg.longitude,
                    latitude=jpeg.latitude,
                    elevation=jpeg.elevation,
                    timestamp=jpeg.timestamp,
                    tz=jpeg.tz
                )

            # Metadaten schreiben
            if jpeg.filename is not None:
                jpg_exif = EExiv2(jpeg.filename, verbose=self.verbose)

                result = jpg_exif.write_exif(
                    creation_date=jpeg.timestamp,
                    creation_author=None,
                    nearest_point=nearest_point,
                    target_tz=jpeg.tz,
                )

                # Logge das Ergebnis (optional)
                if result and result.neighbor:
                    countrycode3 = StringUtils.safe_str(result.neighbor.countrycode3)
                    country = StringUtils.safe_str(result.neighbor.country)
                    state = StringUtils.safe_str(result.neighbor.state)
                    region = StringUtils.safe_str(result.neighbor.region)
                    county = StringUtils.safe_str(result.neighbor.county)
                    city = StringUtils.safe_str(result.neighbor.city)
                    municipality = StringUtils.safe_str(result.neighbor.municipality)

                    log_to_callback(Tag.STATUS, 'Ermittelte Adresse', f'{countrycode3}, {country}, {state}')
                    log_to_callback(Tag.STATUS, '->', f'Region: {region}, Bezirk: {county}')
                    log_to_callback(Tag.STATUS, '->', f'Stadt: {city}, Ort: {municipality}')

        # Ende der for-Schleife - alle Fotos wurden verarbeitet
        if self.verbose:
            log_to_callback(Tag.STATUS, GGPXJpegManager.__name__, f"Verarbeitung von {ii} Fotos abgeschlossen.")

        return
