import os
import geopandas as gpd
from shapely.geometry import Point
from datetime import datetime
from dateutil.parser import parse
import json
import argparse

# Definieer een consistent schema met alle mogelijke velden in de gewenste volgorde
consistent_schema = [
    'deviceSerialNumber', 'deviceName', 'deviceTime', 'latitude', 'longitude', 'altitude', 
    'batteryLevelPercent', 'deviceModel', 'accuracy', 'mdmOverride', 'appVersion',
    'missionId', 'recordNumber', 'groupNumber', 'mcc', 'mnc', 'tac', 'eci',
    'earfcn', 'pci', 'rsrp', 'rsrq', 'ta', 'servingCell', 'lteBandwidth', 'provider', 
    'signalStrength', 'slot', 'snr'
]

integer_fields = ['recordNumber', 'groupNumber', 'mcc', 'mnc', 'tac', 'eci',  'earfcn', 'pci', 'rsrp', 'rsrq', 'ta', 'signalStrength', 'slot', 'snr']

# Batch-grootte (bijv. schrijf na elke 1000 records)
BATCH_SIZE = 100

# Verwerk een record en maak een geometrie aan
def verwerk_record(record):
    # Voeg ontbrekende velden toe met None en zet velden in de juiste volgorde
    formatted_record = {key: record.get(key, None) for key in consistent_schema}

    # Converteer deviceTime naar datetime
    device_time_str = formatted_record.get('deviceTime')
    if device_time_str:
        try:
            formatted_record['deviceTime'] = parse(device_time_str)
        except ValueError:
            print(f"Onjuist datumformaat voor deviceTime: {device_time_str}")
            formatted_record['deviceTime'] = None

        # Specificeer de velden die integer moeten zijn

    # Converteer deze velden naar integer indien mogelijk
    for field in integer_fields:
        value = formatted_record.get(field)
        if value is not None:
            try:
                formatted_record[field] = int(value)
            except (ValueError, TypeError):
                print(f"Fout bij het converteren van {field} naar integer: {value}")
                formatted_record[field] = None

    latitude = formatted_record.get('latitude')
    longitude = formatted_record.get('longitude')

    # Maak geometrieën aan (punt) met uitzondering van missende locatiegegevens
    try:
        if latitude is None or longitude is None:
            raise ValueError("Latitude of longitude ontbreekt.")
        geometry = Point(longitude, latitude)
    except (ValueError, TypeError) as e:
        print(f"Fout bij het maken van punt voor record {formatted_record.get('recordNumber')}: {e}")
        return None, None
    
    return formatted_record, geometry

# Sla records op in een GeoPackage-bestand
def sla_op_in_geopkg(records, geometries, output_file, laagnaam):
    # Maak een GeoDataFrame van de batch
    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")

    # Controleer of het bestand al bestaat
    bestand_bestaat = os.path.exists(output_file)

    # Controleer of de laag al bestaat in het bestand
    if not bestand_bestaat:
        print(f"Maak nieuw GeoPackage-bestand of nieuwe laag: {output_file}")
        gdf.to_file(output_file, layer=laagnaam, driver="GPKG")
    else:
        print(f"Voeg gegevens toe aan bestaande laag in GeoPackage-bestand: {output_file}")
        # Laag bestaat, lees bestaande gegevens en voeg de nieuwe gegevens toe
        gdf.to_file(output_file, layer=laagnaam, driver="GPKG",mode = 'a')

# Hoofdfunctie voor het verwerken van grote JSON-bestanden
def main():
    # Commandline argumenten ophalen
    parser = argparse.ArgumentParser(description="JSON naar GeoPackage converter voor grote bestanden met batching.")
    parser.add_argument("input_file", help="Pad naar het JSON-bestand")
    parser.add_argument("output_file", help="Pad naar het GeoPackage-bestand")
    parser.add_argument("--layer", default="LteRecords", help="Naam van de laag in het GeoPackage-bestand")

    args = parser.parse_args()

    records = []
    geometries = []
    record_count = 0

    # Verwerk het JSON-bestand regel voor regel
    with open(args.input_file, 'r') as file:
        for line in file:
            # Lees elke regel als JSON en pak het data-gedeelte
            try:
                record = json.loads(line)['data']
            except json.JSONDecodeError:
                print(f"Onjuist JSON-formaat in regel: {line}")
                continue
            
            # Verwerk het record
            formatted_record, geometry = verwerk_record(record)
            if formatted_record is None or geometry is None:
                continue  # Skip records met ongeldige locatiegegevens

            records.append(formatted_record)
            geometries.append(geometry)
            record_count += 1

            # Zodra de batchgrootte is bereikt, schrijf naar de GeoPackage
            if len(records) >= BATCH_SIZE:
                print(f"Schrijft batch van {BATCH_SIZE} records naar {args.output_file}...")
                sla_op_in_geopkg(records, geometries, args.output_file, args.layer)
                records = []
                geometries = []

        # Schrijf de overgebleven records als de loop klaar is
        if records:
            print(f"Schrijft laatste batch van {len(records)} records naar {args.output_file}...")
            sla_op_in_geopkg(records, geometries, args.output_file, args.layer)

    print(f"Gegevens succesvol opgeslagen in {args.output_file}. Totaal aantal records: {record_count}")

# Voer het script uit
if __name__ == "__main__":
    main()

