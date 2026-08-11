#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_geo.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 1572
#  Abhängigkeiten    : abc, cProfile, dataclasses, datetime, overpy, pathlib, pstats, scipy, threading, time, typing
#                     zoneinfo
#  Klassen           : BaseGeoDB (ABC), BaseGeoNamesDB (ABC), GeoNamesDB, GeoAlternatenamesDB, GeoCitiesDB
#                     GeoCountriesDB, CountryResolver, GeoLocator, Elevation, GeoOSM
# ------------------------------------------------------------------------------
#  Public Methoden:
#    BaseGeoDB                                            → Abstrakte Basisklasse für geografische Datenbanken.
#      data()                                             → Gibt die geladenen Rohdaten der Geo-Datenbank zurück.
#      data_count()                                       → Gibt die Gesamtanzahl der Einträge zurück.
#      sources()                                          → Gibt die Liste der aktuell registrierten Quelldateien (ZIP-Name, Zielpfad) zurück.
#      idlookup()                                         → Gibt das GeonameID-zu-Namen Lookup-Dictionary zurück.
#      countries()                                        → Gibt die geladenen Ländercodes (ISO-2) zurück.
#      search(float, float, int, str, bool, str)          → Universelle KDTree-Suche für alle Geo-Datenbanken mit dynamischer Sprachauflösung.
#      get_elevation(float, float)                        → Universelle KDTree-Suche für die Geländehöhe (DEM).
#      get_tzinfo(float, float)                           → Ermittelt die IANA-Zeitzone für gegebene Koordinaten.
#
#    BaseGeoNamesDB                                       → Verwaltet die GeoNames-Datenbasis mit instanzbasiertem Daten-Lifecycle.
#      ensure_country_loaded(str)                         → Stellt sicher, dass ein Land in der Laufzeit-Struktur vorhanden ist.
#      add_country(str)                                   → Lädt ein einzelnes Land dynamisch nach und merget es mit den bestehenden Instanzdaten.
#
#    GeoCitiesDB                                          → Verwaltet die GeoCities-Datenbasis.
#      alpha2_from_coords(float, float)                   → Ermittelt den Alpha-2 Code direkt über den KDTree der Städte-DB.
#
#    GeoCountriesDB                                       → Verwaltet die GeoCountries-Datenbasis.
#      resolvermap()                                      → Gibt die vorbereitete Resolver-Map für den schnellen Zugriff zurück.
#
#    CountryResolver                                      → Ermittelt Länderinformationen über entkoppelte Lazy-Properties der Service-Instanzen.
#      iso3_and_name(str, str)                            → Gibt ISO3 und lokalisierten Namen zurück. Priorisiert die gewählte Sprache.
#      alpha2_from_coords(float, float)                   → Ermittelt den Alpha-2 Code aus Koordinaten via GeoCitiesDB.
#      get_tzinfo(float, float)                           → Ermittelt die IANA-Zeitzone für gegebene Koordinaten über GeoCitiesDB.
#      get_elevation(float, float)                        → Universelle KDTree-Suche für die Geländehöhe (DEM).
#
#    GeoLocator                                           → Ermittelt vollständige Adressdaten für Koordinaten auf Instanz-Ebene.
#      get_geonames_information(float, float)             → Gecachte Standortermittlung.
#      get_tzinfo(float, float)                           → Ermittelt die IANA-Zeitzone für gegebene Koordinaten.
#      get_elevation(float, float)                        → Universelle KDTree-Suche für die Geländehöhe (DEM).
#
#    Elevation                                            → Höhenabfrage für GPS-Punkte.
#      get_elevation(GeoPoint)                            → Ruft die geografische Höhe für einen GPS-Punkt ab.
#
#    GeoOSM                                               → Straßensuche via OSM Overpass API.
#      search(float, float, float)                        → Sucht Straßen in einem Radius um gegebene Koordinaten.
# ------------------------------------------------------------------------------
#  Globale Funktionen:
#    initialize_all_geo_services(bool, bool, 
#                                Profile)                 → Initialisiert alle geografischen Singleton-Dienste in der korrekten strukturellen Stufen-Reihenfolge.
#    get_geolocator_service(bool, bool)                   → Singleton-Getter für GeoLocator. Berücksichtigt DEFAULT_GEOLOCATOR_USE.
#    get_geonames_service(list[FilePath], 
#                         list[str], bool, bool)          → Singleton-Getter für GeoNamesDB. Berücksichtigt DEFAULT_GEONAMES_USE.
#    get_geoalternatenames_service(list[FilePath], 
#                                  list[str], bool, bool) → Singleton-Getter für GeoAlternatenamesDB mit automatischer Quell-Synchronisation.
#    get_geocities_service(list[FilePath], 
#                          list[str], bool, bool)         → Singleton-Getter für GeoCitiesDB. Berücksichtigt DEFAULT_GEOCITIES_USE.
#    get_geocountries_service(bool, bool)                 → Singleton-Getter für GeoCountriesDB. Berücksichtigt DEFAULT_GEONAMES_USE.
#    get_countryresolver_service(bool, bool)              → Singleton-Getter für CountryResolver. Berücksichtigt DEFAULT_GEONAMES_USE.
#    get_elevation_service(bool)                          → Singleton-Getter für den zentralen Höhen-Dienst (Elevation).
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

from __future__ import annotations
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import tzinfo
import time
from typing import TypeVar, Generic, Any, Final, ClassVar, Callable
from dataclasses import replace
from zoneinfo import ZoneInfo
from cProfile import Profile
import pstats

from overpy import Overpass, Result
from scipy.spatial import KDTree

from rpg_gpmf.gpmf_const import DEFAULT_RESULT
from rpg_geo.geo_const import FilePath, GEONAMES_FEATURE, GEONAMES_DEFAULT, GEOCITIES_FEATURE, GEOCITIES_DEFAULT, GEOALTERNATENAMES_FEATURE, GEOALTERNATENAMES_DEFAULT
from rpg_geo.geo_datamanager import BaseGeoNamesDataManager, GeoAltNamesDataManager, GeoNamesDataManager, GeoCitiesDataManager, GeoCountriesDataManager
from rpg_geo.geo_basemanager import (GEONAMES_DATA_KEY, GEONAMES_TREE_KEY, GEONAMES_COUNTRIES_KEY, GEONAMES_LANGUAGES_KEY,
                                     GEONAMES_IDLOOKUP_KEY, GEONAMES_RESOLVER_KEY, GEONAMES_SOURCES_KEY)
from rpg_geo.geo_fields import (FIELDFeatureClass, FIELDFeatureCode, FIELDName, FIELDCountryCode2, FIELDLatitude, FIELDLongitude, FIELDGeonameID, FIELDDigitalElevationModel,
                                FIELDAdmin1Code, FIELDAdmin2Code, FIELDAdmin3Code, FIELDAdmin4Code, FIELDTimezone, FIELDPopulation, FIELDHaversine,
                                FIELDISOLANGUAGE, FIELDISO3, FIELDCOUNTRY)
from rpg_gpx.gpx_schema import GeoPoint
from rpg_gpmf.gpmf_geo_schema import GeoInfo, GeoNeighbor
from rpg_gpx.gpx_utils import haversine
from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_utils.utils_http import HttpUtils
from rpg_utils.utils_math import MathUtils
from rpg_utils.utils_string import StringUtils as Str

# -------------------------------------------------------------------------------------------
# HINWEIS: die Singletonverwaltung befindet sich in den Klassen selbst!
# -------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------
# Konstanten
# -------------------------------------------------------------------------------------------
GEO_CACHE_PRECISION: Final[int] = 3
ELEVATION_QUERY_OE_URL: Final[str] = "https://api.open-elevation.com/api/v1/lookup?locations={},{}"
ELEVATION_QUERY_OT_URL: Final[str] = "https://api.opentopodata.org/v1/ned10m?locations={},{}"
ELEVATION_TIMEOUT_SEC: Final[int] = 20
ELEVATION_DELAY_SEC: Final[float] = 1.0

