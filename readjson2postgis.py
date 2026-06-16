#!/usr/bin/env python3
"""
readjson2postgis.py

Importeert locatie-/cel-records uit een continu aangroeiend JSON-lines
bestand (zoals gebruikt door readjson.py) direct in een PostGIS-tabel.

In tegenstelling tot readjson.py (dat steeds een GeoPackage opnieuw
inleest/aanmaakt), is dit script bedoeld om herhaaldelijk te draaien op
een bestand dat blijft groeien en strikt op deviceTime gesorteerd is:

  1. Bij de eerste run wordt het hele bestand verwerkt.
  2. Bij volgende runs wordt eerst de hoogste 'deviceTime' uit de
     PostGIS-tabel opgevraagd.
  3. Met een binaire zoekactie (binary search) op byte-offsets wordt
     direct het punt in het JSON-bestand gevonden vanaf waar nieuwe
     records beginnen, zodat het bestand niet vanaf het begin gelezen
     hoeft te worden (belangrijk bij grote bestanden).
  4. Records worden in batches ingevoegd met
     'INSERT ... ON CONFLICT DO NOTHING', zodat eventuele records die
     rond het hervattingspunt dubbel worden ingelezen niet dubbel in de
     database belanden.

Gebruik
-------
    python3 readjson2postgis.py data.json --dsn postgresql://user:pass@host:5432/dbnaam
    python3 readjson2postgis.py data.json --dsn $POSTGIS_DSN --table lte_records

Vereisten
---------
    pip install psycopg2-binary python-dateutil

Schema-evolutie
---------------
Het brondata-formaat van de logging-app is in de loop van de tijd
uitgebreid (bijv. versie 1.3.0 -> 2.3.0): nieuwe messageTypes
(DeviceStatus, PhoneState, NrRecord, ...) en nieuwe velden (GNSS-/
netwerk-locatie, 5G NR celinfo, enz.). CONSISTENT_SCHEMA bevat de unie
van de velden uit oudere en nieuwere bestanden, plus 'messageType' en
'version' van het bovenste niveau.

Bij elke run worden ontbrekende kolommen met
'ALTER TABLE ... ADD COLUMN IF NOT EXISTS' toegevoegd aan de tabel. Dit
werkt zowel voor een nieuwe tabel als voor een tabel die ooit met een
eerdere (kleinere) versie van dit schema is aangemaakt. Records uit
oudere bestanden die een veld niet kennen, krijgen voor die kolom NULL.

Belangrijke aannames (controleer deze voor jouw data!)
--------------------------------------------------------
  * Het JSON-bestand is (vrijwel) strikt gesorteerd op 'deviceTime'.
    Kleine afwijkingen worden opgevangen met RESUME_MARGIN_SECONDS.
  * UNIQUE_COLUMNS bepaalt wanneer twee records als 'hetzelfde' worden
    gezien (gebruikt voor de UNIQUE-index en ON CONFLICT). Zie de
    toelichting bij die constante hieronder.
  * In tegenstelling tot readjson.py worden records ZONDER latitude/
    longitude niet overgeslagen, maar wel ingevoegd met geom = NULL.
  * 'networkRegistrationInfo' (een geneste lijst, o.a. bij PhoneState)
    wordt als JSON-tekst opgeslagen in een JSONB-kolom, zodat er geen
    data verloren gaat.
"""

import os
import sys
import json
import argparse
from datetime import timedelta, timezone
from dateutil.parser import parse

import psycopg2
import psycopg2.extras
from psycopg2 import sql


