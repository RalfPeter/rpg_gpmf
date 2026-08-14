#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_gpx.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 883
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : GGPX, GGPXManager
# ------------------------------------------------------------------------------

import glob
from typing import cast
from pathlib import Path
from datetime import timedelta, datetime, tzinfo

import bisect
from math import radians, cos, sin
from scipy.spatial import KDTree
from gpxpy import parse as gpxpy_parse
from gpxpy.gpx import GPX, GPXTrack, GPXTrackPoint, GPXWaypoint, GPXRoutePoint, TimeBounds

from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_utils.utils_filepath import ENCODING_UTF8_SIG
from rpg_utils.utils_datetime import TZ_UTC
from rpg_utils.utils_string import StringUtils as Str
from rpg_gpmf.gpmf_const import SUFFIX_GPX, SUFFIX_VIRBGPX, MAX_TIME_DIFFERENCE_SEC, MAX_EVENT_DISTANCE_METER
from rpg_gpmf.gpmf_geo import get_geolocator_service
from rpg_gpx.gpx_schema import GeoPointTime, GeoPoint, GPXTrackInfo
from rpg_gpx.gpx_io import GPXDataLoader
from rpg_gpx.gpx_utils import haversine

# ===========================================================================================
# Konstanten für GGPXManager
# ===========================================================================================
DEFAULT_MERGED_FILENAME = f"gpx_merged{SUFFIX_GPX}"
GLOB_ALL_GPX = f"*{SUFFIX_GPX}"
MODE_READ = "r"
MODE_WRITE = "w"
PREFIX_POSITION = "position"
TRACK_NAME_SEPARATOR = " - "
NAME_SEPARATOR = " / "