# Defaults
DEFAULT_GEONAMES_USE: bool = True
DEFAULT_GEONAMES_FEATURE: Final[list[str]] = GEONAMES_FEATURE
DEFAULT_GEONAMES_FILES: FilePath | list[FilePath] = GEONAMES_DEFAULT
DEFAULT_GEOALTERNATENAMES_FEATURE: Final[list[str]] = GEOALTERNATENAMES_FEATURE
DEFAULT_GEOALTERNATENAMES_FILES: FilePath | list[FilePath] = GEOALTERNATENAMES_DEFAULT
DEFAULT_GEOCITIES_FEATURE: Final[list[str]] = GEOCITIES_FEATURE
DEFAULT_GEOCITIES_FILES: FilePath | list[FilePath] = GEOCITIES_DEFAULT
DEFAULT_GEOCITIES_USE: bool = DEFAULT_GEONAMES_USE
DEFAULT_GEOLOCATOR_FEATURE: Final[list[str]] = GEONAMES_FEATURE
DEFAULT_GEOLOCATOR_FILES: FilePath | list[FilePath] = GEOCITIES_DEFAULT
DEFAULT_GEOLOCATOR_USE: bool = DEFAULT_GEOCITIES_USE
DEFAULT_SORT_FIELD: Final[str] = FIELDHaversine

T = TypeVar("T", bound=dict[str, Any])


