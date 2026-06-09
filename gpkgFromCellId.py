#!/usr/bin/env python3
"""
gpkgFromCellId - Generate a GeoPackage from mobile cell IDs.

Usage:
    gpkgFromCellId -c '204:08:30501:17986829' -o output.gpkg
    gpkgFromCellId -f cells.txt -o output.gpkg
    gpkgFromCellId -c '204:08:30501:17986829' -c '204:08:30501:12345678' -o output.gpkg

Cell ID format: MCC:MNC:TAC:ECI
"""

import sys
import argparse
import geopandas as gpd
from shapely.geometry import Point
from wloc_api.wloc import QueryMobile


def parse_args():
    parser = argparse.ArgumentParser(
        prog="gpkgFromCellId",
        description=(
            "Query mobile cell IDs (MCC:MNC:TAC:ECI) and write results to a GeoPackage."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpkgFromCellId -c '204:08:30501:17986829' -o output.gpkg\n"
            "  gpkgFromCellId -f cells.txt -o output.gpkg\n"
            "  gpkgFromCellId -c '204:08:30501:17986829' -c '204:16:12345:99887766' -o output.gpkg\n"
        ),
    )
    parser.add_argument(
        "-c", "--cell",
        metavar="MCC:MNC:TAC:ECI",
        action="append",
        dest="cells",
        default=[],
        help=(
            "Cell ID in MCC:MNC:TAC:ECI format. "
            "Can be specified multiple times for multiple cells."
        ),
    )
    parser.add_argument(
        "-f", "--file",
        metavar="FILE",
        dest="cell_file",
        help="Path to a file containing one cell ID (MCC:MNC:TAC:ECI) per line. "
             "Blank lines and lines starting with '#' are ignored.",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="OUTPUT.gpkg",
        required=True,
        help="Path for the output GeoPackage file.",
    )
    parser.add_argument(
        "-l", "--layer",
        metavar="LAYER",
        default="cells",
        help="Layer name inside the GeoPackage (default: 'cells').",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print extra progress information.",
    )
    return parser.parse_args()


def validate_cell_id(cell_id: str) -> bool:
    """Return True if cell_id has the expected MCC:MNC:TAC:ECI structure."""
    parts = cell_id.strip().split(":")
    if len(parts) != 4:
        return False
    try:
        int(parts[0])   # MCC  – numeric
        int(parts[2])   # TAC  – numeric
        int(parts[3])   # ECI  – numeric
        # MNC may have a leading zero (e.g. '08'), keep as string but must be numeric
        int(parts[1])
    except ValueError:
        return False
    return True


def read_cell_ids_from_file(path: str) -> list[str]:
    """Read cell IDs from a plain-text file (one per line)."""
    cell_ids = []
    with open(path, "r") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not validate_cell_id(line):
                print(
                    f"[WARN] Skipping invalid cell ID on line {lineno}: {line!r}",
                    file=sys.stderr,
                )
                continue
            cell_ids.append(line)
    return cell_ids


def collect_cell_ids(args) -> list[str]:
    """Merge and deduplicate cell IDs from -c flags and/or -f file."""
    seen = set()
    ordered = []

    def add(cell_id: str):
        key = cell_id.strip()
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    # Validate IDs supplied directly on the command line
    for raw in args.cells:
        if not validate_cell_id(raw):
            print(f"[ERROR] Invalid cell ID: {raw!r}", file=sys.stderr)
            sys.exit(1)
        add(raw.strip())

    # IDs from file
    if args.cell_file:
        for cell_id in read_cell_ids_from_file(args.cell_file):
            add(cell_id)

    return ordered


def query_cells(cell_ids: list[str], verbose: bool) -> tuple[list[dict], list[Point]]:
    """
    Query each cell ID via QueryMobile and return parallel lists of
    attribute dicts and Shapely Points.
    """
    records = []
    geometries = []
    failed = []

    total = len(cell_ids)
    for idx, cell_id in enumerate(cell_ids, 1):
        if verbose:
            print(f"[{idx}/{total}] Querying {cell_id} …")
        else:
            print(f"Querying {cell_id} …")

        try:
            network_dict = QueryMobile(cell_id, True)
        except Exception as exc:
            print(f"  [WARN] Query failed for {cell_id}: {exc}", file=sys.stderr)
            failed.append(cell_id)
            continue

        if not network_dict:
            print(f"  [WARN] No result returned for {cell_id}", file=sys.stderr)
            failed.append(cell_id)
            continue

        for key, network in network_dict.items():
            try:
                loc = network.get_location()      # (lat, lon)
                attrs = network.get_all()
                geometry = Point(loc[1], loc[0])  # Shapely Point(lon, lat)
                records.append(attrs)
                geometries.append(geometry)
                if verbose:
                    print(f"  → {key}  lat={loc[0]:.6f}  lon={loc[1]:.6f}")
            except Exception as exc:
                print(
                    f"  [WARN] Could not extract location for {key}: {exc}",
                    file=sys.stderr,
                )
                failed.append(key)

    if failed:
        print(
            f"\n[WARN] {len(failed)} cell(s) could not be resolved: {', '.join(failed)}",
            file=sys.stderr,
        )

    return records, geometries


def write_gpkg(records: list[dict], geometries: list[Point], output: str, layer: str):
    """Write a GeoDataFrame to a GeoPackage."""
    if not records:
        print("[ERROR] No records to write – output file not created.", file=sys.stderr)
        sys.exit(1)

    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")
    gdf.to_file(output, layer=layer, driver="GPKG")
    print(f"\nWrote {len(gdf)} feature(s) to '{output}' (layer: '{layer}').")


def main():
    args = parse_args()

    # Must have at least one source of cell IDs
    if not args.cells and not args.cell_file:
        print(
            "[ERROR] Provide at least one cell ID via -c or a file via -f.",
            file=sys.stderr,
        )
        sys.exit(1)

    cell_ids = collect_cell_ids(args)
    if not cell_ids:
        print("[ERROR] No valid cell IDs found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cell_ids)} unique cell ID(s) to query.\n")

    records, geometries = query_cells(cell_ids, args.verbose)
    write_gpkg(records, geometries, args.output, args.layer)


if __name__ == "__main__":
    main()