# ---------------------------------------------------------------------------
# Schema - unie van de velden uit oudere (v1.x) en nieuwere (v2.x) bestanden
# ---------------------------------------------------------------------------
CONSISTENT_SCHEMA = [
    # Metadata van het bovenste niveau (niet uit 'data')
    'messageType', 'version',

    # Apparaat / sessie
    'deviceSerialNumber', 'deviceName', 'deviceModel', 'appVersion', 'mdmOverride',
    'deviceTime', 'missionId', 'recordNumber', 'groupNumber',

    # Locatie (primaire fix) en kwaliteit
    'latitude', 'longitude', 'altitude', 'accuracy', 'locationAge', 'speed',

    # Locatie - alternatieve bronnen (sinds v2.x)
    'gnssLatitude', 'gnssLongitude', 'gnssAltitude', 'gnssAccuracy',
    'networkLatitude', 'networkLongitude', 'networkAltitude', 'networkAccuracy',

    # Apparaatstatus
    'batteryLevelPercent',

    # Provider / SIM / netwerkregistratie
    'provider', 'simOperator', 'simState', 'plmn', 'mcc', 'mnc', 'tac',
    'networkRegistrationInfo',

    # LTE celinformatie
    'eci', 'earfcn', 'pci', 'rsrp', 'rsrq', 'ta', 'servingCell', 'lteBandwidth',
    'signalStrength', 'slot', 'snr', 'cqi',

    # 5G NR celinformatie (sinds v2.x)
    'nci', 'narfcn', 'ssSinr', 'csiSinr', 'nonTerrestrialNetwork',
]

INTEGER_FIELDS = [
    'recordNumber', 'groupNumber', 'mcc', 'mnc', 'tac', 'eci', 'earfcn', 'pci',
    'rsrp', 'rsrq', 'ta', 'signalStrength', 'slot', 'snr', 'locationAge', 'cqi', 'narfcn',
]

DOUBLE_FIELDS = [
    'latitude', 'longitude', 'altitude', 'accuracy', 'batteryLevelPercent', 'speed',
    'gnssLatitude', 'gnssLongitude', 'gnssAltitude', 'gnssAccuracy',
    'networkLatitude', 'networkLongitude', 'networkAltitude', 'networkAccuracy',
    'ssSinr', 'csiSinr',
]

# Velden met geneste/variabele structuur die als JSON(B) worden opgeslagen.
JSON_FIELDS = ['networkRegistrationInfo']

# 'nci' (5G NR Cell Identity) wordt door de app als string aangeleverd
# (bv. "0"); niet in INTEGER_FIELDS opnemen, gewoon als TEXT bewaren.


# ---------------------------------------------------------------------------
# Configuratie
# ---------------------------------------------------------------------------
DEFAULT_TABLE = "lte_records"
BATCH_SIZE = 1000

# Velden die samen een record uniek identificeren, gebruikt voor de
# UNIQUE-index en ON CONFLICT DO NOTHING.
#
# 'recordNumber' is een doorlopende teller per (deviceSerialNumber,
# missionId) die wordt GEDEELD door alle messageTypes binnen die mission
# (LteRecord, NrRecord, PhoneState, DeviceStatus, ...) - records van
# verschillende celtypes binnen dezelfde mission hebben dus normaal
# gesproken verschillende recordNumber-waarden.
#
# 'deviceTime' is toegevoegd omdat een klein aantal PhoneState-records
# (bv. per SIM-slot) hetzelfde recordNumber kunnen delen, maar wel een
# net andere deviceTime hebben.
#
# Oudere bestanden (v1.x) hebben voor DeviceStatus-records geen missionId
# of recordNumber (beide NULL). COALESCE zorgt dat zulke NULL-waarden voor
# de UNIQUE-index als gelijk worden behandeld - anders telt Postgres elke
# NULL als 'verschillend' en biedt de index geen bescherming tegen
# duplicaten bij het opnieuw inlezen van de overlapmarge.
UNIQUE_COLUMNS = ["deviceSerialNumber", "missionId", "recordNumber", "deviceTime"]

UNIQUE_COLUMN_DEFAULTS = {
    "missionId": sql.SQL("''"),
    "recordNumber": sql.SQL("-1"),
}


def _unique_kolom_expr(kolom):
    """SQL-expressie voor 'kolom' binnen de UNIQUE-index / ON CONFLICT-doel."""
    default = UNIQUE_COLUMN_DEFAULTS.get(kolom)
    if default is not None:
        return sql.SQL("(COALESCE({}, {}))").format(sql.Identifier(kolom), default)
    return sql.Identifier(kolom)


# Marge rond het hervattingspunt om kleine afwijkingen in de sortering
# van het bestand op te vangen. Eventuele dubbele records die hierdoor
# opnieuw worden gelezen, worden door ON CONFLICT DO NOTHING genegeerd.
RESUME_MARGIN_SECONDS = 60