# ================================================================================
# Basis-Klasse mit nativem __new__ Singleton Pattern
# ================================================================================
class BaseGeoDB(ABC, Generic[T]):
    """Abstrakte Basisklasse für geografische Datenbanken."""

    _instance: ClassVar[Any] = None

    # Globaler Thread-Lock-Pool für alle Unterklassen
    _lock_pool: ClassVar[dict[type, threading.Lock]] = {}

    # --------------------------------------------------------------------------------
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        """Garantiert, dass pro konkreter Unterklasse nur eine Instanz existiert.
        
        :return: (Any) Beschreibung des Rückgabewerts.
        """

        # Nativer Klassenbezeichner als Key für den Thread-Lock holen/erstellen
        if cls not in cls._lock_pool:
            cls._lock_pool.setdefault(cls, threading.Lock())

        # Double-Checked Locking-Pattern
        if cls._instance is None:
            with cls._lock_pool[cls]:
                if cls._instance is None:
                    instance = object.__new__(cls)
                    instance._init_singleton()
                    instance._needs_loading = True
                    cls._instance = instance
                    return instance

        # Wenn Instanz existiert, verhindern wir das erneute Laden im __init__
        cls._instance._needs_loading = False
        return cls._instance

    # --------------------------------------------------------------------------------
    def _init_singleton(self) -> None:
        """Initialisiert die Instanzvariablen isoliert im RAM.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        self.classname: str = self.__class__.__name__
        self._verbose: bool = False
        self.data_directory: Path | None = None
        self._offline_mode: bool = False
        self._needs_loading: bool = True

        self._data: list[dict[str, Any]] = []
        self._sources: list[Any] = []
        self._countries: set[str] = set()
        self._kdtree: KDTree | None = None
        self._idlookup: dict[int, dict[str, str]] = {}
        self._adm_map: dict[str, tuple[int, str]] = {}

    # --------------------------------------------------------------------------------
    def _populate_instance_variables(self, data: dict[str, Any], verbose: bool = False) -> None:
        """Befüllt die Instanzvariablen des Singletons dynamisch aus dem Cache-Dictionary.
        
        :param data: (dict[str, Any]) Das vom DataManager gelieferte Rohdaten-Dictionary.
        :param verbose: (bool) Wenn True, werden Konfigurationsdetails protokolliert.
        """
        if not data:
            return

        KEY_TO_VAR_MAP: dict[str, str] = {
            GEONAMES_DATA_KEY: f"_{GEONAMES_DATA_KEY}",
            GEONAMES_TREE_KEY: f"_{GEONAMES_TREE_KEY}",
            GEONAMES_COUNTRIES_KEY: f"_{GEONAMES_COUNTRIES_KEY}",
            GEONAMES_LANGUAGES_KEY: f"_{GEONAMES_LANGUAGES_KEY}",
            GEONAMES_SOURCES_KEY: f"_{GEONAMES_SOURCES_KEY}",
            GEONAMES_IDLOOKUP_KEY: f"_{GEONAMES_IDLOOKUP_KEY}",
            GEONAMES_RESOLVER_KEY: f"_{GEONAMES_RESOLVER_KEY}",
        }

        self._kdtree = None

        for pickle_key, target_var in KEY_TO_VAR_MAP.items():
            if pickle_key in data:
                if not hasattr(self, target_var):
                    continue

                raw_value = data[pickle_key]
                current_instance_var = getattr(self, target_var, None)

                if isinstance(current_instance_var, set) and isinstance(raw_value, list):
                    final_value = set(raw_value)
                else:
                    final_value = raw_value

                setattr(self, target_var, final_value)

                if verbose or self._verbose:
                    type_info = "als set" if isinstance(final_value, set) else "direkt"
                    log_to_callback(Tag.STATUS, self.classname, f"Bereich '{pickle_key}' erfolgreich {type_info} in '{target_var}' geladen.")

    # --------------------------------------------------------------------------------
    @property
    def data(self) -> list[dict[str, Any]]:
        """Gibt die geladenen Rohdaten der Geo-Datenbank zurück.
        
        :return: (list[dict[str, Any]]) Beschreibung des Rückgabewerts.
        """

        return self._data

    # --------------------------------------------------------------------------------
    @property
    def data_count(self) -> int:
        """Gibt die Gesamtanzahl der Einträge zurück.
        
        :return: (int) Beschreibung des Rückgabewerts.
        """

        return len(self._data)

    # --------------------------------------------------------------------------------
    @property
    def sources(self) -> list[FilePath]:
        """Gibt die Liste der aktuell registrierten Quelldateien (ZIP-Name, Zielpfad) zurück.
        
        :return: (list[FilePath]) Beschreibung des Rückgabewerts.
        """

        return self._sources

    # --------------------------------------------------------------------------------
    @property
    def idlookup(self) -> dict[int, dict[str, str]]:
        """Gibt das GeonameID-zu-Namen Lookup-Dictionary zurück.
        
        :return: (dict[int, dict[str, str]]) Beschreibung des Rückgabewerts.
        """

        return self._idlookup

    # --------------------------------------------------------------------------------
    @property
    def countries(self) -> set[str]:
        """Gibt die geladenen Ländercodes (ISO-2) zurück.
        
        :return: (set[str]) Beschreibung des Rückgabewerts.
        """

        return self._countries

    # --------------------------------------------------------------------------------
    def _build_adm_index(self, data_list: list[dict[str, Any]]) -> None:
        """Baut den administrativen Index (ADM1-ADM4) auf.
        
        :param data_list: (list[dict[str, Any]]) Die Liste der Rohdaten-Datensätze.
        """
        if not data_list:
            return

        FEATURE_CLASS_ADMIN: str = "A"
        FEATURE_PREFIX_ADM: str = "ADM"
        ADMIN_FIELDS: tuple[str, str, str, str] = (
            FIELDAdmin1Code, FIELDAdmin2Code, FIELDAdmin3Code, FIELDAdmin4Code
        )

        # --------------------------------------------------------------------------------
        def _get_adm_priority(l_row: dict[str, Any]) -> int:
            """Kurzbeschreibung für _get_adm_priority.
            
            :param l_row: (dict[str, Any]) Beschreibung von l_row.
            :return: (int) Beschreibung des Rückgabewerts.
            """

            fcode = str(l_row.get(FIELDFeatureCode, ""))
            if fcode.startswith(FEATURE_PREFIX_ADM):
                level_str = fcode[3:]
                if level_str in ("1", "2", "3", "4"):
                    return int(level_str)
            return 9

        sorted_data = sorted(
            [r for r in data_list if str(r.get(FIELDFeatureClass, "")) == FEATURE_CLASS_ADMIN],
            key=_get_adm_priority
        )

        for row in sorted_data:
            f_code = str(row.get(FIELDFeatureCode, ""))

            if not (f_code.startswith(FEATURE_PREFIX_ADM) and f_code[3:] in ("1", "2", "3", "4")):
                continue

            try:
                level = int(f_code[3:])
                cc = str(row.get(FIELDCountryCode2, "")).upper()

                raw_codes = [str(row.get(ADMIN_FIELDS[i], "")) for i in range(level)]
                codes = [c.replace(".0", "").strip() for c in raw_codes if c and c != "None"]

                if len(codes) != level:
                    continue

                geoname_id = MathUtils.safe_int(row.get(FIELDGeonameID))
                name_val = str(row.get(FIELDName, "")).strip()

                if geoname_id is None or not name_val:
                    continue

                for active_level in range(1, level + 1):
                    sub_codes = codes[:active_level]
                    key = ".".join([cc] + sub_codes)

                    if active_level == level or key not in self._adm_map:
                        self._adm_map[key] = (geoname_id, name_val)

            except (ValueError, KeyError, IndexError):
                continue

    # --------------------------------------------------------------------------------
    @staticmethod
    def _normalize_cities(names: list[str | None]) -> list[str | None]:
        """Normalisiert Stadt- und Gemeinde-Namen weltweit durch relative Hierarchie-Befüllung.

        Füllt das 'city'-Feld bei strukturellen Lücken auf, ohne bestehende
        Verwaltungsebenen (Region, County) zu überschreiben oder zu löschen.

        :param names: (list[str | None]) [State, Region, County, City, Municipality]
        :return: (list[str | None]) Die bereinigte und vervollständigte Namensliste
        """
        # 1. Kompakte und absolut linter-sichere Inline-Bereinigung
        state: str | None = n.strip() if (n := names[0]) else None
        region: str | None = n.strip() if (n := names[1]) else None
        county: str | None = n.strip() if (n := names[2]) else None
        city: str | None = n.strip() if (n := names[3]) else None
        municipality: str | None = n.strip() if (n := names[4]) else None

        # 2. SONDERFALL: Stadtstaaten & Statutarstädte (Wien, Berlin, Hamburg, etc.)
        # Hier ist die Region oder das County der primäre Stadtname, da er im Bundesland steckt.
        if not city and state:
            if region and region in state:
                city = region
            elif county and county in state:
                city = county

        # 3. WELTWEITER FALLBACK: Wenn die Stadt (ADM4) komplett leer ist
        # Wenn es keine Statutarstadt ist, ziehen wir das administrative Zentrum
        # (County oder Region) hoch, lassen aber alle anderen Felder für Aggregationen intakt.
        if not city:
            if county:
                city = county
            elif region:
                city = region

        # 4. Wenn das Dorf exakt so heißt wie die übergeordnete Stadt, löschen wir die Redundanz.
        if city and municipality == city:
            city = None

        # 5. Werte typsicher und absolut ohne Datenverlust in das originale Array zurückschreiben
        names[1] = region if region else None
        names[2] = county if county else None
        names[3] = city if city else None
        names[4] = municipality if municipality else None

        return names

    # --------------------------------------------------------------------------------
    def search(self,
               latitude: float,
               longitude: float,
               neighbors: int = 7,
               sort: str = '',
               ascending: bool = True,
               language: str = 'de'
               ) -> list[GeoNeighbor] | None:
        """Universelle KDTree-Suche für alle Geo-Datenbanken mit dynamischer Sprachauflösung.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :param neighbors: (int) Anzahl der zu suchenden Nachbarn.
        :param sort: (str) Feldname, nach dem sortiert werden soll.
        :param ascending: (bool) Sortierreihenfolge.
        :param language: (str) ISO-Sprachkürzel für die administrativen Namen (z.B. 'de', 'en').
        :return: (list[GeoNeighbor] | None) Beschreibung
        """
        
        # --------------------------------------------------------------------------------
        def _get_adm(l_row: dict[str, Any], l_name: str) -> list[str | None]:

            """Kurzbeschreibung für _get_adm.
            
            :param l_row: (dict[str, Any]) Beschreibung von l_row.
            :param l_name: (str) Beschreibung von l_name.
            :return: (list[str | None]) Beschreibung des Rückgabewerts.
            """

            codes = [str(l_row.get(f, "")) for f in [FIELDAdmin1Code, FIELDAdmin2Code, FIELDAdmin3Code, FIELDAdmin4Code]]

            names: list[str | None] = []
            for j in range(4):
                key = ".".join([cc] + codes[:j + 1])
                adm_entry = self._adm_map.get(key, None)

                if isinstance(adm_entry, tuple):
                    adm_id, default_name = adm_entry
                    if alt_lookup and adm_id in alt_lookup:
                        names.append(alt_lookup[adm_id].get(language, default_name))
                    else:
                        names.append(default_name)
                else:
                    names.append("")

            names.append(l_name)
            names = self._normalize_cities(names)

            return names

        # --------------------------------------------------------------------------------
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)) or self._kdtree is None:
            log_to_callback(Tag.ERR, self.classname, 'Ungültige Koordinaten oder Baum nicht initialisiert.')
            return None

        # neighbors = neighbors * 3
        _, indexes = self._kdtree.query([latitude, longitude], k=neighbors)
        idx_list = [indexes] if neighbors == 1 else list(indexes)

        alt_service = GeoAlternatenamesDB()
        alt_lookup = alt_service.idlookup if alt_service is not None else {}

        results: list[GeoNeighbor] = []
        for i in idx_list:
            row = self._data[int(i)]
            dist = haversine(latitude, longitude, float(row[FIELDLatitude]), float(row[FIELDLongitude]))

            c2 = row.get(FIELDCountryCode2) if row else ''
            c2 = str(c2).upper() if c2 else None
            cc = str(c2).upper() if c2 else ''

            adm_names = _get_adm(l_row=row, l_name=Str.safe_str(row.get(FIELDName)))

            gn = GeoNeighbor(
                geonameid=MathUtils.safe_int(row.get(FIELDGeonameID)),
                latitude=float(row.get(FIELDLatitude, 0.0)),
                longitude=float(row.get(FIELDLongitude, 0.0)),
                elevation=MathUtils.safe_int(row.get(FIELDDigitalElevationModel, 0)),
                countrycode2=c2,
                countrycode3=None,
                country='',
                state=adm_names[0],
                region=adm_names[1],
                county=adm_names[2],
                city=adm_names[3],
                municipality=adm_names[4],
                timezone=Str.safe_str(row.get(FIELDTimezone)),
                population=MathUtils.safe_int(row.get(FIELDPopulation)),
                haversine=dist)

            if gn is not None:
                results.append(gn)

        if len(results) > 1:
            self._sort_geo_results(results, sort, ascending=ascending)
        return results

    # --------------------------------------------------------------------------------
    @staticmethod
    def _sort_geo_results(
            neighbors: list[GeoNeighbor],
            sort_field: str | None = None,
            ascending: bool = True,
    ) -> None:
        """Sortiert die Liste der GeoNeighbor-Objekte direkt (in-place).

        Normalisiert externe Feldnamen dynamisch über Case-Insensitivity, um sie
        mit den Attributen der GeoNeighbor-Dataclass abzugleichen.

        :param neighbors: (list[GeoNeighbor]) Die zu sortierende Liste.
        :param sort_field: (str | None) Das Feld für die Sortierung (case-insensitive).
        :param ascending: (bool) Sortierrichtung (True für aufsteigend).
        """
        
        # --------------------------------------------------------------------------------
        def sort_key_provider(l_item: GeoNeighbor) -> Any:
            """Liefert den typsicheren Vergleichsschlüssel für das Sortiersegment.

            :param l_item: (GeoNeighbor) Das zu prüfende GeoNeighbor-Objekt.
            :return: (Any) Der bereinigte Wert für die Sortierung.
            """
            val = getattr(l_item, target, None)
            return val if val is not None else fallback

        if not neighbors:
            return

        # 1. Bestimme das eingegangene Zielfeld
        raw_target: str = sort_field if sort_field else DEFAULT_SORT_FIELD

        # 2. Dynamische Normalisierung: Alles in Kleinbuchstaben konvertieren
        # und störende Trennzeichen wie Unterstriche oder Leerzeichen entfernen
        target: str = raw_target.lower().replace("_", "").replace(" ", "")

        # Ein kleiner Sicherheitsnetz-Fallback für Felder wie 'geonameid' vs 'geonamesid'
        if "id" in target and not target.endswith("id"):
            target = target.replace("id", "") + "id"

        # 3. Dynamische Typerkennung für das ermittelte Attribut
        is_string_field: bool = False
        for item in neighbors:
            # Falls das normalisierte Attribut nicht existiert, liefert getattr None
            current_val = getattr(item, target, None)
            if current_val is not None:
                is_string_field = isinstance(current_val, str)
                break

        # 4. Bestimme das sichere Fallback-Element für optionale Felder (None)
        fallback = "" if is_string_field else float("inf")

        # 5. In-Place-Sortierung ausführen
        neighbors.sort(key=sort_key_provider, reverse=not ascending)

    # --------------------------------------------------------------------------------
    def get_elevation(self, latitude: float | None = None, longitude: float | None = None) -> float | None:
        """Universelle KDTree-Suche für die Geländehöhe (DEM).
        
        :param latitude: (float | None) Breitengrad.
        :param longitude: (float | None) Längengrad.
        :return: (float | None) Beschreibung
        """
        # Schutz vor ungültigen Suchanfragen (Early Exit bei fehlenden Koordinaten)
        if latitude is None or longitude is None:
            return None

        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)) or self._kdtree is None:
            log_to_callback(Tag.ERR, self.classname, 'Ungültige Koordinaten oder Baum nicht initialisiert.')
            return None

        _, index = self._kdtree.query([latitude, longitude])

        if index:
            row = self._data[int(index)]
            return MathUtils.safe_float(row.get(FIELDDigitalElevationModel, 0))
        return None

    # --------------------------------------------------------------------------------
    def get_tzinfo(self, latitude: float | None, longitude: float | None) -> tzinfo | None:
        """Ermittelt die IANA-Zeitzone für gegebene Koordinaten.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (tzinfo | None) Beschreibung
        """
        # Schutz vor ungültigen Suchanfragen (Early Exit bei fehlenden Koordinaten)
        if latitude is None or longitude is None:
            return None

        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)) or self._kdtree is None:
            log_to_callback(Tag.ERR, self.classname, 'Ungültige Koordinaten oder Baum nicht initialisiert.')
            return None

        _, index = self._kdtree.query([latitude, longitude], k=1)
        row = self._data[int(index)]
        tz_name = Str.safe_str(row.get(FIELDTimezone)) if row.get(FIELDTimezone) else None
        return ZoneInfo(tz_name) if tz_name else None


# ================================================================================
# GeoNames Basisklassen & Implementierungen
# ================================================================================
class BaseGeoNamesDB(BaseGeoDB[dict[str, Any]], ABC):
    """Verwaltet die GeoNames-Datenbasis mit instanzbasiertem Daten-Lifecycle."""

    # --------------------------------------------------------------------------------
    def _init_singleton(self) -> None:
        """Erweitert die Basis-Strukturen um GeoNames-spezifische Instanzvariablen.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        super()._init_singleton()
        self._languages: set[str] = set()
        self._idlookup: dict[int, dict[str, str]] = {}
        self.manager: BaseGeoNamesDataManager | None = None

    # --------------------------------------------------------------------------------
    def __init__(self,
                 files: list[FilePath] | None = None,
                 features: list[str] | None = None,
                 features_field: str | None = None,
                 data_directory: Path | None = None,
                 verbose: bool = False,
                 offline_mode: bool = True) -> None:
        """Konstruktor läuft bei jedem Aufruf, triggert teure I/O-Ladevorgänge aber nur exakt einmal.
        
        :param files: (list[FilePath] | None) Beschreibung
        :param features: (list[str] | None) Beschreibung
        :param features_field: (str | None) Beschreibung
        :param data_directory: (Path | None) Beschreibung
        :param verbose: (bool) Beschreibung
        :param offline_mode: (bool) Beschreibung
        """
        # Lokaler Check des Lade-Status
        if not getattr(self, "_needs_loading", True):
            return

        # Absicherung über den klassenspezifischen Lock der Basisklasse
        with self._lock_pool[self.__class__]:
            # Erneute Prüfung innerhalb des kritischen Abschnitts
            if not self._needs_loading:
                return

            self._verbose = verbose
            self.data_directory = data_directory
            self._offline_mode = offline_mode

            self.manager = self._manager_class(
                files=files or [],
                features=features or [],
                features_field=features_field,
                data_directory=data_directory,
                verbose=verbose,
                offline_mode=self._offline_mode
            )
            try:
                self._apply_data(self.manager.load_data())
            except (FileNotFoundError, ValueError, KeyError) as error:
                log_to_callback(Tag.ERR, self.classname, f"Initialisierungsfehler: {error}")
                raise

            self._needs_loading = False

    # --------------------------------------------------------------------------------
    @property
    @abstractmethod
    def _manager_class(self) -> type[BaseGeoNamesDataManager]:
        """Erzwingt die Definition des Managers auf konkreten Klassen.
        
        :return: (type[BaseGeoNamesDataManager]) Beschreibung des Rückgabewerts.
        """

        pass

    # --------------------------------------------------------------------------------
    def ensure_country_loaded(self, alpha2: str) -> bool:
        """Stellt sicher, dass ein Land in der Laufzeit-Struktur vorhanden ist.
        
        :param alpha2: (str) ISO 3166-1 Alpha-2 Ländercode.
        :return: (bool) Beschreibung
        """
        alpha2 = alpha2.upper()
        if alpha2 in self._countries:
            return True
        return self.add_country(alpha2)

    # --------------------------------------------------------------------------------
    def _apply_data(self, data_dict: dict[str, Any]) -> None:
        """Aktiviert die geladenen Datenstrukturen direkt auf dem Objekt (self).
        
        :param data_dict: (dict[str, Any]) Daten-Dictionary aus dem Cache.
        """
        if not data_dict:
            return

        self._populate_instance_variables(data_dict, verbose=False)
        self._refresh_adm_index()

    # --------------------------------------------------------------------------------
    def _refresh_adm_index(self) -> None:
        """Neuaufbau des administrativen Indexes dieser Instanz.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        self._adm_map.clear()
        if self._data and isinstance(self._data, list) and len(self._data) > 0 and isinstance(self._data[0], dict):
            self._build_adm_index(self._data)

    # --------------------------------------------------------------------------------
    def add_country(self, alpha2: str) -> bool:
        """Lädt ein einzelnes Land dynamisch nach und merget es mit den bestehenden Instanzdaten.
        
        :param alpha2: (str) ISO 3166-1 Alpha-2 Ländercode.
        :return: (bool) Beschreibung
        """
        alpha2 = alpha2.upper()
        if alpha2 in self._countries:
            return True

        new_file_path: FilePath = (f"{alpha2}.zip", f"{alpha2}.txt")

        try:
            if self.manager is not None:
                updated_data: dict[str, Any] = self.manager.append_additional_sources([new_file_path])

                if updated_data:
                    self._apply_data(updated_data)

                    if self._verbose:
                        log_to_callback(Tag.STATUS, self.classname,
                                        f"Land '{alpha2}' erfolgreich integriert. Gesamteinträge: {len(self._data)}")

                    if self._on_country_added(alpha2):
                        return True

        except Exception as e:
            log_to_callback(Tag.ERR, self.classname, f"Fehler beim dynamischen Nachladen des Landes '{alpha2}': {e}")

        return False

    # --------------------------------------------------------------------------------
    def _on_country_added(self, alpha2: str) -> bool:
        """Hook für nachgelagerte Synchronisationsprozesse bei Unterklassen.
        
        :param alpha2: (str) Der Ländercode.
        :return: (bool) Beschreibung
        """
        if self._verbose:
            log_to_callback(Tag.STATUS, self.classname, f"Hook für '{alpha2}' wird aufgerufen")
        return True


# ================================================================================
# GeoNames DB
# ================================================================================
class GeoNamesDB(BaseGeoNamesDB):
    """Spezifische Datenbank für GeoNames Hauptdaten."""

    _manager_class = GeoNamesDataManager

    # --------------------------------------------------------------------------------
    def _on_country_added(self, alpha2: str) -> bool:
        """Synchronisiert den Alternativnamen-Service beim Laden neuer Hauptdaten.
        
        :param alpha2: (str) Der Ländercode.
        :return: (bool) Beschreibung
        """
        alt_service = GeoAlternatenamesDB()
        if alt_service and isinstance(alt_service, GeoAlternatenamesDB):
            if self._verbose:
                log_to_callback(Tag.STATUS, self.classname, f"Synchronisiere Alternatenames für {alpha2}")
            return alt_service.add_country(alpha2)
        return True


# ================================================================================
# GeoAlternatenames DB
# ================================================================================
class GeoAlternatenamesDB(BaseGeoNamesDB):
    """Spezifische Datenbank für GeoNames Alternativnamen."""

    _manager_class = GeoAltNamesDataManager

    # --------------------------------------------------------------------------------
    def _refresh_adm_index(self) -> None:
        """Überschreibt Basis-Implementierung, da Alternativnamen keine ADM-Ebenen enthalten.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        pass