# ===========================================================================================
# GGPX
# ===========================================================================================
class GGPX:
    """Verwaltet das Laden, Parsen, Filtern sowie die hochperformante räumliche."""

    # --------------------------------------------------------------------------------
    def __init__(
        self,
        path: Path,
        diff_time: int = MAX_TIME_DIFFERENCE_SEC,
        diff_dist: int = MAX_EVENT_DISTANCE_METER,
        load_on_init: bool = True,
        verbose: bool = False,
    ) -> None:
        """Initialisiert die GGPX-Instanz mit Konfigurationsparametern und Caches.
        
        :param path: (Path) Pfad zu einer einzelnen GPX-Datei oder einem Verzeichnis.
        :param diff_time: (int) Maximale zeitliche Abweichung in Sekunden für Suchen.
        :param diff_dist: (int) Maximale räumliche Abweichung in Metern für Suchen.
        :param load_on_init: (bool) Steuert, ob Daten direkt beim Erzeugen geladen werden.
        :param verbose: (bool) Aktiviert detaillierte Logging-Ausgaben.
        """
        self.path: Path = path
        self.diff_time = diff_time
        self.diff_dist = diff_dist

        self.verbose: bool = verbose

        # Externe Services & Datenstrukturen
        self.geonames = get_geolocator_service(verbose=verbose)
        self.tracks: dict[Path, list[GPXTrackInfo]] = {}
        self.routes: dict[Path, list[GPXTrackInfo]] = {}
        self.files: list[Path] = []

        # INTERNE OPTIMIERTE SUCHSTRUKTUREN (Kapselung)
        # Interner Zustand zur Vermeidung von redundanten Schleifen (Performance-Schutz)
        self._search_structures_ready: bool = False
        self._flat_tracks: dict[Path, list[GeoPointTime]] = {}
        self._track_trees: dict[Path, KDTree] = {}

        # Instanz-Caches zur Eliminierung redundanter Schleifen/Konvertierungen im Hot-Path
        self._timestamps_cache: dict[int, list[datetime]] = {}

        self._populate_filelist()
        if load_on_init:
            self._load_gpx()

    # --------------------------------------------------------------------------------
    def _populate_filelist(self) -> None:
        """Sucht alle relevanten GPX-Dateien im angegebenen Pfad und füllt die Dateiliste.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        # Absichern, dass es sich um ein echtes Path-Objekt und nicht PurePath handelt
        path_obj = Path(self.path)

        if not path_obj.exists():
            return

        # 1. Fall: Pfad ist eine einzelne Datei
        if path_obj.is_file():
            is_gpx_suffix = path_obj.name.casefold().endswith(SUFFIX_GPX.casefold())
            is_not_excluded = SUFFIX_VIRBGPX not in path_obj.name

            if is_gpx_suffix and is_not_excluded:
                self.files.append(path_obj.resolve())

        # 2. Fall: Pfad ist ein Verzeichnis
        elif path_obj.is_dir():
            gpx_files = list(path_obj.glob(f'*{SUFFIX_GPX.casefold()}'))

            self.files = sorted([
                file.resolve()
                for file in gpx_files
                if SUFFIX_VIRBGPX not in file.name
            ])

    # --------------------------------------------------------------------------------
    def _load_gpx(self) -> None:
        """Lädt und parst die GPX-Dateien und speichert alle Punkte in einem.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        if self.verbose:
            log_to_callback(Tag.STATUS, GGPX.__name__, f"{self.path}: Routen / Tracks werden eingelesen...")

        try:
            for gpx_file in self.files:
                # XML Loader aufrufen
                # Bevorzugung des LxmlGpxStreamer, falls dieser stabiler ist
                # loader = LxmlGpxStreamer(gpx_file, verbose=self.verbose)
                loader = GPXDataLoader(gpx_file, verbose=self.verbose)

                rt = loader.get_tracks()
                if rt:
                    self.tracks[gpx_file] = rt  # Tracks speichern in self.tracks

                rt = loader.get_routes()
                if rt:
                    self.routes[gpx_file] = rt  # Routen speichern in self.routes

                if self.verbose:
                    log_to_callback(Tag.STATUS, GGPX.__name__, f"{gpx_file}: {len(self.tracks.get(gpx_file, []))} Tracks, {len(self.routes.get(gpx_file, []))} Routen eingelesen.")

            if self.verbose:
                anz = len(self.tracks) + len(self.routes)
                log_to_callback(Tag.STATUS, GGPX.__name__, f"Ladevorgang abgeschlossen. {anz} Gesamtpunkte gespeichert.")

        except Exception as e:
            log_to_callback(Tag.ERR, GGPX.__name__, f"Fehler beim Laden von {self.path}: {e}")

    # --------------------------------------------------------------------------------
    def is_empty_gpx(self, gpx: GPX, gpx_name: str = 'GPX-Name') -> bool:
        """Prüft, ob eine geladene GPX-Struktur leer ist oder keine Punkte enthält.
        
        :param gpx: (GPX) Das zu prüfende gpxpy-Objekt.
        :param gpx_name: (str) Der Name der GPX-Datei für Log-Ausgaben.
        :return: (bool) Beschreibung
        """
        if self.verbose:
            log_to_callback(Tag.STATUS, GGPX.__name__, f"{gpx_name}: prüfe auf leere GPX Daten...")

        if not gpx:
            log_to_callback(Tag.STATUS, GGPX.__name__, f"{gpx_name}: die GPX-Datei ist leer.")
            return True

        if not gpx.tracks:
            log_to_callback(Tag.STATUS, GGPX.__name__, f"{gpx_name}: Die GPX-Datei enthält keine Tracks.")
            return True

        return False

    # --------------------------------------------------------------------------------
    def prepare_search_structures(self, force: bool = False) -> None:
        """Bereitet die flachen Listen und KDTrees intern für alle geladenen Dateien vor.
        
        :param force: (bool) Wenn True, wird die Erzeugung erzwungen, selbst wenn sie bereits lief.
        """
        # Wenn bereits berechnet und kein Force-Wechsel vorliegt -> Sofort abbrechen (O(1))
        if self._search_structures_ready and not force:
            return

        if self.verbose:
            log_to_callback(Tag.STATUS, GGPX.__name__, "Suchbäume und flache Tracklisten werden intern generiert...")

        for gpx_file, tracks in self.tracks.items():
            # 1. Abflachen inklusive des räumlichen Zeitzonen-Grid-Caches
            flat_list = self._flatten_list(tracks)
            self._flat_tracks[gpx_file] = flat_list

            # 2. Hocheffizienten KDTree ohne redundante NumPy-Kopien bauen
            tree = self._build_gpx_tree(flat_list)
            if tree:
                self._track_trees[gpx_file] = tree

        # Zustand unumkehrbar auf True setzen – selbst wenn die dicts mangels Daten leer blieben!
        self._search_structures_ready = True

    # --------------------------------------------------------------------------------
    def _flatten_list(self, tracks: list[GPXTrackInfo]) -> list[GeoPointTime]:
        """Macht eine Liste von GPXTrackInfo-Objekten flach zu einer einzelnen Liste von GeoPointTime.

        :param tracks: (list[GPXTrackInfo]) Die Liste der Track-Informationen.
        :return: (list[GeoPointTime]) Flache Liste aller Punkte.
        """
        if not self.geonames:
            # Ultra-schneller Fallback: Wir reichen einfach die Referenzen der bestehenden
            # Objekte als flache Liste durch (List Comprehension läuft in C-Speed).
            return [location for track in tracks for location in track.points]

        # Lokaler Cache zur Vermeidung redundanter Lookups
        # Ein Schlüssel besteht aus (int(lat * 100), int(lon * 100)) -> Auflösung ca. 1.1 km
        tz_spatial_cache: dict[tuple[int, int], tzinfo | None] = {}
        flat_list: list[GeoPointTime] = []

        for track in tracks:
            for location in track.points:
                if location.latitude is None or location.longitude is None:
                    continue

                # Performance-Trick: Integer-Cast nach Multiplikation ist massiv schneller
                # als round(..., 2) und erzeugt ein exakt gleich großes 1.1km-Raster.
                grid_key = (int(location.latitude * 100), int(location.longitude * 100))

                if grid_key in tz_spatial_cache:
                    point_tz = tz_spatial_cache[grid_key]
                else:
                    # Cache-Miss: Wir haben ein neues Planquadrat betreten (oder Grenze überschritten)
                    point_tz = self.geonames.get_tzinfo(
                        latitude=location.latitude,
                        longitude=location.longitude
                    )
                    tz_spatial_cache[grid_key] = point_tz

                # Wir weisen dem BEREITS EXISTIERENDEN Objekt einfach die Zeitzone zu.
                # Keine teure Neu-Instanziierung mehr!
                location.tz = point_tz
                flat_list.append(location)

        return flat_list

    # --------------------------------------------------------------------------------
    @staticmethod
    def _build_gpx_tree_2d(positions: list[GeoPointTime]) -> KDTree | None:
        """Erstellt einen KDTree aus den Positionsdaten für schnelle räumliche Suchen.

        :param positions: (list[GeoPointTime]) Liste der Trackpunkte.
        :return: (KDTree | None) Beschreibung
        """
        if not positions:
            return None

        # Explizite Typ-Anmerkung zwingt den Checker zur korrekten Erkennung
        # cast() zwingt die IDE, das gefilterte Ergebnis als reine Floats zu akzeptieren
        coordinates = cast(
            list[tuple[float, float]],
            [
                (p.latitude, p.longitude)
                for p in positions
                if p.latitude is not None and p.longitude is not None
            ]
        )

        return KDTree(coordinates)

    # --------------------------------------------------------------------------------
    @staticmethod
    def _build_gpx_tree(positions: list[GeoPointTime]) -> KDTree | None:
        """Erstellt einen 3D-KDTree (kartesisch auf der Einheitskugel) für exakte meterbasierte Suchen.
        
        :param positions: (list[GeoPointTime]) Beschreibung von positions.
        :return: (KDTree | None) Beschreibung des Rückgabewerts.
        """

        if not positions:
            return None

        coords_3d: list[tuple[float, float, float]] = []
        for p in positions:
            if p.latitude is not None and p.longitude is not None:
                lat_rad = radians(p.latitude)
                lon_rad = radians(p.longitude)
                x = cos(lat_rad) * cos(lon_rad)
                y = cos(lat_rad) * sin(lon_rad)
                z = sin(lat_rad)
                coords_3d.append((x, y, z))

        return KDTree(coords_3d) if coords_3d else None

    # --------------------------------------------------------------------------------
    def _interpolate_timestamp(self, p1: GeoPointTime, p2: GeoPointTime, target_time: datetime) -> GeoPointTime:
        """Interpoliert mathematisch linear eine Position zwischen zwei Wegpunkten.
        
        :param p1: (GeoPointTime) Startpunkt der Interpolation.
        :param p2: (GeoPointTime) Endpunkt der Interpolation.
        :param target_time: (datetime) Der Zielzeitstempel, auf den berechnet wird.
        :return: (GeoPointTime) Beschreibung
        """
        # 1. Sicherstellen, dass alle benötigten Zeitstempel existieren (Guard Clause)
        if p1.timestamp is None or p2.timestamp is None:
            return p1

        # 2. Type Casting erzwingen
        # Wir sagen dem Checker: "lat1/lon1 sind garantiert floats"
        lat1 = cast(float, p1.latitude)
        lon1 = cast(float, p1.longitude)
        lat2 = cast(float, p2.latitude)
        lon2 = cast(float, p2.longitude)

        # 3. Zeit-Differenz Berechnung: total_seconds() gibt immer einen float zurück
        delta_total = (p2.timestamp - p1.timestamp).total_seconds()
        if delta_total == 0:
            return p1

        fraction = (target_time - p1.timestamp).total_seconds() / delta_total

        # 4. Mathematische Interpolation mit expliziter Typ-Absicherung (Casting auf float)
        lat = lat1 + (lat2 - lat1) * fraction
        lon = lon1 + (lon2 - lon1) * fraction

        # Sicherer Umgang mit Elevation (None-Handling)
        ele1 = p1.elevation if p1.elevation is not None else 0.0
        ele2 = p2.elevation if p2.elevation is not None else 0.0
        ele = ele1 + (ele2 - ele1) * fraction
        # Zeitzone ermitteln: Priorisiere vorhandene Zonen, sonst Geolocator nutzen
        if p1.tz is not None and p1.tz == p2.tz:
            tz = p1.tz
        elif self.geonames is not None:
            tz = self.geonames.get_tzinfo(latitude=lat1, longitude=lon1)
        else:
            tz = None

        return GeoPointTime(
            latitude=float(lat),
            longitude=float(lon),
            elevation=float(ele),
            timestamp=target_time,  # es wurde die Position interpoliert, der timestamp bleibt!
            tz=tz,
        )

    # --------------------------------------------------------------------------------
    @staticmethod
    def _haversine(p1: GeoPoint, p2: GeoPoint) -> float:
        """Berechnet die Großkreisdistanz zwischen zwei Punkten auf einer Kugel.
        
        :param p1: (GeoPoint) Der erste geografische Punkt.
        :param p2: (GeoPoint) Der zweite geografische Punkt.
        :return: (float) Beschreibung
        """
        lat1 = cast(float, p1.latitude)
        lon1 = cast(float, p1.longitude)
        lat2 = cast(float, p2.latitude)
        lon2 = cast(float, p2.longitude)

        return haversine(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)

    # --------------------------------------------------------------------------------
    def find_nearest_by_timestamp(self, gpx_file: Path, target_time: datetime) -> tuple[GeoPointTime, int, int] | None:
        """Sucht den zeitlich nächsten Trackpunkt mittels schneller Binärsuche (O(log N)).
        
        :param gpx_file: (Path) Der Pfad der zu durchsuchenden GPX-Datei.
        :param target_time: (datetime) Der gesuchte Ziel-Zeitstempel (naive oder aware).
        :return: (tuple[GeoPointTime, int, int] | None) Beschreibung
        """
        # Automatischer Schutz: Holt die Erzeugung nach, falls noch nicht geschehen
        self.prepare_search_structures()

        # Holen der intern gekapselten Strukturen
        gpx_positions = self._flat_tracks.get(gpx_file, [])
        if not gpx_positions:
            return None

        if self.verbose:
            log_to_callback(Tag.STATUS, GGPX.__name__, f"Suche nahesten Punkt zu {target_time} mit binärer Suche...")

        # 1. ID-basiertes Caching der reinen UTC-Zeitstempel (Macht Folgesuchen extrem schnell)
        list_id = id(gpx_positions)
        if list_id not in self._timestamps_cache:
            extracted_timestamps: list[datetime] = []
            for p in gpx_positions:
                if p.timestamp is None:
                    continue
                extracted_timestamps.append(
                    p.timestamp.replace(tzinfo=TZ_UTC)
                    if p.timestamp.tzinfo is None
                    else p.timestamp.astimezone(TZ_UTC)
                )
            self._timestamps_cache[list_id] = extracted_timestamps

        timestamps_ref = self._timestamps_cache[list_id]
        if not timestamps_ref:
            return None

        # 2. Anpassung der Suchanfrage (target_time) an die UTC-Welt
        target_time_utc = (
            target_time.replace(tzinfo=TZ_UTC)
            if target_time.tzinfo is None
            else target_time.astimezone(TZ_UTC)
        )

        # 3. Vorab-Prüfung der Grenzwerte (Fail-Fast)
        max_diff_td = timedelta(seconds=self.diff_time)
        if (target_time_utc + max_diff_td) < timestamps_ref[0] or (
            target_time_utc - max_diff_td
        ) > timestamps_ref[-1]:
            return None

        # 4. Binäre Suche (bisect)
        index = bisect.bisect_left(timestamps_ref, target_time_utc)
        anz = len(timestamps_ref)

        idx_next = index
        idx_prev = index - 1

        nearest: GeoPointTime | None = None
        diff = float("inf")
        nearest_index = -1

        if idx_prev >= 0:
            diff_prev = abs(
                (target_time_utc - timestamps_ref[idx_prev]).total_seconds()
            )
            if diff_prev < diff:
                diff = diff_prev
                nearest = gpx_positions[idx_prev]
                nearest_index = idx_prev

        if idx_next < anz:
            diff_next = abs(
                (target_time_utc - timestamps_ref[idx_next]).total_seconds()
            )
            if diff_next < diff:
                diff = diff_next
                nearest = gpx_positions[idx_next]
                nearest_index = idx_next

        if nearest is None or diff > self.diff_time:
            return None

        if diff == 0:
            return nearest, int(diff), nearest_index

        # 5. Lineare Interpolation (Aufruf mit bereinigten UTC-Werten)
        interpolated_position = nearest
        if nearest_index == 0 and anz > 1:
            interpolated_position = self._interpolate_timestamp(
                nearest, gpx_positions[1], target_time_utc
            )
        elif 0 < nearest_index < anz - 1:
            if target_time_utc < timestamps_ref[nearest_index]:
                interpolated_position = self._interpolate_timestamp(
                    gpx_positions[nearest_index - 1], nearest, target_time_utc
                )
            else:
                interpolated_position = self._interpolate_timestamp(
                    nearest, gpx_positions[nearest_index + 1], target_time_utc
                )
        elif nearest_index == anz - 1 and anz > 1:
            interpolated_position = self._interpolate_timestamp(
                gpx_positions[nearest_index - 1], nearest, target_time_utc
            )

        return interpolated_position, int(diff), nearest_index

    # --------------------------------------------------------------------------------
    def find_nearest_by_position(self, gpx_file: Path, target_point: GeoPoint) -> tuple[GeoPointTime, int, int] | None:
        """Sucht den räumlich nächsten Wegpunkt basierend auf Koordinaten via KDTree.
        
        :param gpx_file: (Path) Die Liste der Trackpunkte.
        :param target_point: (GeoPoint) Der Zielpunkt, nach dem gesucht wird.
        :return: (tuple[GeoPointTime, int, int] | None) Beschreibung
        """
        # Schutz vor ungültigen Suchanfragen (Early Exit bei fehlenden Koordinaten)
        if target_point.latitude is None or target_point.longitude is None:
            return None

        # Automatischer Schutz: Holt die Erzeugung nach, falls noch nicht geschehen
        self.prepare_search_structures()

        # Holen der intern gekapselten Strukturen
        # Holen der intern gekapselten Strukturen
        gpx_positions = self._flat_tracks.get(gpx_file, [])
        gpx_tree = self._track_trees.get(gpx_file)

        if not gpx_positions or gpx_tree is None:
            return None

        # KDTree Abfrage liefert direkt den exakt nächsten euklidischen Nachbarn
        _, raw_index = gpx_tree.query((target_point.latitude, target_point.longitude), k=1)
        index = int(raw_index)
        nearest = gpx_positions[index]

        dist_meter = int(abs(self._haversine(GeoPoint(latitude=nearest.latitude, longitude=nearest.longitude), target_point)))
        if dist_meter > self.diff_dist:
            return None

        return nearest, dist_meter, index