# ---------------------------------------------------------------------------
# Record-verwerking (vergelijkbaar met verwerk_record in readjson.py)
# ---------------------------------------------------------------------------
def formatteer_record(obj):
    """
    Vul ontbrekende velden aan en converteer typen.

    'obj' is de volledige JSON-regel, dus {"version": ..., "messageType": ...,
    "data": {...}}. Velden die niet voorkomen in 'data' - omdat het bestand
    uit een oudere versie van de app komt, of omdat dit messageType ze niet
    gebruikt - worden NULL.
    """
    data = obj.get('data') or {}

    formatted = {}
    for key in CONSISTENT_SCHEMA:
        if key == 'messageType':
            formatted[key] = obj.get('messageType')
        elif key == 'version':
            formatted[key] = obj.get('version')
        elif key in JSON_FIELDS:
            value = data.get(key)
            formatted[key] = json.dumps(value) if value is not None else None
        else:
            formatted[key] = data.get(key, None)

    device_time_str = formatted.get('deviceTime')
    if device_time_str:
        try:
            dt = parse(device_time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            formatted['deviceTime'] = dt
        except (ValueError, TypeError):
            print(f"Onjuist datumformaat voor deviceTime: {device_time_str}")
            formatted['deviceTime'] = None

    for field in INTEGER_FIELDS:
        value = formatted.get(field)
        if value is not None:
            try:
                formatted[field] = int(value)
            except (ValueError, TypeError):
                print(f"Fout bij het converteren van {field} naar integer: {value}")
                formatted[field] = None

    return formatted


# ---------------------------------------------------------------------------
# Binaire zoekactie naar het hervattingspunt in het JSON-lines bestand
# ---------------------------------------------------------------------------
def _vind_regelstart(f, pos):
    """
    Geef de byte-offset van het begin van de regel die byte-positie 'pos'
    bevat: scan terug tot het teken direct na de vorige '\\n', of tot 0.

    Het resultaat is altijd <= pos.
    """
    if pos == 0:
        return 0

    f.seek(pos - 1)
    if f.read(1) == b'\n':
        return pos

    blok = 4096
    cur = pos - 1
    while cur > 0:
        lees = min(blok, cur)
        cur -= lees
        f.seek(cur)
        chunk = f.read(lees)
        idx = chunk.rfind(b'\n')
        if idx != -1:
            return cur + idx + 1

    return 0


def _lees_regel(f, start):
    """Lees de regel die begint op byte-offset 'start'. Geeft (regel, eind) terug."""
    f.seek(start)
    regel = f.readline()
    return regel, f.tell()


def _device_time_van_regel(raw_regel):
    """Geef de deviceTime (timezone-aware) van een JSON-regel, of None."""
    try:
        record = json.loads(raw_regel)['data']
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    device_time_str = record.get('deviceTime')
    if not device_time_str:
        return None

    try:
        dt = parse(device_time_str)
    except (ValueError, TypeError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def zoek_hervattingspositie(pad, vanaf_tijd):
    """
    Binaire zoekactie: geef de byte-offset terug van het begin van de eerste
    regel waarvan deviceTime >= vanaf_tijd. Geeft 0 terug als vanaf_tijd None is,
    of de bestandsgrootte als alle records ouder zijn dan vanaf_tijd.

    Aanname: het bestand is (vrijwel) gesorteerd op deviceTime. Regels die
    niet als geldig JSON met een leesbare deviceTime kunnen worden herkend,
    worden voor de zoekactie overgeslagen.
    """
    if vanaf_tijd is None:
        return 0

    with open(pad, 'rb') as f:
        f.seek(0, os.SEEK_END)
        bestandsgrootte = f.tell()

        lo, hi = 0, bestandsgrootte
        while lo < hi:
            mid = (lo + hi) // 2
            regel_start = _vind_regelstart(f, mid)
            regel, regel_eind = _lees_regel(f, regel_start)

            record_time = _device_time_van_regel(regel)
            if record_time is None or record_time < vanaf_tijd:
                # Onbekend of te oud: deze regel (en alles ervoor) hoeft
                # niet opnieuw gelezen te worden.
                lo = regel_eind
            else:
                hi = regel_start

        return lo


# ---------------------------------------------------------------------------
# PostGIS
# ---------------------------------------------------------------------------
def _sql_type_voor_kolom(kolom):
    if kolom == 'deviceTime':
        return 'TIMESTAMPTZ'
    if kolom in JSON_FIELDS:
        return 'JSONB'
    if kolom in DOUBLE_FIELDS:
        return 'DOUBLE PRECISION'
    if kolom in INTEGER_FIELDS:
        return 'BIGINT'
    return 'TEXT'


def zorg_voor_tabel(conn, table):
    """
    Maak de tabel aan indien nodig, voeg ontbrekende kolommen toe (schema-
    migratie) en zorg voor de benodigde indexen. Idempotent: kan op elke
    run worden aangeroepen, ook tegen een tabel uit een eerdere versie van
    dit script.
    """
    with conn.cursor() as cur:
        try:
            cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Waarschuwing: kon PostGIS-extensie niet aanmaken ({e}). "
                  f"Ga ervan uit dat deze al actief is.")

    # Minimale tabel; alle databasevelden komen via ADD COLUMN IF NOT
    # EXISTS hieronder. Dit pad werkt zowel voor een gloednieuwe tabel als
    # voor migratie van een tabel met een eerdere (kleinere) schemaversie.
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {table} (id BIGSERIAL PRIMARY KEY)")
            .format(table=sql.Identifier(table))
        )
    conn.commit()

    with conn.cursor() as cur:
        for kolom in CONSISTENT_SCHEMA:
            cur.execute(
                sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {type}").format(
                    table=sql.Identifier(table),
                    col=sql.Identifier(kolom),
                    type=sql.SQL(_sql_type_voor_kolom(kolom)),
                )
            )
        cur.execute(
            sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} geometry(Point, 4326)")
            .format(table=sql.Identifier(table), col=sql.Identifier("geom"))
        )
    conn.commit()

    with conn.cursor() as cur:
        # Verwijder een eventuele unieke index uit een eerdere versie van
        # dit script (3 kolommen, zonder deviceTime/COALESCE), zodat
        # ON CONFLICT met de nieuwe definitie (hieronder) werkt.
        cur.execute(
            sql.SQL("DROP INDEX IF EXISTS {idx}").format(idx=sql.Identifier(f"{table}_unique_idx"))
        )
        cur.execute(
            sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {idx} ON {table} ({cols})").format(
                idx=sql.Identifier(f"{table}_unique_idx2"),
                table=sql.Identifier(table),
                cols=sql.SQL(", ").join(_unique_kolom_expr(c) for c in UNIQUE_COLUMNS),
            )
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col})").format(
                idx=sql.Identifier(f"{table}_devicetime_idx"),
                table=sql.Identifier(table),
                col=sql.Identifier("deviceTime"),
            )
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} USING GIST ({col})").format(
                idx=sql.Identifier(f"{table}_geom_idx"),
                table=sql.Identifier(table),
                col=sql.Identifier("geom"),
            )
        )
    conn.commit()