# ================================================================================
# GeoCities DB
# ================================================================================
class GeoCitiesDB(BaseGeoDB[dict[str, Any]]):
    """Verwaltet die GeoCities-Datenbasis."""

    # --------------------------------------------------------------------------------
    def __init__(self,
                 files: list[FilePath] | None = None,
                 features: list[str] | None = None,
                 data_directory: Path | None = None,
                 verbose: bool = False,
                 offline_mode: bool = True) -> None:
        """Initialisiert GeoCitiesDB komplett objektbasiert.
        
        :param files: (list[FilePath] | None) Beschreibung
        :param features: (list[str] | None) Beschreibung
        :param data_directory: (Path | None) Beschreibung
        :param verbose: (bool) Beschreibung
        :param offline_mode: (bool) Beschreibung
        """
        if not self._needs_loading:
            return

        self._verbose = verbose
        self.data_directory = data_directory
        self._offline_mode = offline_mode

        manager = GeoCitiesDataManager(
            files=files or [],
            features=features or [],
            features_field=FIELDFeatureClass,
            verbose=verbose,
            offline_mode=self._offline_mode
        )

        try:
            data = manager.load_data()
            if GEONAMES_DATA_KEY not in data or GEONAMES_TREE_KEY not in data:
                raise ValueError("Geladene Cache-Daten sind unvollständig.")

            self._populate_instance_variables(data, verbose=verbose)

        except (KeyError, ValueError) as e:
            log_to_callback(Tag.ERR, GeoCitiesDB.__name__, f"Initialisierungsfehler: {e}")
            raise

        self._needs_loading = False

    # --------------------------------------------------------------------------------
    def alpha2_from_coords(self, latitude: float, longitude: float) -> str | None:
        """Ermittelt den Alpha-2 Code direkt über den KDTree der Städte-DB.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (str | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)) or self._kdtree is None:
            log_to_callback(Tag.ERR, self.classname, 'Ungültige Koordinaten oder Baum nicht initialisiert.')
            return None

        _, index = self._kdtree.query([latitude, longitude], k=1)
        row = self._data[int(index)]
        c2 = Str.safe_str(row.get(FIELDCountryCode2))
        return str(c2) if c2 else None


# ================================================================================
# GeoCountries DB
# ================================================================================
class GeoCountriesDB(BaseGeoDB[dict[str, Any]]):
    """Verwaltet die GeoCountries-Datenbasis."""

    # --------------------------------------------------------------------------------
    def _init_singleton(self) -> None:
        """Erreicht die Basis-Initialisierung um die spezifische Resolvermap.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        super()._init_singleton()
        self._resolvermap: dict[str, dict[str, Any]] = {}

    # --------------------------------------------------------------------------------
    def __init__(self,
                 data_directory: Path | None = None,
                 languages: list[str] | None = None,
                 verbose: bool = False,
                 offline_mode: bool = True) -> None:
        """Initialisiert GeoCountriesDB instanzspezifisch.
        
        :param data_directory: (Path | None) Beschreibung
        :param languages: (list[str] | None) Beschreibung
        :param verbose: (bool) Beschreibung
        :param offline_mode: (bool) Beschreibung
        """
        if not self._needs_loading:
            return

        self._verbose = verbose
        self.data_directory = data_directory
        self._offline_mode = offline_mode

        manager = GeoCountriesDataManager(
            data_directory=data_directory,
            languages=languages,
            verbose=verbose,
            offline_mode=self._offline_mode
        )

        try:
            data = manager.load_data()
            if GEONAMES_DATA_KEY not in data:
                raise ValueError("Geladene Cache-Daten sind unvollständig.")

            self._populate_instance_variables(data, verbose=verbose)

        except (KeyError, ValueError) as e:
            log_to_callback(Tag.ERR, self.classname, f"Initialisierungsfehler: {e}")
            raise

        self._needs_loading = False

    # --------------------------------------------------------------------------------
    @property
    def resolvermap(self) -> dict[str, dict[str, Any]]:
        """Gibt die vorbereitete Resolver-Map für den schnellen Zugriff zurück.
        
        :return: (dict[str, dict[str, Any]]) Beschreibung des Rückgabewerts.
        """

        return self._resolvermap