# ===========================================================================================
# GGPXManager
# ===========================================================================================
class GGPXManager:
    """Verwaltet Operationen, die über eine Liste von GPX-Dateien oder ein Verzeichnis ausgeführt werden."""

    # ---------------------------------------------------------------------------------------
    def __init__(
        self,
        path: Path,
        diff_time: int = MAX_TIME_DIFFERENCE_SEC,
        diff_dist: int = MAX_EVENT_DISTANCE_METER,
        load_on_init: bool = True,
        verbose: bool = False,
    ) -> None:
        """Initialisiert den Manager mit einer GGpx-Engine für die Durchführung von Einzel-Datei-Operationen.
        
        :param path: (Path) Der Basis-Pfad für die GPX-Dateien oder das Verzeichnis.
        :param diff_time: (int) Die maximale Zeitdifferenz für Filterungen/Berechnungen.
        :param diff_dist: (int) Die maximale Distanzdifferenz für Filterungen/Berechnungen.
        :param load_on_init: (bool) Bestimmt, ob die Daten direkt bei der Initialisierung geladen werden sollen.
        :param verbose: (bool) Wenn True, werden detaillierte Protokolle ausgegeben.
        """
        self.classname = self.__class__.__name__
        self.verbose: bool = verbose
        self.geonames = get_geolocator_service(verbose=verbose)
        self.gpx_engine: GGPX = GGPX(
            path=path,
            diff_time=diff_time,
            diff_dist=diff_dist,
            load_on_init=load_on_init,
            verbose=verbose,
        )

    # ---------------------------------------------------------------------------------------
    def _parse_gpx_file(self, file_path: Path) -> GPX | None:
        """Hilfsfunktion zum sicheren Parsen einer GPX-Datei.
        
        :param file_path: (Path) Der Pfad zur GPX-Datei.
        :return: (GPX | None) Beschreibung
        """
        try:
            with open(
                file_path, mode=MODE_READ, encoding=ENCODING_UTF8_SIG
            ) as f:
                return gpxpy_parse(f)
        except Exception as e:
            log_to_callback(Tag.STATUS, self.classname, f"Fehler beim Lesen der Datei {file_path.name}: {e}")
            return None

    # ---------------------------------------------------------------------------------------
    def _write_gpx_file(self, file_path: Path, gpx: GPX) -> bool:
        """Hilfsfunktion zum sicheren Schreiben eines GPX-Objekts in eine Datei.
        
        :param file_path: (Path) Der Zielpfad der GPX-Datei.
        :param gpx: (GPX) Das zu schreibende GPX-Objekt.
        :return: (bool) Beschreibung
        """
        try:
            with open(
                file_path, mode=MODE_WRITE, encoding=ENCODING_UTF8_SIG
            ) as f:
                f.write(gpx.to_xml())
            return True
        except Exception as e:
            log_to_callback(Tag.STATUS, self.classname, f"Fehler beim Schreiben der Datei {file_path.name}: {e}")
            return False

    # ---------------------------------------------------------------------------------------
    def add_description_to_gpxfiles(self) -> None:
        """Fügt allen GPS-Punkten in einer Liste von GPX-Dateien Beschreibungen und Höhenmeter hinzu und speichert die Datei zurück.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        for gpx_file in self.gpx_engine.files:
            gpx_file_path = Path(gpx_file).resolve()

            log_to_callback(Tag.STATUS, self.classname, f"Datei {gpx_file_path.name} wird bearbeitet.")
            gpx = self._parse_gpx_file(gpx_file_path)

            if not gpx:
                continue

            if self._add_description_to_gpx(gpx):
                self._write_gpx_file(gpx_file_path, gpx)

    # ---------------------------------------------------------------------------------------
    def _add_description_to_gpx(self, gpx: GPX) -> bool:
        """Fügt Namen und Höheninformationen zu GPS-Punkten in einem GPX-Objekt hinzu.
        
        :param gpx: (GPX) Das GPX-Objekt, das ergänzt werden soll.
        :return: (bool) Beschreibung
        """
        if not gpx:
            return False

        for track in gpx.tracks:
            for segment in track.segments:
                log_to_callback(Tag.STATUS, self.classname, f"Bearbeite {len(segment.points)} Trackpunkte von {Str.safe_str(track.name)}...")
                for point in segment.points:
                    self._set_info_for_point(point)

        if gpx.waypoints:
            log_to_callback(Tag.STATUS, self.classname, f"Bearbeite {len(gpx.waypoints)} Waypoints...")
            for waypoint in gpx.waypoints:
                self._set_info_for_point(waypoint)

        for route in gpx.routes:
            log_to_callback(Tag.STATUS, self.classname, f"Bearbeite {len(route.points)} Routenpunkte...")
            for point in route.points:
                self._set_info_for_point(point)

        return True

    # ---------------------------------------------------------------------------------------
    def _set_info_for_point(
        self, gpspoint: GPXTrackPoint | GPXWaypoint | GPXRoutePoint
    ) -> bool:
        """Setzt Namen und Höheninformationen für einen GPS-Punkt (mittels Geonames-Service).
        
        :param gpspoint: (GPXTrackPoint | GPXWaypoint | GPXRoutePoint) Der zu aktualisierende Punkt.
        :return: (bool) Beschreibung
        """
        if (
            gpspoint.name
            and not gpspoint.name.lower().startswith(PREFIX_POSITION)
            and gpspoint.elevation
            and gpspoint.description
        ):
            return False

        gi = None
        if self.geonames:
            gi = self.geonames.get_geonames_information(
                gpspoint.latitude, gpspoint.longitude
            )

        name: str | None = None
        elevation: float | None = None

        if gi and hasattr(gi, "neighbor") and gi.neighbor:
            neighbor = gi.neighbor
            parts = [neighbor.city, neighbor.municipality]
            name = NAME_SEPARATOR.join(str(p) for p in parts if p)
            elevation = neighbor.elevation

        if name:
            gpspoint.name = name
            gpspoint.description = (
                None if gpspoint.description == name else gpspoint.description
            )

        if elevation is not None:
            if gpspoint.elevation is None or gpspoint.elevation == 0.0:
                gpspoint.elevation = elevation

        return True

    # ---------------------------------------------------------------------------------------
    def _prepare_merge(
        self,
        gpx_path: Path,
        gpx_pattern: str | None = None,
        output: Path | None = None,
    ) -> tuple[list[str], str] | None:
        """Interne Hilfsfunktion zur Vorbereitung der Dateiliste für die Zusammenführung.
        
        :param gpx_path: (Path) Das Verzeichnis oder die Datei, in dem/der gesucht werden soll.
        :param gpx_pattern: (str | None) Glob-Muster zur Filterung der GPX-Dateien.
        :param output: (Path | None) Optionaler Pfad für die Ausgabedatei.
        :return: (tuple[list[str], str] | None) Beschreibung
        """
        if self.verbose:
            log_to_callback(Tag.STATUS, self.classname, f"Alle GPX in {gpx_path} werden zusammengeführt...")

        output_path = (
            output.resolve()
            if output
            else gpx_path.joinpath(DEFAULT_MERGED_FILENAME).resolve()
        )

        if gpx_path and gpx_pattern:
            gpx_files = glob.glob(str(gpx_path.joinpath(gpx_pattern)))
        elif gpx_path.is_dir():
            gpx_files = glob.glob(str(gpx_path.joinpath(GLOB_ALL_GPX)))
        else:
            gpx_files = glob.glob(str(gpx_path))

        return gpx_files, str(output_path)

    # ---------------------------------------------------------------------------------------
    def merge_gpx_files(
        self,
        gpx_path: Path,
        gpx_pattern: str | list[str],
        output: Path | None = None,
    ) -> bool:
        """Führt alle Tracks aus den GPX-Dateien, die einem Muster entsprechen, in einer neuen Datei zusammen.
        
        :param gpx_path: (Path) Das Verzeichnis, in dem die GPX-Dateien gesucht werden.
        :param gpx_pattern: (str | list[str]) Glob-Muster oder explizite Liste von Dateipfaden.
        :param output: (Path | None) Optionaler Pfad für die Ausgabedatei.
        :return: (bool) Beschreibung
        """
        if not gpx_pattern or not gpx_path:
            return False

        if isinstance(gpx_pattern, list):
            gpx_files = gpx_pattern
            output = gpx_path.joinpath(DEFAULT_MERGED_FILENAME).resolve()
        else:
            result = self._prepare_merge(gpx_path, gpx_pattern, output)
            if not result:
                return False
            gpx_files, output_path_str = result
            output = Path(output_path_str)

        if not gpx_files:
            return False

        gpx_new = GPX()
        output_name = output.stem

        for gpx_file in gpx_files:
            gpx_file_path = Path(gpx_file).resolve()
            if gpx_file_path.stem == output_name:
                continue

            gpx = self._parse_gpx_file(gpx_file_path)
            if not gpx or self.gpx_engine.is_empty_gpx(
                gpx, gpx_file_path.name
            ):
                continue

            for track in gpx.tracks:
                gpx_new.tracks.append(track)

        return self._write_gpx_file(output, gpx_new)

    # ---------------------------------------------------------------------------------------
    def merge_overlapping_gpx_files(
        self, gpx_path: Path, output: Path | None = None
    ) -> None:
        """Führt Tracks zusammen und versucht, sich überlappende Tracks nach Zeitstempel des letzten Punktes zu verbinden.
        
        :param gpx_path: (Path) Das Verzeichnis, in dem die GPX-Dateien gesucht werden.
        :param output: (Path | None) Optionaler Pfad für die Ausgabedatei.
        """
        result = self._prepare_merge(gpx_path=gpx_path, output=output)
        if not result:
            return
        gpx_files, output_path_str = result
        output = Path(output_path_str)
        output_name = output.stem

        gpx_new = GPX()
        track_dict: dict[str, GPXTrack] = {}

        for gpx_file in gpx_files:
            gpx_file_path = Path(gpx_file).resolve()
            gpx_name = gpx_file_path.stem

            if gpx_name == output_name:
                continue

            gpx = self._parse_gpx_file(gpx_file_path)
            if not gpx or self.gpx_engine.is_empty_gpx(
                gpx, gpx_file_path.name
            ):
                continue

            for i, track in enumerate(gpx.tracks, 1):
                if not track.segments:
                    continue

                track_name = f"{gpx_name}{TRACK_NAME_SEPARATOR}{i}"
                if track_name not in track_dict:
                    track.name = track_name
                    track_dict[track_name] = track
                else:
                    existing_track = track_dict[track_name]

                    if not existing_track.segments:
                        existing_track.segments = track.segments
                        continue

                    existing_segment = existing_track.segments[0]
                    new_segment = track.segments[0]

                    if not existing_segment.points or not new_segment.points:
                        continue

                    last_point = existing_segment.points[-1]
                    first_point = new_segment.points[0]

                    if last_point.time == first_point.time:
                        existing_segment.points.extend(new_segment.points[1:])
                    else:
                        existing_segment.points.extend(new_segment.points)

                    existing_track.segments.extend(track.segments[1:])

        gpx_new.tracks = list(track_dict.values())
        self._write_gpx_file(output, gpx_new)

    # ---------------------------------------------------------------------------------------
    def merge_overlapping_gpx_files_2(
        self, gpx_path: Path, output: Path | None = None
    ) -> None:
        """Führt Tracks zusammen, die sich nicht zeitlich überschneiden (Segment-Bounds-Prüfung).
        
        :param gpx_path: (Path) Das Verzeichnis, in dem die GPX-Dateien gesucht werden.
        :param output: (Path | None) Optionaler Pfad für die Ausgabedatei.
        """

        # --------------------------------------------------------------------------------
        def time_bounds_overlap(
            bounds1: TimeBounds, bounds2: TimeBounds
        ) -> bool:
            """Prüft, ob sich zwei Zeitintervalle überschneiden.

            :param bounds1: (TimeBounds) Das erste Zeitintervall.
            :param bounds2: (TimeBounds) Das zweite Zeitintervall.
            :return: (bool) True, wenn sich die Intervalle überschneiden, sonst False.
            """
            start1, end1 = bounds1
            start2, end2 = bounds2

            if (
                start1 is None
                or end1 is None
                or start2 is None
                or end2 is None
            ):
                return False

            latest_start: datetime = max(start1, start2)
            earliest_end: datetime = min(end1, end2)
            return latest_start < earliest_end

        result = self._prepare_merge(gpx_path=gpx_path, output=output)
        if not result:
            return
        gpx_files, output_path_str = result
        output = Path(output_path_str)
        output_name = output.stem

        gpx_new = GPX()
        for gpx_file in gpx_files:
            gpx_file_path = Path(gpx_file).resolve()

            if gpx_file_path.stem == output_name:
                continue

            gpx = self._parse_gpx_file(gpx_file_path)
            if not gpx or self.gpx_engine.is_empty_gpx(
                gpx, gpx_file_path.name
            ):
                continue

            for track in gpx.tracks:
                merge_required = True

                for merged_track in gpx_new.tracks:
                    for segment in track.segments:
                        segment_bounds = segment.get_time_bounds()
                        if not segment_bounds:
                            continue

                        for merged_segment in merged_track.segments:
                            merged_segment_bounds = (
                                merged_segment.get_time_bounds()
                            )
                            if merged_segment_bounds and time_bounds_overlap(
                                segment_bounds, merged_segment_bounds
                            ):
                                merge_required = False
                                break
                        if not merge_required:
                            break
                    if not merge_required:
                        break

                if merge_required:
                    gpx_new.tracks.append(track)

        self._write_gpx_file(output, gpx_new)