def laatste_device_time(conn, table):
    """Geef de hoogste deviceTime in de tabel, of None als de tabel leeg is."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT MAX({col}) FROM {table}").format(
                col=sql.Identifier("deviceTime"),
                table=sql.Identifier(table),
            )
        )
        row = cur.fetchone()
    return row[0] if row else None


def voeg_batch_toe(conn, table, records):
    """Voeg een batch records toe met ON CONFLICT DO NOTHING. Geeft #ingevoegd terug."""
    if not records:
        return 0

    kolommen = CONSISTENT_SCHEMA + ["geom"]

    # Voor elke rij: eerst alle gewone kolomwaarden, daarna lon/lat tweemaal
    # voor de CASE-expressie die de geometrie opbouwt (of NULL laat).
    template = (
        "(" + ", ".join(["%s"] * len(CONSISTENT_SCHEMA)) +
        ", CASE WHEN %s IS NOT NULL AND %s IS NOT NULL "
        "THEN ST_SetSRID(ST_MakePoint(%s, %s), 4326) ELSE NULL END)"
    )

    values = []
    for r in records:
        rij = [r.get(c) for c in CONSISTENT_SCHEMA]
        lon = r.get('longitude')
        lat = r.get('latitude')
        rij.extend([lon, lat, lon, lat])
        values.append(tuple(rij))

    insert_sql = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({unique_cols}) DO NOTHING"
    ).format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in kolommen),
        unique_cols=sql.SQL(", ").join(_unique_kolom_expr(c) for c in UNIQUE_COLUMNS),
    )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, insert_sql.as_string(conn), values, template=template, page_size=len(values)
        )
        ingevoegd = cur.rowcount
    conn.commit()
    return ingevoegd