# ================================================================================
# CountryResolver mit nativem __new__ Singleton Pattern
# ================================================================================
class CountryResolver:
    """Ermittelt Länderinformationen über entkoppelte Lazy-Properties der Service-Instanzen."""

    _instance: ClassVar[CountryResolver | None] = None
    # Globaler Thread-Lock-Pool für alle Service-Klassen
    _lock_pool: ClassVar[dict[type, threading.Lock]] = {}

    # --------------------------------------------------------------------------------
    def __new__(cls, *args: Any, **kwargs: Any) -> CountryResolver:
        """Stellt sicher, dass das CountryResolver-Singleton nativ und thread-sicher gekapselt ist.
        
        :return: (CountryResolver) Beschreibung des Rückgabewerts.
        """

        # Nativer Klassenbezeichner (Typ-Objekt) als Key für den Thread-Lock holen/erstellen
        if cls not in cls._lock_pool:
            cls._lock_pool.setdefault(cls, threading.Lock())

        # Double-Checked Locking Pattern für die Instanziierung
        if cls._instance is None:
            with cls._lock_pool[cls]:
                if cls._instance is None:
                    instance: CountryResolver = object.__new__(cls)
                    instance._needs_loading = True
                    cls._instance = instance
                    return instance

        cls._instance._needs_loading = False
        return cls._instance

    # --------------------------------------------------------------------------------
    def __init__(self, verbose: bool = False, offline_mode: bool = True) -> None:
        """Wird bei jedem Zugriff aufgerufen, setzt Konfigurationswerte instanzsicher um.
        
        :param verbose: (bool) Beschreibung
        :param offline_mode: (bool) Beschreibung
        """
        if not getattr(self, "_needs_loading", True):
            return

            # Absicherung über den klassenspezifischen Lock der Basis/Klasse
        with self._lock_pool[self.__class__]:
            # Erneute Prüfung im geschützten Bereich (Double-Checked)
            if not self._needs_loading:
                return

            self._verbose: bool = verbose
            self._offline_mode: bool = offline_mode
            self._needs_loading = False

    # --------------------------------------------------------------------------------
    @property
    def _geocities_service(self) -> GeoCitiesDB | None:
        """Lazy-Property für den GeoCities-Suchdienst.
        
        :return: (GeoCitiesDB | None) Beschreibung des Rückgabewerts.
        """

        return get_geocities_service(verbose=self._verbose, offline_mode=self._offline_mode)

    # --------------------------------------------------------------------------------
    @property
    def _geocountries_service(self) -> GeoCountriesDB | None:
        """Lazy-Property für den GeoCountries-Suchdienst.
        
        :return: (GeoCountriesDB | None) Beschreibung des Rückgabewerts.
        """

        return get_geocountries_service(verbose=self._verbose, offline_mode=self._offline_mode)

    # --------------------------------------------------------------------------------
    @property
    def _geoalternatenames_service(self) -> GeoAlternatenamesDB | None:
        """Lazy-Property für den Alternatenames-Dienst.
        
        :return: (GeoAlternatenamesDB | None) Beschreibung des Rückgabewerts.
        """

        return get_geoalternatenames_service(verbose=self._verbose, offline_mode=self._offline_mode)

    # --------------------------------------------------------------------------------
    def iso3_and_name(self, alpha2: str | None, language: str = 'de') -> tuple[str | None, str | None]:
        """Gibt ISO3 und lokalisierten Namen zurück. Priorisiert die gewählte Sprache.
        
        :param alpha2: (str | None) Alpha-2 Code (z.B. 'DE').
        :param language: (str) Sprachkürzel für den Namen. Standard ist 'de'.
        :return: (tuple[str | None, str | None]) Beschreibung
        """
        lang_lower = language.lower()
        if not alpha2:
            return DEFAULT_RESULT

        countries_service = self._geocountries_service
        if countries_service is None:
            return DEFAULT_RESULT

        data = countries_service.resolvermap
        if not data:
            return DEFAULT_RESULT

        alpha2_upper = alpha2.upper()
        country_info: dict[str, Any] | None = None

        if isinstance(data, dict):
            country_info = data.get(alpha2_upper)
        # elif isinstance(data, list):
        #     for row in data:
        #         if str(row.get(FIELDCountryCode2, "")).upper() == alpha2_upper:
        #             country_info = row
        #             break

        if not isinstance(country_info, dict):
            return DEFAULT_RESULT

        iso3 = country_info.get(FIELDISO3)
        geoname_id = country_info.get(FIELDGeonameID)
        default_name = str(country_info.get(FIELDCOUNTRY, ""))

        service = self._geoalternatenames_service
        alt_lookup: dict[int, dict[str, str]] = service.idlookup if service else {}

        localized_name: str | None = None
        if alt_lookup and isinstance(geoname_id, (int, float)):
            try:
                gid_key = int(geoname_id)
                if gid_key in alt_lookup:
                    localized_name = alt_lookup[gid_key].get(lang_lower)
                    if not localized_name:
                        localized_name = alt_lookup[gid_key].get('en')
            except (ValueError, TypeError):
                pass

        if not localized_name:
            localized_name = default_name

        return (
            Str.safe_str(iso3).upper() if iso3 else None,
            Str.safe_str(localized_name) if localized_name else None
        )

    # --------------------------------------------------------------------------------
    def alpha2_from_coords(self, latitude: float, longitude: float) -> str | None:
        """Ermittelt den Alpha-2 Code aus Koordinaten via GeoCitiesDB.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (str | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None

        service = self._geocities_service
        if service is None:
            return None

        res = service.alpha2_from_coords(latitude, longitude)
        return res if res else None

    # --------------------------------------------------------------------------------
    def get_tzinfo(self, latitude: float, longitude: float) -> tzinfo | None:
        """Ermittelt die IANA-Zeitzone für gegebene Koordinaten über GeoCitiesDB.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (tzinfo | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None

        service = self._geocities_service
        if service is None:
            return None

        res = service.get_tzinfo(latitude, longitude)
        return res if res else None

    # --------------------------------------------------------------------------------
    def get_elevation(self, latitude: float, longitude: float) -> float | None:
        """Universelle KDTree-Suche für die Geländehöhe (DEM).
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (float | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None

        service = self._geocities_service
        if service is None:
            return None

        res = service.get_elevation(latitude, longitude)
        return res if res else None


# ================================================================================
# GeoLocator mit nativem __new__ Singleton Pattern
# ================================================================================
class GeoLocator:
    """Ermittelt vollständige Adressdaten für Koordinaten auf Instanz-Ebene."""

    _instance: ClassVar[GeoLocator | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # --------------------------------------------------------------------------------
    def __new__(cls, *args: Any, **kwargs: Any) -> GeoLocator:
        """Stellt sicher, dass das GeoLocator-Singleton nativ und thread-sicher gekapselt ist.
        
        :return: (GeoLocator) Beschreibung des Rückgabewerts.
        """

        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance: GeoLocator = object.__new__(cls)
                    instance.classname = cls.__name__
                    instance._needs_loading = True
                    cls._instance = instance
                    return instance

        cls._instance._needs_loading = False
        return cls._instance

    # --------------------------------------------------------------------------------
    def __init__(self, language: str = 'de', verbose: bool = False, offline_mode: bool = True) -> None:
        """Initialisiert den GeoLocator beim Kaltstart.
        
        :param language: (str) Beschreibung
        :param verbose: (bool) Beschreibung
        :param offline_mode: (bool) Beschreibung
        """
        if not getattr(self, "_needs_loading", True):
            return

        with self._lock:
            if not self._needs_loading:
                return

            self._verbose = verbose
            self._offline_mode = offline_mode
            self.language = language
            self._geo_cache: dict[tuple[float, float], GeoInfo | None] = {}

            self._needs_loading = False

    # --------------------------------------------------------------------------------
    def get_geonames_information(self, latitude: float, longitude: float) -> GeoInfo | None:
        """Gecachte Standortermittlung.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :return: (GeoInfo | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None

        cache_key = (round(latitude, GEO_CACHE_PRECISION), round(longitude, GEO_CACHE_PRECISION))

        if cache_key in self._geo_cache:
            if self._verbose:
                log_to_callback(Tag.STATUS, self.classname, f'Cache-Hit für {latitude:.4f}/{longitude:.4f}')
            return self._geo_cache[cache_key]

        country_resolver = CountryResolver()
        countrycode2: str | None = country_resolver.alpha2_from_coords(latitude, longitude) if country_resolver else None

        geonames_db = GeoNamesDB()
        if countrycode2 and geonames_db:
            geonames_db.ensure_country_loaded(countrycode2)
        else:
            return None

        neighbors: list[GeoNeighbor] | None = None

        if geonames_db:
            neighbors = geonames_db.search(
                latitude=latitude, longitude=longitude, sort=FIELDHaversine, ascending=True
            )

        geocities_db = GeoCitiesDB()
        if not neighbors and geocities_db:
            if self._verbose:
                log_to_callback(Tag.STATUS, self.classname, "GeoNames nicht verfügbar — nutze GeoCities.")
            neighbors = geocities_db.search(
                latitude=latitude, longitude=longitude, sort=FIELDHaversine, ascending=True
            )

        geoinfo: GeoInfo | None = None

        # iso3 und Name des Landes werden gefüllt
        if neighbors:
            enriched_neighbors: list[GeoNeighbor] = []

            for neighbor in neighbors:
                if country_resolver:
                    iso3, c_name = country_resolver.iso3_and_name(alpha2=neighbor.countrycode2, language=self.language)
                    neighbor = replace(neighbor, countrycode3=iso3, country=c_name or '')
                enriched_neighbors.append(neighbor)

            # wurde schon sortiert in search
            closest = enriched_neighbors[0]
            geoinfo = GeoInfo(
                latitude=closest.latitude,
                longitude=closest.longitude,
                neighbor=closest,
                neighbors=enriched_neighbors
            )

        self._geo_cache[cache_key] = geoinfo
        return geoinfo

    # --------------------------------------------------------------------------------
    @staticmethod
    def get_tzinfo(latitude: float | None = None, longitude: float | None = None) -> tzinfo | None:
        """Ermittelt die IANA-Zeitzone für gegebene Koordinaten.
        
        :param latitude: (float | None) Breitengrad.
        :param longitude: (float | None) Längengrad.
        :return: (tzinfo | None) Beschreibung
        """
        has_geo = None not in (latitude, longitude) and (latitude != 0.0 or longitude != 0.0)
        if not has_geo:
            return None
        geonames_db = GeoNamesDB()
        return geonames_db.get_tzinfo(latitude=latitude, longitude=longitude) if geonames_db else None

    # --------------------------------------------------------------------------------
    @staticmethod
    def get_elevation(latitude: float | None = None, longitude: float | None = None) -> float | None:
        """Universelle KDTree-Suche für die Geländehöhe (DEM).
        
        :param latitude: (float | None) Breitengrad.
        :param longitude: (float | None) Längengrad.
        :return: (float | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None
        geonames_db = GeoNamesDB()
        return geonames_db.get_elevation(latitude=latitude, longitude=longitude)


# ================================================================================
# Elevation & OpenStreetMap
# ================================================================================
class Elevation:
    """Höhenabfrage für GPS-Punkte."""

    _instance: ClassVar[Elevation | None] = None

    # --------------------------------------------------------------------------------
    def __new__(cls, *args: Any, **kwargs: Any) -> Elevation:
        """Garantiert, dass im gesamten Laufzeitprozess nur eine Instanz existiert.
        
        :return: (Elevation) Beschreibung des Rückgabewerts.
        """

        if cls._instance is None:
            instance: Elevation = object.__new__(cls)
            instance.classname = cls.__name__
            instance._needs_loading = True
            cls._instance = instance
        else:
            cls._instance._needs_loading = False
            instance = cls._instance

        return instance

    # --------------------------------------------------------------------------------
    def __init__(self, verbose: bool = False) -> None:
        """Initialisiert den Höhen-Dienst exakt einmal beim Kaltstart.
        
        :param verbose: (bool) Aktiviert detaillierte Protokollausgaben für die Abfragen.
        """
        if not self._needs_loading:
            return

        self._verbose: bool = verbose
        self._needs_loading = False

    # --------------------------------------------------------------------------------
    def get_elevation(self, point: GeoPoint) -> float | None:
        """Ruft die geografische Höhe für einen GPS-Punkt ab.
        
        :param point: (GeoPoint) Das abzufragende GeoPoint-Objekt mit latitude und longitude.
        :return: (float | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(point.latitude) and MathUtils.is_valid_float(point.longitude)):
            return None

        elevation: float | None = None
        geonames_db = GeoNamesDB()

        if geonames_db and point.latitude is not None and point.longitude is not None:
            # Hier greifen wir auf die lokale Suchfunktion der GeoNamesDB zu
            elevation = geonames_db.get_elevation(latitude=point.latitude, longitude=point.longitude)
            if self._verbose and elevation is not None:
                log_to_callback(Tag.STATUS, self.classname, f'GeoNames: [{point.latitude}, {point.longitude}] → {elevation}m')

        if elevation is None:
            fetchers: list[Callable[[GeoPoint], float | None]] = [
                self._get_elevation_OpenTopo,
                self._get_elevation_OpenElevation
            ]
            for fetcher in fetchers:
                elevation = fetcher(point)
                if elevation is not None:
                    break
            else:
                if self._verbose:
                    log_to_callback(Tag.STATUS, self.classname, f'Höhenabfrage fehlgeschlagen: [{Str.safe_str(point.latitude)}, {Str.safe_str(point.longitude)}]')

        return elevation

    # --------------------------------------------------------------------------------
    def _get_elevation_OpenElevation(self, point: GeoPoint) -> float | None:
        """Führt eine Höhenabfrage über die Open-Elevation API durch.
        
        :param point: (GeoPoint) Der abzufragende Geokoordinatenpunkt.
        :return: (float | None) Beschreibung
        """
        return self._call_elevation(ELEVATION_QUERY_OE_URL, point)

    # --------------------------------------------------------------------------------
    def _get_elevation_OpenTopo(self, point: GeoPoint) -> float | None:
        """Führt eine Höhenabfrage über die OpenTopoData API durch.
        
        :param point: (GeoPoint) Der abzufragende Geokoordinatenpunkt.
        :return: (float | None) Beschreibung
        """
        return self._call_elevation(ELEVATION_QUERY_OT_URL, point)

    # --------------------------------------------------------------------------------
    @classmethod
    def _call_elevation(cls, query: str, point: GeoPoint) -> float | None:
        """Führt eine standardisierte HTTP-REST-Abfrage für Höhendaten durch.
        
        :param query: (str) Der URL-Formatstring für die Ziel-API.
        :param point: (GeoPoint) Der abzufragende Zielpunkt.
        :return: (float | None) Beschreibung
        """
        if not query or point.latitude is None or point.longitude is None:
            return None

        response = HttpUtils.get_content_from_url(
            query.format(point.latitude, point.longitude),
            error_message=cls.__name__,
            timeout=ELEVATION_TIMEOUT_SEC,
            json=True
        )

        # Prüfen, ob response existiert UND ob es den erwarteten Typ hat
        if not response or not isinstance(response, tuple):
            return None

        _, content = response
        results: list[dict[str, Any]] = content.get("results", [])

        if not results or not isinstance(results, list):
            return None

        elevation = results[0].get("elevation")
        time.sleep(ELEVATION_DELAY_SEC)

        return MathUtils.safe_float(elevation)


# ================================================================================
# GeoOSM
# ================================================================================
class GeoOSM:
    """Straßensuche via OSM Overpass API."""

    # --------------------------------------------------------------------------------
    def __init__(self, verbose: bool = False) -> None:
        """Initialisiert das OSM Overpass Suchmodul.
        
        :param verbose: (bool) Verbose-Ausgabe.
        """
        self._verbose = verbose
        self.classname = self.__class__.__name__

    # --------------------------------------------------------------------------------
    def search(self, latitude: float, longitude: float, radius: float = 100) -> Result | dict | None:
        """Sucht Straßen in einem Radius um gegebene Koordinaten.
        
        :param latitude: (float) Breitengrad.
        :param longitude: (float) Längengrad.
        :param radius: (float) Suchradius in Metern (Standard: 100m).
        :return: (Result | dict | None) Beschreibung
        """
        if not (MathUtils.is_valid_float(latitude) and MathUtils.is_valid_float(longitude)):
            return None

        api = Overpass()
        query = f"""
        [out:json];
        (
          way["highway"](around:{radius},{latitude},{longitude});
        );
        out body;
        >;
        out skel qt;
        """

        try:
            result = api.query(query)
            if self._verbose and result:
                num_elements = len(result.get('elements', [])) if isinstance(result, dict) else "Unbekannt"
                log_to_callback(Tag.STATUS, self.classname, f"Overpass-Suche erfolgreich: {num_elements} Elemente gefunden.")
            return result

        except Exception as e:
            log_to_callback(Tag.ERR, GeoOSM.__name__, f"Fehler bei Overpass-Abfrage: {e}")
            return None


# ==========================================================================================
# Instanz-Singleton-Verwaltung mit Abschaltlogik (USE-Flags)
# ==========================================================================================
# --------------------------------------------------------------------------------
def initialize_all_geo_services(
        verbose: bool = False,
        offline_mode: bool = True,
        profiler: Profile | None = None,
) -> None:
    """Initialisiert alle geografischen Singleton-Dienste in der korrekten strukturellen Stufen-Reihenfolge.
    
    :param verbose: (bool) Aktiviert detaillierte Logging-Ausgaben während der Initialisierung.
    :param offline_mode: (bool) Lädt lokale Cache-Dateien (Pickle) ohne zeitaufwändige Download-Validierung.
    :param profiler: (Profile | None) Profile für Profiling.
    """
    log_to_callback(Tag.STATUS, "Initializer", "Starte kontrollierte Eager-Initialisierung aller Geo-Dienste...")

    if profiler:
        profiler.enable()

    try:
        if verbose:
            log_to_callback(Tag.STATUS, "Initializer", "Stufe 1: Initialisiere CountryResolver...")
        get_countryresolver_service(verbose=verbose, offline_mode=offline_mode)

        if verbose:
            log_to_callback(Tag.STATUS, "Initializer", "Stufe 2: Initialisiere geografische Datenbanken...")

        get_geocountries_service(verbose=verbose, offline_mode=offline_mode)
        get_geocities_service(verbose=verbose, offline_mode=offline_mode)
        get_geoalternatenames_service(verbose=verbose, offline_mode=offline_mode)
        get_geonames_service(verbose=verbose, offline_mode=offline_mode)

        if verbose:
            log_to_callback(Tag.STATUS, "Initializer", "Stufe 3: Initialisiere Haupt-Dienst (GeoLocator)...")
        get_geolocator_service(verbose=verbose, offline_mode=offline_mode)

        log_to_callback(Tag.STATUS, "Initializer", "Alle geografischen Dienste erfolgreich im RAM initialisiert.")

        geonames_db = GeoNamesDB()
        if geonames_db:
            loaded_countries = sorted(geonames_db.countries)
            countries_str = ", ".join(loaded_countries) if loaded_countries else "Keine"
            log_to_callback(Tag.STATUS, GeoNamesDB.__name__, f"Geladene Länder ({len(loaded_countries)}): [{countries_str}]")

        geoalt_db = GeoAlternatenamesDB()
        if geoalt_db:
            loaded_countries = sorted(geoalt_db.countries)
            countries_str = ", ".join(loaded_countries) if loaded_countries else "Keine"
            log_to_callback(Tag.STATUS, GeoAlternatenamesDB.__name__, f"Geladene Länder ({len(loaded_countries)}): [{countries_str}]")

        if profiler:
            profiler.disable()
            stats = pstats.Stats(profiler).sort_stats(pstats.SortKey.TIME)
            stats.print_stats(20)

    except Exception as error:
        log_to_callback(Tag.ERR, "Initializer", f"Kritischer Fehler bei der sequentiellen Vorab-Initialisierung: {error}")
        raise error


# --------------------------------------------------------------------------------
def get_geolocator_service(verbose: bool = False, offline_mode: bool = True) -> GeoLocator | None:
    """Singleton-Getter für GeoLocator. Berücksichtigt DEFAULT_GEOLOCATOR_USE.
    
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (GeoLocator | None) Beschreibung
    """
    if not DEFAULT_GEOLOCATOR_USE:
        return None
    return GeoLocator(verbose=verbose, offline_mode=offline_mode)


# --------------------------------------------------------------------------------
def get_geonames_service(files: list[FilePath] | None = None, features: list[str] | None = None,
                         verbose: bool = False, offline_mode: bool = True) -> GeoNamesDB | None:
    """Singleton-Getter für GeoNamesDB. Berücksichtigt DEFAULT_GEONAMES_USE.
    
    :param files: (list[FilePath] | None) Beschreibung
    :param features: (list[str] | None) Beschreibung
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (GeoNamesDB | None) Beschreibung
    """
    if not DEFAULT_GEONAMES_USE:
        return None

    input_files = files if files is not None else DEFAULT_GEONAMES_FILES
    final_files: list[FilePath] = input_files if isinstance(input_files, list) else [input_files]

    return GeoNamesDB(
        files=final_files,
        features=features or DEFAULT_GEONAMES_FEATURE,
        features_field=FIELDFeatureClass,
        verbose=verbose,
        offline_mode=offline_mode
    )


# --------------------------------------------------------------------------------
def get_geoalternatenames_service(files: list[FilePath] | None = None, features: list[str] | None = None,
                                  verbose: bool = False, offline_mode: bool = True) -> GeoAlternatenamesDB | None:
    """Singleton-Getter für GeoAlternatenamesDB mit automatischer Quell-Synchronisation.
    
    :param files: (list[FilePath] | None) Beschreibung
    :param features: (list[str] | None) Beschreibung
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (GeoAlternatenamesDB | None) Beschreibung
    """
    if not DEFAULT_GEONAMES_USE:
        return None

    geonames_service = get_geonames_service()
    master_sources: list[FilePath] = geonames_service.sources if geonames_service else []

    input_files = files if files is not None else DEFAULT_GEOALTERNATENAMES_FILES
    final_files: list[FilePath] = input_files if isinstance(input_files, list) else [input_files]

    if master_sources:
        existing_target_names = {
            Path(p).name if isinstance(p, (str, Path)) else Path(p[1]).name if hasattr(p[1], "name") else Path(p[1]).name
            for p in final_files
        }

        for src_zip, src_txt in master_sources:
            pure_txt_name = Path(src_txt).name
            pure_zip_name = Path(src_zip).name

            if pure_txt_name not in existing_target_names:
                if verbose:
                    log_to_callback(Tag.STATUS, "get_geoalternatenames_service", f"Synchronisiere Quelle aus GeoNames: {pure_txt_name}")
                final_files.append((pure_zip_name, pure_txt_name))

    return GeoAlternatenamesDB(
        files=final_files,
        features=features or DEFAULT_GEOALTERNATENAMES_FEATURE,
        features_field=FIELDISOLANGUAGE,
        verbose=verbose,
        offline_mode=offline_mode
    )


# --------------------------------------------------------------------------------
def get_geocities_service(files: list[FilePath] | None = None, features: list[str] | None = None,
                          verbose: bool = False, offline_mode: bool = True) -> GeoCitiesDB | None:
    """Singleton-Getter für GeoCitiesDB. Berücksichtigt DEFAULT_GEOCITIES_USE.
    
    :param files: (list[FilePath] | None) Beschreibung
    :param features: (list[str] | None) Beschreibung
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (GeoCitiesDB | None) Beschreibung
    """
    if not DEFAULT_GEOCITIES_USE:
        return None

    input_files = files if files is not None else DEFAULT_GEOCITIES_FILES
    final_files: list[FilePath] = input_files if isinstance(input_files, list) else [input_files]

    return GeoCitiesDB(
        files=final_files,
        features=features or DEFAULT_GEOCITIES_FEATURE,
        verbose=verbose,
        offline_mode=offline_mode
    )


# --------------------------------------------------------------------------------
def get_geocountries_service(verbose: bool = False, offline_mode: bool = True) -> GeoCountriesDB | None:
    """Singleton-Getter für GeoCountriesDB. Berücksichtigt DEFAULT_GEONAMES_USE.
    
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (GeoCountriesDB | None) Beschreibung
    """
    if not DEFAULT_GEONAMES_USE:
        return None
    return GeoCountriesDB(verbose=verbose, languages=GEOALTERNATENAMES_FEATURE, offline_mode=offline_mode)


# --------------------------------------------------------------------------------
def get_countryresolver_service(verbose: bool = False, offline_mode: bool = True) -> CountryResolver | None:
    """Singleton-Getter für CountryResolver. Berücksichtigt DEFAULT_GEONAMES_USE.
    
    :param verbose: (bool) Beschreibung
    :param offline_mode: (bool) Beschreibung
    :return: (CountryResolver | None) Beschreibung
    """
    if not DEFAULT_GEONAMES_USE:
        return None
    return CountryResolver(verbose=verbose, offline_mode=offline_mode)


# --------------------------------------------------------------------------------
def get_elevation_service(verbose: bool = False) -> Elevation:
    """Singleton-Getter für den zentralen Höhen-Dienst (Elevation).
    
    :param verbose: (bool) Wenn True, werden detaillierte Suchlogs ausgegeben.
    :return: (Elevation) Beschreibung
    """
    return Elevation(verbose=verbose)
