"""
Script Name: save_intersecting_kmls_GREATLAKES.py
Description: takes a large polygon KML drawn in geojson.io and queries the Great_Lakes_aois.gpkg to find and save the intersecting AOI KMLs to a new folder.
Updates processing status in CSV log file.
 - An example for finding the AOIs for Vancouver is included in example_save_intersecting_kmls/

NOTE: modified filepaths to use for the Great Lakes AOIs (2026-04-16)

How to run:
 - cd to this folder in Command Prompt
 - modify user I/O file paths in main() as required
 - run:

EITHER: (checks and updates logfile as needed)
python save_intersecting_kmls_GREATLAKES.py

OR (if you want all intersecting AOI KMLs without checking and modifying the log file):
python save_intersecting_kmls_GREATLAKES.py --ignorelog
"""

from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union
import argparse
from datetime import datetime


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def parse_geojsonio_polygons(kml_path):
    """
    Parse polygons from a KML formatted from the geojson.io tool like:

    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <Polygon>
            <outerBoundaryIs>
              <LinearRing>
                <coordinates>
                  lon,lat
                  lon,lat
                  ...
                </coordinates>
              </LinearRing>
            </outerBoundaryIs>
          </Polygon>
        </Placemark>
      </Document>
    </kml>

    Returns a list of shapely polygon geometries in EPSG:4326
    """
    kml_path = Path(kml_path)
    tree = ET.parse(kml_path)
    root = tree.getroot()
    polygons = []
    coord_nodes = root.findall(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)

    for node in coord_nodes:
        if node.text is None:
            continue
        coord_text = node.text.strip()
        if not coord_text:
            continue
        coords = []
        for line in coord_text.split():
            parts = line.split(",")
            if len(parts)<2:
                continue
            lon = float(parts[0])
            lat = float(parts[1])
            coords.append((lon, lat))
        if len(coords)>=4:
            poly = Polygon(coords)
            if poly.is_valid and not poly.is_empty:
                polygons.append(poly)
    if not polygons:
        raise ValueError(f"No valid polygons found in KML: {kml_path}")
    return polygons


def normalize_aoi_id(aoi_id):
    """
    Convert aoi_id to expected filename (ex. U_UTM10_0001 to U_UTM10_0001.kml)
    """
    aoi_id = str(aoi_id).strip()
    aoi_id += ".kml"
    return aoi_id


def copy_matching_kmls(
    log_csv,
    date_str,
    ignorelog,
    site_tag,
    input_kml,
    aois_gpkg,
    aois_kml_root,
    output_folder
):
    """
    1. Read polygons from the input KML
    2. Find intersecting polygons in aois.gpkg
    3. Copy corresponding KML files from aois_kml_root into output_folder
    """
    output_folder.mkdir(parents=True, exist_ok=True)

    # parse input area
    query_polys = parse_geojsonio_polygons(input_kml)
    query_geom = unary_union(query_polys)
    query_gdf = gpd.GeoDataFrame(
        {"geometry": [query_geom]},
        crs="EPSG:4326"
    )
    aois = gpd.read_file(aois_gpkg)
    log = gpd.read_file(log_csv)

    if aois.crs != query_gdf.crs:
        query_gdf = query_gdf.to_crs(aois.crs)
    query_geom = query_gdf.geometry.iloc[0]

    # get intersections
    matches = aois[aois.geometry.intersects(query_geom)].copy()
    print(f"Found {len(matches)} intersecting AOIs")
    copied = 0
    missing = []
    skipped = []
    for aoi_id in matches["aoi_id"]:
        kml_name = normalize_aoi_id(aoi_id)
        found = list(aois_kml_root.rglob(kml_name))
        cell_val = log.loc[log['aoi_id'] == aoi_id, 'date_copied'].iloc[0]
        is_empty = pd.isna(cell_val) or cell_val == ''

        if not found:
            missing.append(kml_name)
            continue
        if not is_empty and not ignorelog:
            skipped.append(kml_name)
            continue
        else:
            src = found[0]
            dst = output_folder/src.name
            shutil.copy2(src, dst)
            copied += 1
            log.loc[log['aoi_id'] == aoi_id, ['date_copied', 'site_tag']] = [date_str, site_tag] # update log_csv

    print(f"Copied {copied} KML files to: {output_folder}")
    if missing:
        print("\nMissing KML files:")
        for name in missing:
            print(f"  {name}")
    if skipped:
        print("\nSkipped KML files (already copied for processing):")
        for name in skipped:
            print(f"  {name}")

    # save to log
    if copied >= 1 and not ignorelog:
        log.to_csv(log_csv, index=False, encoding='utf-8', header=['aoi_id', 'date_copied', 'site_tag'])
        print(f"Updated log_csv: {log_csv}")

    return matches


# def initialize_logfile(log_csv, aois_gpkg):
#     """
#     To be run only once to set up the file on the P:drive.
#     """
#     aois = gpd.read_file(aois_gpkg)
#     df = pd.DataFrame({
#         'aoi_id': aois['aoi_id']
#     })
#     df['date_copied'] = None
#     df['site_tag'] = None
#     df.to_csv(log_csv, index=False, encoding='utf-8', header=['aoi_id', 'date_copied', 'site_tag'])


def main():
    parser = argparse.ArgumentParser(description="args")
    parser.add_argument( # Ignores the log_csv: add argument to force all AOIs to be copied into the new folder regardless of download status in the P:drive log_csv, and not update the log_csv file
        "-i",
        "--ignorelog",
        action = "store_true",
        help = "Download all intersecting AOIs regardless of P:drive log_csv status."
    )
    args = parser.parse_args()
    if args.ignorelog:
        print("Downloading all intersecting AOIs regardless of P:drive log_csv status.")

    # specify user I/O paths
    input_kml = Path(r"P:\CoastSat\KMLs\example.kml") # draw a KML over the area you want to cover in geojson.io
    aois_gpkg = Path("Great_Lakes_aois.gpkg")
    aois_kml_root = Path("Great_Lakes_aois_kml")
    output_folder = Path(r"D:\Jaime\20260415_example_L_S2_1984_2026_analysis_batch\selected_kmls")

    # direct to the P:drive log file we all have access to: do not change this unless the file has been moved
    log_csv = Path(r"P:\CoastSat\AOIs_Great_Lakes\log_GREATLAKES.csv")
    if not log_csv.exists:
        raise FileNotFoundError(f"Existing log file not found: {log_csv}")
    now = datetime.now()
    now = now.isoformat()

    matches = copy_matching_kmls(
        log_csv=log_csv,
        date_str=now,
        ignorelog=args.ignorelog,
        site_tag=input_kml.stem,
        input_kml=input_kml,
        aois_gpkg=aois_gpkg,
        aois_kml_root=aois_kml_root,
        output_folder=output_folder
    )

    # optional: save intersecting AOIs as a gpkg to view all selections at once for QA
    # matches.to_file(r"example_save_intersecting_kmls\selected_aois.gpkg", driver="GPKG")


if __name__=="__main__":
    main()