# ---------------------------------------------------------------------------
# Bestandsverwerking
# ---------------------------------------------------------------------------
def verwerk_bestand(conn, table, pad, start_offset, batch_size):
    verwerkt = 0
    ingevoegd = 0
    overgeslagen = 0
    batch = []

    with open(pad, 'rb') as f:
        f.seek(start_offset)
        for raw_regel in f:
            try:
                regel = raw_regel.decode('utf-8').strip()
            except UnicodeDecodeError as e:
                print(f"Kan regel niet decoderen, overgeslagen: {e}")
                overgeslagen += 1
                continue

            if not regel:
                continue

            try:
                obj = json.loads(regel)
                if 'data' not in obj:
                    raise KeyError('data')
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"Onjuist JSON-formaat, regel overgeslagen: {e}")
                overgeslagen += 1
                continue

            batch.append(formatteer_record(obj))
            verwerkt += 1

            if len(batch) >= batch_size:
                ingevoegd += voeg_batch_toe(conn, table, batch)
                batch.clear()
                if verwerkt % (batch_size * 10) == 0:
                    print(f"... {verwerkt} regels verwerkt, {ingevoegd} nieuw ingevoegd tot nu toe")

        if batch:
            ingevoegd += voeg_batch_toe(conn, table, batch)

    return verwerkt, ingevoegd, overgeslagen


# ---------------------------------------------------------------------------
# Hoofdprogramma
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Importeer JSON-lines locatie-/cel-records direct in PostGIS, "
                     "met hervatten via binaire zoekactie op deviceTime."
    )
    parser.add_argument("input_file", help="Pad naar het JSON-lines bestand")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("POSTGIS_DSN"),
        help="PostgreSQL connectiestring, bv. 'postgresql://user:wachtwoord@host:5432/database'. "
             "Standaard wordt de omgevingsvariabele POSTGIS_DSN gebruikt.",
    )
    parser.add_argument(
        "--table", default=DEFAULT_TABLE,
        help=f"Naam van de doeltabel (standaard: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE,
        help=f"Aantal records per database-batch (standaard: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--from-start", action="store_true",
        help="Negeer bestaande data in PostGIS en verwerk het hele bestand vanaf het begin",
    )
    parser.add_argument(
        "--skip-table-setup", action="store_true",
        help="Sla het aanmaken/migreren van tabel en indexen over (gebruik als dit al is gedaan)",
    )
    args = parser.parse_args()

    if not args.dsn:
        parser.error("Geef een database-connectie op via --dsn of de omgevingsvariabele POSTGIS_DSN")

    if not os.path.exists(args.input_file):
        parser.error(f"Bestand niet gevonden: {args.input_file}")

    conn = psycopg2.connect(args.dsn)

    try:
        if not args.skip_table_setup:
            zorg_voor_tabel(conn, args.table)

        if args.from_start:
            start_offset = 0
            print("Start vanaf het begin van het bestand (--from-start).")
        else:
            last_time = laatste_device_time(conn, args.table)
            if last_time is None:
                start_offset = 0
                print(f"Tabel '{args.table}' is leeg, start vanaf het begin van het bestand.")
            else:
                vanaf_tijd = last_time - timedelta(seconds=RESUME_MARGIN_SECONDS)
                start_offset = zoek_hervattingspositie(args.input_file, vanaf_tijd)
                print(f"Laatste deviceTime in '{args.table}': {last_time.isoformat()}")
                print(f"Hervat vanaf byte-offset {start_offset} "
                      f"(zoekmarge van {RESUME_MARGIN_SECONDS}s rond {vanaf_tijd.isoformat()}).")

        verwerkt, ingevoegd, overgeslagen = verwerk_bestand(
            conn, args.table, args.input_file, start_offset, args.batch_size
        )

        print(
            f"Klaar. Regels verwerkt: {verwerkt}, "
            f"nieuw ingevoegd: {ingevoegd}, "
            f"overgeslagen (parse-fouten): {overgeslagen}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
