# rpg_gpmf

# RPG Tools Framework Suite

Eine leistungsfähige, modulare Python-Framework-Suite zur Extraktion und Verarbeitung von **GoPro-Telemetriedaten (GPMF)**, Erzeugung von **GPX-Tracks**, **Geokodierung**, **Karten-Rendering**, **Video-Overlays** sowie wiederverwendbaren **PySide6-UI-Utilities**.

---

## 🏗️ Architektur & Modul-Übersicht

Das Framework **rpg-tools** stellt die zentrale Bibliothek dar, auf der Anwendungs-Suites wie **[gopro-tools](https://github.com/RalfPeter/gopro-tools)** (GUIs und CLI-Skripte) aufbauen:

  ┌───────────────────────────────────────────────────────────────────────────────────┐
  │                                    gopro-tools                                    │
  │        (Anwendungen: gui_gopro2file, gui_gopro2overlay, CLI Pipelines)            │
  └─────────────────────────────────────────┬─────────────────────────────────────────┘
                                            │  nutzt als Bibliothek
                                            ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                                     rpg-tools                                       │
  │                              (Core Framework Suite)                                 │
  ├───────────┬───────────┬───────────┬────────────────┬───────────────────┬────────────┤
  │ rpg_gpmf  │  rpg_geo  │  rpg_gpx  │    rpg_gui     │     rpg_utils     │rpg_overlay │
  │Telemetrie │Geocoding  │GPX Tracks │ PySide6 Base   │ Shared Utilities  │ Video      │
  │GPMF KLV   │GeoNames   │Schema / IO│ Templates/Utils│ Logger/Config/Math│ Overlays   │
  └───────────┴───────────┴───────────┴────────────────┴───────────────────┴────────────┘

---

---

## rpg_gpmf

Kern-Modul zur Extraktion und Verarbeitung von GoPro-GPMF-Binärdaten (KLV-Parsing), Video-Metadaten-Analyse und Rohdaten-Exporten.

### Allgemeines
Das Framework **`rpg_gpmf`** ist eine hochspezialisierte, objektorientierte Python-3.10+-Bibliothek zur professionellen Verarbeitung, Extraktion, Geokodierung und Metadaten-Anreicherung von Action-Cam-Medien (fokussiert auf das *GoPro Metadata Format* – **GPMF**) sowie zugehörigen Foto-, Video- und Geodaten-Dateien (GPX/KML/NMEA).

Es dient als zentrales Bindeglied zwischen Rohdaten von Kamerasystemen (z. B. GoPro, Contour, Novatek, iCatch), Geodaten-Diensten und Metadaten-Standards für Mediendateien. Das Framework wurde entwickelt, um große Mengen an Bild- und Videomaterial vollautomatisch zu analysieren, zeitlich und räumlich zu synchronisieren sowie mit detaillierten GPS- und Adressinformationen zu versehen.

#### Kernfunktionen und Einsatzgebiete
* **Standardisierte Metadaten-Verwaltung (EXIF, IPTC, XMP):**
  Vollständiges Lesen, Korrigieren und Schreiben von Bildmetadaten über eine Kapselung von `pyexiv2`. Es ermöglicht die zeitgenaue Ausrichtung von Erstellungsdaten, Zeitzonen-Offsets und Geokoordinaten sowie das automatische Generieren hierarchischer Schlagwörter (z. B. für DigiKam-Albenstrukturen).
* **Hochperformante Räumliche Geosuche (Reverse Geocoding & DEM):**
  Integration lokaler *GeoNames*-, *GeoCities*- und *GeoCountries*-Datenbanken. Unter Verwendung von `scipy.spatial.KDTree` führt das Framework extrem schnelle Nächste-Nachbarn-Suchen durch, um Koordinaten in reale Ortsnamen, administrative Ebenen (Bundesland, Region, Landkreis, Stadt, Gemeinde) sowie Geländehöhen (*Digital Elevation Model*) und IANA-Zeitzonen aufzulösen.
* **Schnittstelle für Videoverarbeitung (FFmpeg / FFprobe):**
  Robustes Management externer FFmpeg- und FFprobe-Binaries mit automatischer Pfad- und Versionserkennung, plattformübergreifender Konfigurationsauflösung und fensterloser Subprozess-Ausführung (unter Windows via `CREATE_NO_WINDOW`).
* **GoPro-Spezifika & Konstantenverwaltung:**
  Zentrale Definitionen der GoPro-Dateibenennungskonventionen (Kapitelvideos, Looping, AVC/HEVC-Standardisierung), Kamera-Encoder, Toleranzschwellenwerte für GPS-Plausibilitätsprüfungen (DOP-Grenzwerte, Max-Distanzen, Geschwindigkeitsprüfungen) und Dateierweiterungs-Klassifizierungen.

### Modulübersicht

#### 1. `gpmf_const.py` (Konstanten & Konfigurationen)
Enthält alle zentralen Literale, Datei-Endungen, Farb- und Schwellenwerte für die Verarbeitung von Medien und Geodaten:
* **Dateitypen & Erweiterungen:** Definitionen für Videos (`.mp4`, `.mov`), Geodaten (`.gpx`, `.gpmf`, `.kml`, `.bin`), Bilder (`.jpg`, `.png`) und temporäre/Trash-Muster.
* **GoPro-Nomenklatur:** Erkennungslogik für AVC (`GH`) und HEVC (`GX`) Dateimuster, Kapitelierungs- (`GHzzxxxx`) und Looping-Formate (`GHYYxxxx`).
* **GPS- & Geodaten-Schwellenwerte:** Schwellenwerte für maximale Punktabstände (`MAX_GPS_DISTANCE_METER`), Plausibilitätsprüfungen für Geschwindigkeit (`GPS_MAX_SPEED`) und DOP-Grenzwerte (`GPS_DOP_MAX_THRESHOLD`).

#### 2. `gpmf_exif.py` (Metadaten-Verwaltung & Wrapper `EExiv2`)
Kapselt den Zugriff auf Bildmetadaten zur Bereinigung, Tagging und Geokodierung:
* **Klasse `EExiv2`:** Wrapper um `ImageData` (`pyexiv2`) mit automatischem Encoding-Fallback (UTF-8 / ISO-8859-1) und temporärer Datei-Sicherung (`~` Backups).
* **Zeit- & Zeitzonen-Harmonisierung:** Berechnet und korrigiert Abweichungen in `DateTimeOriginal`, `OffsetTimeOriginal` und `TimezoneOffset` unter Einbeziehung von GPS-Zeitstempeln und Geolocation-Zeitzonen.
* **Automatisches Geo-Tagging:** Schreibt exakte DMS-Koordinaten, Höhenwerte und ermittelte Ortsnamen in IPTC-/XMP-Felder sowie als hierarchische Pfade (z. B. `Länder/DE`, `Orte/Deutschland/Berlin`, `Personen/...`).

#### 3. `gpmf_ffmpeg.py` (FFmpeg-Integration)
Bietet eine saubere Schnittstelle zur Interaktion mit Multimediabefehlen:
* **Klasse `FfmpegConfig`:** Automatische Ermittlung von FFmpeg/FFprobe aus Konfigurationsdateien (`gpmf2file.conf`), Arbeitsverzeichnissen oder dem System-`PATH`.
* **Klasse `FfmpegTools`:** Führt FFmpeg/FFprobe-Subprozesse aus, parsed Versionsnummern und steuert das Ausgabe-Format (JSON-Kompatibilität ab v4.0+).
* **Singleton-Funktion `get_ffmpeg_service()`:** Garantiert eine wiederverwendbare, globale Instanz der Tools ohne Nutzung globaler Variablen.

#### 4. `gpmf_geo.py` (Geodatenbanken & Spatial Queries)
Stellt die räumlichen Analysewerkzeuge und Datenbank-Klassen bereit:
* **Klasse `BaseGeoDB`:** Abstrakte Generics-Basisklasse mit Thread-sicherem Singleton-Pattern (Double-Checked Locking Pool) und KDTree-Indizierung.
* **Verwaltung Administrativer Hierarchien:** Indizierung und Normalisierung von ADM1 bis ADM4 Ebenen zur Vermeidung von Redundanzen bei Stadtstaaten oder unvollständigen Gemeindeeinträgen.
* **Spezifische DB-Implementierungen:**
  * `GeoNamesDB` & `GeoAlternatenamesDB`: Haupt- und Sprachdatenbanken für weltweite Ortsnamen.
  * `GeoCitiesDB`: Spezialisierte Datenbank für Städte mit direkter Alpha-2 Ländercodierung.
  * `GeoCountriesDB`: Länderinformationen und Zuordnungen.

#### 5. `gpmf_gpmf.py` (GPMF-Parser & Telemetrie-Extraktion)
Zentrales Modul zur Analyse und Extraktion von Binärdaten aus dem GoPro Metadata Format (GPMF), wie es in MP4-Videostreams eingebettet ist:
* **Klasse `GpmfParser`:** Liest den Binärstrom des Metadaten-Tracks (FourCC `gpmd`) aus MP4-Dateien aus und zerlegt ihn in die hierarchische KLV-Struktur (Key-Length-Value).
* **Telemetrie-Extraktion:** Extrahiert Sensordaten wie GPS (`GPS5` / `GPS9`), Beschleunigungsmesser (`ACCL`), Gyroskop (`GYRO`), Magnetometer (`MAGN`) und Kamera-Temperaturen (`TMP`).
* **GPS-Fixing & Glättung:** Filtert ungültige GPS-Punkte anhand von 2D/3D-Fixes (`GPSF`), Satellitenanzahl (`GPSS`) und DOP-Werten (`DGPS`). Führt bei Unterbrechungen Interpolations- und Bereinigungsroutinen durch.
* **Konvertierung:** Exportiert extrahierte Telemetriedaten in standardisierte Formate wie GPX, KML, CSV oder GeoJSON.

#### 6. `gpmf_file.py` (Datei- & Verzeichnisverwaltung für Medien)
Stellt abstrakte und konkrete Datenstrukturen zur Repräsentation von Medienressourcen im Dateisystem zur Verfügung:
* **Klasse `MediaFile`:** Basisklasse für alle physischen Medienelemente. Bietet Methoden zur Dateigrößenbestimmung, Prüfsummenberechnung (MD5/SHA256), Zeitstempel-Analyse und sicheren Dateideskriptor-Verarbeitung.
* **Klasse `GoProVideoFile`:** Spezialisierte Repräsentation von GoPro-Videodateien. Erkennt automatisch Dateityp (AVC/HEVC), Kapitelnummerierungen (z. B. `GH010001.MP4` vs. `GH020001.MP4`), Looping-Dateien und verknüpft zusammengehörige Video-Sequenzen zu logischen Aufnahmesessions.
* **Klasse `ImageFile`:** Repräsentation von Standbildern (JPG/PNG) mit direkter Anbindung an das `gpmf_exif`-Modul zur Schnellauslese von Exif-Metadaten.

#### 7. `gpmf_track.py` (Räumlich-zeitliche Trajektorien & GPS-Tracks)
Strukturierte Verwaltung und mathematische Analyse von Ortsverläufen:
* **Klasse `GPSTrackPoint`:** Repräsentiert einen einzelnen Geodatenpunkt inklusive Breitengrad, Längengrad, Höhe, Zeitstempel (UTC), Geschwindigkeit, Kurs (Heading) und DOP-Qualitätsmerkmalen.
* **Klasse `GPSTrackSegment`:** Zusammenhängende Folge von Trackpoints. Bietet Berechnungsfunktionen für:
  * Gesamtdistanz (via Haversine-Formel und Vincenty-Ellipsoid-Berechnung)
  * Durchschnitts- und Höchstgeschwindigkeit
  * Kumulierte Höhenmeter (Aufstieg/Abstieg)
  * Pausen- und Stillstandserkennung
* **Klasse `GPSTrack`:** Verwaltet mehrere Segmente (z. B. unterbrochene Aufnahmen oder Mehrtagestouren) und bietet Export- sowie Vereinfachungsfunktionen (z. B. Ramer-Douglas-Peucker-Algorithmus).

#### 8. `gpmf_dem.py` (Digital Elevation Model / Höhendaten-Dienste)
Verarbeitung und Anreicherung von Geokoordinaten mit präzisen Geländehöhen:
* **Klasse `DEMProvider`:** Schnittstelle zur Abfrage lokaler Raster-Höhendateien (z. B. SRTM, HGT-Dateien, GeoTIFF) sowie externer Web-APIs.
* **Höhen-Korrektur:** Abgleich von ungenauen GPS-Höhenwerten mit dem tatsächlichen digitalen Geländemodell, um barometrische oder geometrische Messfehler zu minimieren.

#### 9. `gpmf_tz.py` (Zeitzonen- & Datumsauflösung)
Präzise Bestimmung von Zeitzonen anhand räumlicher und zeitlicher Daten:
* **Klasse `TimezoneResolver`:** Ermittelt anhand von Koordinaten (Latitude/Longitude) unter Nutzung lokaler Shapefiles/KD-Trees die exakte IANA-Zeitzone (z. B. `Europe/Berlin`).
* **Sommerzeit- & Offset-Berechnung:** Bestimmt für jeden historischen oder aktuellen Zeitstempel den genauen UTC-Offset (inklusive Wechsel zwischen Normalzeit und Sommerzeit) zur korrekten Eintragung in die EXIF/XMP-Tags (`OffsetTimeOriginal`).

### Architektur & Integrationsmodell

                    +------------------------+
                    |      gpmf_const        |
                    +-----------+------------+
                                |
        +-----------------------+-----------------------+
        |                       |                       |
+-------v------+        +-------v------+        +-------v------+
|  gpmf_ffmpeg |        |   gpmf_geo   |        |   gpmf_dem   |
+-------+------+        +-------+------+        +-------+------+
        |                       |                       |
        |               +-------v------+                |
        |               |   gpmf_tz    |                |
        |               +-------+------+                |
        |                       |                       |
+-------v-----------------------v-----------------------v-------+
|                      gpmf_exif / gpmf_file                    |
+-------------------------------+-------------------------------+
                                |
                        +-------v------+
                        |  gpmf_track  |
                        +-------+------+
                                |
                        +-------v------+
                        |  gpmf_gpmf   |
                        +--------------+

Konfiguration & Basiskomponenten (gpmf_const, gpmf_ffmpeg): Stellen Systempfade, Standard-Schwellenwerte und externe Executables für alle übergeordneten Module bereit.

Räumlich-Zeitliche Kontextauflösung (gpmf_geo, gpmf_dem, gpmf_tz): Liefern basierend auf Koordinaten die Geofaktorisierung (Städte, Länder, Höhen, IANA-Zeitzonen).

Medien- & Dateiverwaltung (gpmf_file, gpmf_exif): Kapseln physische Dateien und wenden ermittelte Raum-Zeit-Metadaten auf Exif-, IPTC- und XMP-Strukturen an.

Telemetrie- & Trackprozessierung (gpmf_track, gpmf_gpmf): Verarbeiten Roh-Binärstreams aus Videos, extrahieren Trajektorien und synchronisieren diese über die gesamte Pipeline hinweg.

### Abhängigkeiten

#### Externe Frameworks (PyPI)
- `gpxpy`
- `lxml`
- `numpy`
- `overpy`
- `pandas`
- `pyexiv2`
- `requests`
- `scipy`
- `tzlocal`
- `yaml`

#### Eigene Frameworks
- `rpg_geo`
- `rpg_gpx`
- `rpg_utils`

---

### Öffentliche Klassen

* **`EExiv2`**: Ein High-Level Wrapper um `pyexiv2` zur Handhabung, Korrektur, Synchronisation und Anreicherung von EXIF-, IPTC- und XMP-Bildmetadaten.
* **`FfmpegConfig`**: Verwaltet Pfade und Ausführungsoptionen für das `ffmpeg`- und `ffprobe`-Ökosystem unter Berücksichtigung von Systemkonfigurationen und Umgebungsvariablen.
* **`FfmpegTools`**: Bietet Low-Level- und Subprozess-Schnittstellen zur Interaktion mit `ffmpeg`/`ffprobe` inklusive automatischer Versions- und JSON-Standard-Erkennung.
* **`BaseGeoDB`**: Abstrakte Basisklasse mit Singleton-Muster für Performanz-optimierte räumliche K-D-Baum-Suche in Geodaten.
* **`BaseGeoNamesDB`**: Spezifische Basisklasse zur Verwaltung von GeoNames-Datensätzen mit flexiblem Lifecycle für dynamisches Nachladen von Ländern.
* **`GeoNamesDB`**: Hauptdatenbank zur Speicherung und Abfrage von GeoNames-Einträgen.
* **`GeoAlternatenamesDB`**: Datenbank zur Verwaltung lokalisierter Alternativnamen von Orten und administrativen Ebenen.
* **`GeoCitiesDB`**: Kompakte Datenbank zur schnellen städtebasierten Standort- und Zeitzonenbestimmung.
* **`GeoCountriesDB`**: Datenbank zur Validierung und Übersetzung von Ländercodes (ISO Alpha-2 / Alpha-3) und Namen.
* **`CountryResolver`**: Hilfsklasse zur Bestimmung von Ländernamen und ISO-Codes anhand geographischer Koordinaten oder Ländercodes.
* **`Elevation`**: Dienstklasse zur Abfrage von Höhendaten über K-D-Bäume oder externe Online-Services.
* **`GeoLocator`**: Zentraler Aggregationsdienst zur Ermittlung vollständiger Adress- und Ortsobjekte (`GeoInfo`) für Geokoordinaten mit In-Memory-Caching.
* **`GeoOSM`**: Schnittstelle zur Overpass-API für OpenStreetMap-Abfragen.

---

### Öffentliche Methoden nach Klassen

#### `EExiv2`

* **`__init__(file: str | Path, verbose: bool = False)`**
  * :param file: (str | Path) Pfad zur Zielbilddatei.
  * :param verbose: (bool) Bei True werden erweiterte Log-Meldungen ausgegeben.
  * *Beschreibung:* Initialisiert das Objekt, lädt die Datei und liest EXIF-, IPTC-, XMP- sowie ICC-Metadaten ein.

* **`read_exif() -> dict`**
  * *Beschreibung:* Liest EXIF-Daten aus und wendet Automatikkorrekturen (z. B. Datumsformate, Zeitzonen-Offsets) an.

* **`read_iptc() -> dict`**
  * *Beschreibung:* Liest IPTC-Daten aus und synchronisiert Erstellungsdaten basierend auf EXIF-Referenzen.

* **`read_xmp() -> dict`**
  * *Beschreibung:* Liest XMP-Daten aus und analysiert spezifische Personen- oder Region-Tags.

* **`close()`**
  * *Beschreibung:* Schließt die pyexiv2-Bildressource explizit.

* **`read_creationdate(point: GeoPoint | None = None) -> datetime | None`**
  * :param point: (GeoPoint | None) Optionaler Punkt zur Bestimmung der Zeitzone im Fallback-Szenario.
  * :param return: (datetime | None) Erstellungsdatum der Aufnahme als tz-aware oder naives Datetime-Objekt.
  * *Beschreibung:* Extrahiert den Aufnahmezeitpunkt unter Einbeziehung proprietärer und EXIF-Standard-Offsets.

* **`read_geolocation() -> GeoPoint | None`**
  * :param return: (GeoPoint | None) Geokoordinaten samt Höhe als `GeoPoint` oder None.
  * *Beschreibung:* Extrahiert und konvertiert GPS-Koordinaten aus den EXIF-Tags.

* **`write_exif(creation_date: datetime | None = None, creation_author: str | None = None, nearest_point: GeoPointTime | None = None, target_tz: tzinfo | None = None) -> GeoInfo | None`**
  * :param creation_date: (datetime | None) Zu schreibendes Aufnahmedatum.
  * :param creation_author: (str | None) Autoren- / Künstler-Name.
  * :param nearest_point: (GeoPointTime | None) Zugeordneter GPS-Punkt.
  * :param target_tz: (tzinfo | None) Ziel-Zeitzone.
  * :param return: (GeoInfo | None) Adressinformationen des geschriebenen Geopunkts.
  * *Beschreibung:* Schreibt konsistent EXIF-, IPTC- und XMP-Daten inklusive Geolocation und Adress-Keywords in das Bild.

---

#### `FfmpegConfig`

* **`__init__(ffmpeg=None, ffprobe=None, verbose: bool = False)`**
  * :param ffmpeg: (Any) Vorgegebener Pfad zu FFmpeg.
  * :param ffprobe: (Any) Vorgegebener Pfad zu FFprobe.
  * :param verbose: (bool) Steuert Verbose-Ausgaben.
  * *Beschreibung:* Initialisiert die Konfiguration und liest Pfade aus Konfigurationsdateien oder dem System-PATH.

* **`load_config_file(l_ffmpeg, l_ffprobe)`**
  * :param l_ffmpeg: (Any) Fallback-Pfad ffmpeg.
  * :param l_ffprobe: (Any) Fallback-Pfad ffprobe.
  * *Beschreibung:* Lädt System-Konfigurationsdateien bezüglich benutzerdefinierter Executable-Pfade.

---

#### `FfmpegTools`

* **`__init__(config: FfmpegConfig, verbose: bool = False)`**
  * :param config: (FfmpegConfig) Konfigurationsobjekt.
  * :param verbose: (bool) Steuert Log-Details.
  * *Beschreibung:* Initialisiert das Toolset, validiert die Ausführbarkeit der Binaries und prüft die Version.

* **`call_ffmpeg(args: list[str]) -> Result`**
  * :param args: (list[str]) Argumentliste für FFmpeg.
  * :param return: (Result) Ausführungsergebnis mit Code, Stdout und Stderr.
  * *Beschreibung:* Führt FFmpeg mit Argumenten im Hintergrund aus.

* **`call_ffprobe(args: list[str]) -> Result`**
  * :param args: (list[str]) Argumentliste für FFprobe.
  * :param return: (Result) Ausführungsergebnis mit Code, Stdout und Stderr.
  * *Beschreibung:* Führt FFprobe mit Argumenten im Hintergrund aus.

* **`to_int(value: str | None) -> int | None`**
  * :param value: (str | None) String-Wert.
  * :param return: (int | None) Konvertierter Integer oder None.
  * *Beschreibung:* Hilfsmethode zur sicheren Integer-Konvertierung.

* **`run_cmd_raw(cmd, args) -> Result`**
  * :param cmd: Executable-Pfad.
  * :param args: Argumente.
  * :param return: (Result) Ergebnis-Tupel.
  * *Beschreibung:* Führt einen Systembefehl ohne Konsolenfenster aus.

---

#### `BaseGeoDB`

* **`search(latitude: float, longitude: float, neighbors: int = 7, sort: str = '', ascending: bool = True, language: str = 'de') -> list[GeoNeighbor] | None`**
  * :param latitude: (float) Breitengrad.
  * :param longitude: (float) Längengrad.
  * :param neighbors: (int) Trefferanzahl.
  * :param sort: (str) Sortierfeld.
  * :param ascending: (bool) Sortierreihenfolge.
  * :param language: (str) Sprachkürzel.
  * :param return: (list[GeoNeighbor] | None) Liste der nächstgelegenen Ortseinträge.
  * *Beschreibung:* Führt eine Nächste-Nachbarn-Suche im K-D-Baum durch.

* **`get_elevation(latitude: float | None = None, longitude: float | None = None) -> float | None`**
  * :param latitude: (float | None) Breitengrad.
  * :param longitude: (float | None) Längengrad.
  * :param return: (float | None) Geländehöhe in Metern.
  * *Beschreibung:* Ermittelt die Höhe für eine Koordinate im K-D-Baum.

* **`get_tzinfo(latitude: float | None, longitude: float | None) -> tzinfo | None`**
  * :param latitude: (float | None) Breitengrad.
  * :param longitude: (float | None) Längengrad.
  * :param return: (tzinfo | None) Zeitzonen-Objekt (`ZoneInfo`).
  * *Beschreibung:* Liefert die IANA-Zeitzone für Geokoordinaten.

---

#### `BaseGeoNamesDB`

* **`ensure_country_loaded(alpha2: str) -> bool`**
  * :param alpha2: (str) ISO 3166-1 Alpha-2 Code.
  * :param return: (bool) True, wenn das Land verfügbar/geladen ist.
  * *Beschreibung:* Garantiert das Vorhandensein eines Landes im In-Memory-Baum.

* **`add_country(alpha2: str) -> bool`**
  * :param alpha2: (str) ISO 3166-1 Alpha-2 Code.
  * :param return: (bool) True bei Erfolgsfall.
  * *Beschreibung:* Lädt Daten für ein spezifisches Land dynamisch nach.

---

#### `GeoCitiesDB`

* **`alpha2_from_coords(latitude: float, longitude: float) -> str | None`**
  * :param latitude: (float) Breitengrad.
  * :param longitude: (float) Längengrad.
  * :param return: (str | None) Ländercode (ISO Alpha-2).
  * *Beschreibung:* Ermittelt den Ländercode direkt anhand der städtischen Geodatenbank.

---

#### `CountryResolver`

* **`iso3_and_name(alpha2: str | None, language: str = 'de') -> tuple[str | None, str | None]`**
  * :param alpha2: (str | None) Ländercode (Alpha-2).
  * :param language: (str) Zielsprache.
  * :param return: (tuple[str | None, str | None]) Tupel aus ISO3-Code und lokalisiertem Ländernamen.
  * *Beschreibung:* Löst Alpha-2-Codes in ISO3-Codes und Namen auf.

* **`alpha2_from_coords(latitude: float, longitude: float) -> str | None`**
  * :param latitude: (float) Breitengrad.
  * :param longitude: (float) Längengrad.
  * :param return: (str | None) Ländercode Alpha-2.
  * *Beschreibung:* Bestimmt den Ländercode aus Geokoordinaten via `GeoCitiesDB`.

---

#### `GeoLocator`

* **`get_geonames_information(latitude: float, longitude: float) -> GeoInfo | None`**
  * :param latitude: (float) Breitengrad.
  * :param longitude: (float) Längengrad.
  * :param return: (GeoInfo | None) Vollständige Standort- und Adressstruktur.
  * *Beschreibung:* Ermittelt gecacht und hochperformant komplexe Ortsinformationen zu einer Koordinate.

---

### Globale Service-Funktionen

* **`get_ffmpeg_service(verbose: bool = False) -> FfmpegTools`**
  * :param verbose: (bool) Verbose-Flag.
  * :param return: (FfmpegTools) Singleton-Instanz von `FfmpegTools`.
  * *Beschreibung:* Liefert den globalen Service-Zugriff auf die FFmpeg-Tools.

---
