"""
JDEV-cli Tool: get_cancoast_by_utm_GREATLAKES.py
Date: 2026-02-18

Creates a separate shp file for each UTM Zone with the corresponding segment of CanCoast shoreline in EPSG:4326.

NOTE: modified Paths to create AOIs for the Great Lakes (2026-04-14)

How-to:
>>> conda activate coastsat
>>> python get_cancoast_by_utm_GREATLAKES.py
"""

import os
import re
import geopandas as gpd


def main():
    import re
    utm_path = r"C:\Users\jwatt\cs\02_rawdata\World_UTM_Grid\World_UTM_Grid.shp"
    shoreline_path = r"C:\Users\jwatt\cs\02_rawdata\World_UTM_Grid\World_UTM_Grid.shp"
    out_dir = r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\greatlakes_by_utm"
    os.makedirs(out_dir, exist_ok=True)

    print("Reading utm file...")
    utm = gpd.read_file(utm_path)
    print("Reading CanCoast file...")
    shoreline = gpd.read_file(shoreline_path)

    if shoreline.crs is None:
        shoreline = shoreline.set_crs("EPSG:4326")
    else:
        shoreline = shoreline.to_crs("EPSG:4326")

    # reproject UTM zones to EPSG:4326 so clip works correctly
    print("Reprojecting UTM Zones to EPSG:4326...")
    if utm.crs is None:
        raise ValueError("UTM grid has no CRS; set it before running.")
    utm_4326 = utm.to_crs("EPSG:4326")

    def safe_name(x: str) -> str:
        x = str(x)
        x = re.sub(r"[^\w\-]+", "_", x)
        return x.strip("_")

    print("Speedup option...")
    shoreline = shoreline[shoreline.geometry.notnull()].copy()

    written = 0
    for i, zone in utm_4326.iterrows():
        zone_id = safe_name(zone["ZONE"])
        row_id = safe_name(zone["ROW_"])
        print(f"Working on: UTM Zone {zone_id} {row_id}")
        zone_gdf = utm_4326.iloc[[i]].copy()
        clipped = gpd.clip(shoreline, zone_gdf)

        if clipped.empty: # skip shorelines with no features
            continue

        clipped = clipped.set_crs("EPSG:4326", allow_override=True)
        out_path = os.path.join(out_dir, f"shoreline_utm_{zone_id}_{row_id}.shp")
        clipped.to_file(out_path)
        written += 1
    print(f"Done. Wrote {written} zone shoreline shapefiles to:\n{out_dir}")


if __name__ == "__main__":
    main()