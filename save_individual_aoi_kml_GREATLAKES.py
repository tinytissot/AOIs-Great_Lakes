"""
Script Name: save_individual_aoi_kml_GREATLAKES.py
Description: Run after create_RSGrove_partition_overlap_GREATLAKES.py to turn the geopackages into individual KML files (not the *best* storage solution ever, I know).

NOTE: modified Paths for Great Lakes AOIs (2026-04-14)

How to run:
 - modify user I/O paths as required
>>> python save_individual_aoi_kml_GREATLAKES.py
"""

from __future__ import annotations
from pathlib import Path
import re
from xml.sax.saxutils import escape
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon


# Matches names like:
# aois_RSGrove_utm_10_0_U.gpkg
# shoreline_utm_10_0_U_singleparts.gpkg
# anything containing: utm_<zone>_<something>_<band>
UTM_PATTERN = re.compile(r"_([A-Z])_UTM(\d+)$", re.IGNORECASE)


def get_zone_folder_name(file_path: Path):
    """
    Get folder name from filenames like:
        aois_rstar_grove_X_UTM15.gpkg -> UTM15X
    """
    m = UTM_PATTERN.search(file_path.stem)
    if not m:
        raise ValueError(f"Failed to parse utm zone from filename: {file_path.name}")
    return f"UTM{m.group(1).upper()}{m.group(2)}"


def polygon_to_kml_coordinates(poly: Polygon):
    """
    Convert a shapely Polygon 4-point box to the style expected by CoastSat from geojson.io
    KML coordinates block should look like:
        lon,lat
        lon,lat
        ...
    """
    coords = []
    for x, y in poly.exterior.coords:
        coords.append(f"{x:.15f},{y:.15f}")
    return "\n".join(coords)


def geometry_to_geojsonio_kml(geom):
    """
    Return KML text in the same style as geojson.io
    """
    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
        
    placemarks = []
    for poly in polygons:
        coords_text = polygon_to_kml_coordinates(poly)
        placemarks.append(
            f"""<Placemark>
            <ExtendedData></ExtendedData>
            <Polygon>
            <outerBoundaryIs>
            <LinearRing><coordinates>{coords_text}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"""
        )
    return (
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n'
        + "\n".join(placemarks)
        + "\n</Document></kml>"
    )


def export_gpkg_aois_to_kmls(gpkg_path: Path, output_root: Path):
    """
    Read GPKG, reproject to EPSG:4326, and export each AOI as its own KML.
    Output is grouped into a folder named by UTM zone based on the gpkg filename.
    """
    zone_folder = get_zone_folder_name(gpkg_path)
    zone_output = output_root/zone_folder
    zone_output.mkdir(parents=True, exist_ok=True)
    gdf = gpd.read_file(gpkg_path)

    if gdf.empty:
        print(f"Skipping empty file: {gpkg_path.name}")
        return
    if gdf.crs is None:
        raise ValueError(f"{gpkg_path.name} has no CRS defined.")

    gdf = gdf.to_crs("EPSG:4326")
    print(f"\nProcessing {gpkg_path.name} -> {zone_folder}")
    print(f"  Features: {len(gdf)}")
    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            print(f"  - Skipping empty geometry at idx: {idx}")
            continue
        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            print(f"  - Skipping index {idx}, unsupported geometry type: {geom.geom_type}")
            continue

        safe_name = re.sub(r'[<>:"/\\\\|?*]+', "_", str(row["aoi_id"]))
        out_path = zone_output/f"{safe_name}L.kml"
        kml_text = geometry_to_geojsonio_kml(geom)
        out_path.write_text(kml_text, encoding="utf-8")
    print(f"  Wrote KMLs to: {zone_output}")


def main():
    # User I/O paths
    input_folder = Path(r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\Great_Lakes_aois")
    output_folder = Path(r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\Great_Lakes_aois_kml")
    output_folder.mkdir(parents=True, exist_ok=True)

    gpkg_files = sorted(input_folder.glob("*.gpkg"))
    print(f"Found {len(gpkg_files)} gpkg files")
    for gpkg_path in gpkg_files:
        try:
            export_gpkg_aois_to_kmls(gpkg_path, output_folder)
        except Exception as e:
            print(f"Failed on {gpkg_path.name}: {e}")


if __name__ == "__main__":
    main()