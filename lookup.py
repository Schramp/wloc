import os
import geopandas as gpd
from shapely.geometry import Point
from datetime import datetime
from dateutil.parser import parse

import json
import argparse
from wloc_api.wloc import QueryMobile

from shapely.geometry import Point

def read_json_lines(file_path):
    """Generator to read line-delimited JSON from a file."""
    with open(file_path, 'r') as file:
        for line in file:
            if line.strip():
                yield json.loads(line)

def query_eci_from_json(file_path):
    try:
        requested_queries2 = set() # Keep track of already requested query strings
        requested_queries = {}  # Keep track of already requested query strings

        # Iterate over records using the generator
        skipcount = 0
        for record in read_json_lines(file_path):
            data = record.get("data", {})
            eci = data.get("eci")

            if eci:
                mcc = data.get("mcc", "")
                mnc = data.get("mnc", "")
                tac = data.get("tac", "")

                # Construct the query string in MCC:MNC:TAC:ECI format
                query_string = f"{mcc}:{mnc}:{tac}:{eci}"
                requested_queries2.add(query_string)

                # Check if the query has already been made
                if query_string in requested_queries:
                    skipcount += 1
                    continue
                print(f"Skipping already requested queries: {skipcount}, {len(requested_queries)}")
                skipcount = 0

                print(f"Querying {query_string}...")
                requested_queries[query_string]=None # Mark this query as requested

                # Call the QueryMobile function
                network_dict = QueryMobile(query_string, True)
                for key, network in network_dict.items():
                    requested_queries[key]=network

        
        records = []
        geometries = []

        for key in requested_queries2:
            cellinfo = requested_queries[key]
            L =cellinfo.get_location()
            geometry = Point(L[1], L[0])
            geometries.append(geometry)
            records.append(cellinfo.get_all())

        print(records)
        gdf = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")
        gdf.to_file("opstelpunten.gpkg", layer="opstelpunten", driver="GPKG")



    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise e

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query ECIs from a JSON file.")
    parser.add_argument("file_path", type=str, help="Path to the JSON file.")
    args = parser.parse_args()

    query_eci_from_json(args.file_path)

