"""
Script Name: create_RSGrove_partition_overlap.py
Description: the script used to create the procedural AOIs that span the entirety of the CanCoast shoreline

How to run:
 - ensure the shoreline you want to use has been preprocessed appropriately as was done in the 20260218_cancoast_by_utm folder (see that README.txt)

>>> python create_RSGrove_partition_overlap.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import math
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, MultiPoint, box
from shapely.ops import unary_union
from glob import glob
from pathlib import Path
import re


@dataclass
class RSParams:
    spacing_m: float = 100.0 # sampling
    metric_crs: str = "EPSG:3347" # partition CRS (m)

    # AOI constraints
    max_aoi_area_km2: float = 100.0
    max_points_per_box: int = 2500
    max_density_pts_per_km2: Optional[float] = None

    # Min size/recursion
    min_box_side_m: float = 500.0
    max_depth: int = 18

    # Second pass to add small amount of overlap (25m spacing between coastline points means there is potential for gaps)
    second_pass_enabled: bool = True
    second_pass_pad_m: float = 150.0
    second_pass_min_area_fraction: float = 0.20
    second_pass_sort_by: str = "n_points"   # options: "n_points", "area_desc", "area_asc"


@dataclass
class PartitionNode:
    bbox: object
    point_ids: np.ndarray
    depth: int


def sample_points_along_lines(lines_gdf_metric: gpd.GeoDataFrame, spacing_m: float) -> gpd.GeoDataFrame:
    """
    Turn coastline lines into sample points in a metric CRS.
    """
    pts = []
    for geom in lines_gdf_metric.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            parts = [geom]
        elif geom.geom_type == "MultiLineString":
            parts = list(geom.geoms)
        else:
            continue

        for line in parts:
            length = line.length
            if length == 0:
                continue

            n = max(2, int(math.ceil(length/spacing_m))+1)
            distances = np.linspace(0, length, n)
            for d in distances:
                pts.append(line.interpolate(d))
    if not pts:
        raise ValueError("No coastline sample points were created.")
    return gpd.GeoDataFrame(geometry=pts, crs=lines_gdf_metric.crs)


def bbox_area_km2(b):
    return b.area/1_000_000.0


def bbox_side_lengths(b):
    minx, miny, maxx, maxy = b.bounds
    return maxx-minx, maxy-miny


def bbox_perimeter(b):
    minx, miny, maxx, maxy = b.bounds
    return 2.0*((maxx-minx) + (maxy-miny))


def make_tight_bbox(points_xy: np.ndarray, point_ids: np.ndarray):
    """
    Bounding box around a subset of sampled points
    """
    subset = points_xy[point_ids]
    minx = subset[:,0].min()
    miny = subset[:,1].min()
    maxx = subset[:,0].max()
    maxy = subset[:,1].max()
    return box(minx,miny,maxx,maxy)


def padded_bbox(b, min_side_m: float):
    """
    Ensure the bbox is not too skinny/thin by padding short dimensions.
    """
    minx, miny, maxx, maxy = b.bounds
    w = maxx-minx
    h = maxy-miny

    if w < min_side_m:
        pad = (min_side_m-w) / 2.0
        minx -= pad
        maxx += pad
    if h < min_side_m:
        pad = (min_side_m-h) / 2.0
        miny -= pad
        maxy += pad
    return box(minx,miny,maxx,maxy)


def pad_bbox_by_distance(b, pad_m: float):
    """
    Uniformly pad a bbox outward by a fixed distance in meters.
    NOTE: for the second pass.
    """
    minx, miny, maxx, maxy = b.bounds
    return box(minx-pad_m, miny-pad_m, maxx+pad_m, maxy+pad_m)


def largest_polygon_part(geom):
    """
    If geometry is multipart after subtracting overlaps -> keep largest piece.
    """
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type=="Polygon":
        return geom
    if geom.geom_type=="MultiPolygon":
        return max(geom.geoms, key=lambda g:g.area)

    gc = getattr(geom,"geoms",None)
    if gc:
        polys = [g for g in gc if g.geom_type in {"Polygon", "MultiPolygon"} and not g.is_empty]
        if not polys:
            return None
        exploded = []
        for g in polys:
            if g.geom_type == "Polygon":
                exploded.append(g)
            else:
                exploded.extend(list(g.geoms))
        return max(exploded, key=lambda g:g.area) if exploded else None
    return None


def second_pass_remove_overlaps(
    aois_metric: gpd.GeoDataFrame,
    params: RSParams,
) -> gpd.GeoDataFrame:
    """
    Second pass:
    1. pad all boxes a little
    2. greedily subtract overlap against already accepted boxes
    3. keep the largest remaining piece
    4. convert that remaining piece back to a bbox

    This preserves a rectangle output while removing overlap greedily.
    """
    if aois_metric.empty:
        return aois_metric.copy()

    work = aois_metric.copy()
    work["orig_area_m2"] = work.geometry.area
    work["geometry"] = work.geometry.apply(lambda g: pad_bbox_by_distance(g, params.second_pass_pad_m))

    # Greedy ordering
    if params.second_pass_sort_by == "n_points": # n_points is kind of a proxy for the load (the 'amount' of shoreline)
        work = work.sort_values(
            by=["n_points", "area_km2_metric_bbox", "depth"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
    elif params.second_pass_sort_by == "area_desc":
        work = work.sort_values(
            by=["area_km2_metric_bbox", "n_points", "depth"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
    elif params.second_pass_sort_by == "area_asc":
        work = work.sort_values(
            by=["area_km2_metric_bbox", "n_points", "depth"],
            ascending=[True, False, True],
        ).reset_index(drop=True)
    else:
        raise ValueError(f"second_pass_sort_by is not an option: {params.second_pass_sort_by}")

    accepted_geoms = []
    out_records = []
    for _, row in work.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        remaining = geom
        for prev in accepted_geoms:
            if remaining.is_empty:
                break
            if not remaining.intersects(prev):
                continue
            remaining = remaining.difference(prev)

        remaining = largest_polygon_part(remaining)
        if remaining is None or remaining.is_empty:
            continue
        remaining_area = remaining.area
        if remaining_area <= 0:
            continue
        if remaining_area < row["orig_area_m2"]*params.second_pass_min_area_fraction:
            continue

        # convert the leftover geometry back to a bbox so output stays rectangular
        new_bbox = box(*remaining.bounds)
        row_out = row.copy()
        row_out.geometry = new_bbox
        row_out["area_km2_metric_bbox"] = new_bbox.area/1_000_000.0
        accepted_geoms.append(new_bbox)
        out_records.append(row_out)
    if not out_records:
        return aois_metric.iloc[0:0].copy()
    cleaned = gpd.GeoDataFrame(out_records, crs=aois_metric.crs).copy()

    # Try to sort order and reassign AOI ids before saving
    if "region" in cleaned.columns:
        cleaned = cleaned.sort_values(by=["region", "aoi_id"]).reset_index(drop=True)
        cleaned["aoi_id"] = [
            f"{region}_{i+1:04d}"
            for region, i in zip(cleaned["region"], cleaned.groupby("region").cumcount())
        ]
    else:
        cleaned = cleaned.reset_index(drop=True)
    cleaned = cleaned.drop(columns=["orig_area_m2"], errors="ignore")
    return cleaned


def needs_split(node: PartitionNode, points_xy: np.ndarray, params: RSParams):
    """
    Decide if a node (box) should be split further.
    """
    n_pts = len(node.point_ids)
    if n_pts == 0:
        return False

    area_km2 = bbox_area_km2(node.bbox)
    width, height = bbox_side_lengths(node.bbox)

    # checks
    if node.depth >= params.max_depth:
        return False
    if width <= params.min_box_side_m and height <= params.min_box_side_m:
        return False
    if area_km2 > params.max_aoi_area_km2:
        return True
    if n_pts > params.max_points_per_box:
        return True
    if params.max_density_pts_per_km2 is not None and area_km2 > 0:
        density = n_pts / area_km2
        if density > params.max_density_pts_per_km2:
            return True

    return False


def split_score(
    left_bbox,
    right_bbox,
    n_left: int,
    n_right: int,
    total_n: int,
) -> float:
    """
    Lower is better

    R*-style intuition:
    - minimize overlap
    - minimize dead space/total area
    - minimize margin ('square-ness')
    - encourage balanced splits
    """
    overlap = left_bbox.intersection(right_bbox).area
    total_area = left_bbox.area + right_bbox.area
    total_margin = bbox_perimeter(left_bbox) + bbox_perimeter(right_bbox)
    balance = abs(n_left-n_right) / total_n
    score = ( # sort of arbitrary... I was testing with a grid search approach for the best params and this works pretty well. R*-style is heuristic so I thought this was ok for now!
        overlap*1000.0
        + total_area
        + total_margin*5.0
        + balance*total_area*0.25
    )
    return score


def candidate_splits_1d(sorted_vals: np.ndarray, min_group_size: int = 2) -> List[int]:
    """
    Generate candidate split indices in sorted order.
    Avoids very tiny groups.
    """
    n = len(sorted_vals)
    if n<2 * min_group_size:
        return []

    qs = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    idxs = sorted(set(
        max(min_group_size, min(n-min_group_size, int(round(q*n))))
        for q in qs
    ))
    diffs = np.diff(sorted_vals)
    if len(diffs)>0:
        largest_gap_idx = int(np.argmax(diffs)) + 1
        if min_group_size <= largest_gap_idx <= n-min_group_size:
            idxs.append(largest_gap_idx)
    return sorted(set(idxs))


def try_axis_split(
    point_ids: np.ndarray,
    points_xy: np.ndarray,
    axis: int,
    params: RSParams,
) -> Optional[Tuple[np.ndarray, np.ndarray, object, object, float]]:
    """
    Try splitting along one axis and return the best candidate.
    """
    coords = points_xy[point_ids, axis]
    order = np.argsort(coords)
    ordered_ids = point_ids[order]
    ordered_vals = coords[order]

    cut_idxs = candidate_splits_1d(ordered_vals, min_group_size=2)
    if not cut_idxs:
        return None
    best = None
    total_n = len(point_ids)

    for cut in cut_idxs:
        left_ids = ordered_ids[:cut]
        right_ids = ordered_ids[cut:]
        if len(left_ids) < 2 or len(right_ids) < 2:
            continue
        left_bbox = padded_bbox(make_tight_bbox(points_xy, left_ids), params.min_box_side_m)
        right_bbox = padded_bbox(make_tight_bbox(points_xy, right_ids), params.min_box_side_m)
        score = split_score(left_bbox, right_bbox, len(left_ids), len(right_ids), total_n)
        candidate = (left_ids, right_ids, left_bbox, right_bbox, score)
        if best is None or score < best[4]:
            best = candidate

    return best


def choose_best_split(
    node: PartitionNode,
    points_xy: np.ndarray,
    params: RSParams,
) -> Optional[Tuple[PartitionNode, PartitionNode]]:
    """
    Choose the best split across X and Y dimensions
    """
    best_x = try_axis_split(node.point_ids, points_xy, axis=0, params=params)
    best_y = try_axis_split(node.point_ids, points_xy, axis=1, params=params)

    best = None
    for candidate in [best_x, best_y]:
        if candidate is None:
            continue
        if best is None or candidate[4] < best[4]:
            best = candidate
    if best is None:
        return None

    left_ids, right_ids, left_bbox, right_bbox, _ = best
    left = PartitionNode(
        bbox=left_bbox,
        point_ids=left_ids,
        depth=node.depth + 1,
    )
    right = PartitionNode(
        bbox=right_bbox,
        point_ids=right_ids,
        depth=node.depth + 1,
    )
    return left, right


def recursive_partition(
    node: PartitionNode,
    points_xy: np.ndarray,
    params: RSParams,
    out_nodes: List[PartitionNode],
):
    """
    Recursively split until constraints are satisfied.
    """
    if not needs_split(node, points_xy, params):
        out_nodes.append(node)
        return

    split_nodes = choose_best_split(node, points_xy, params)
    if split_nodes is None:
        out_nodes.append(node)
        return
    left, right = split_nodes

    if len(left.point_ids)==0 or len(right.point_ids)==0:
        out_nodes.append(node)
        return
    if len(left.point_ids)==len(node.point_ids) or len(right.point_ids)==len(node.point_ids):
        out_nodes.append(node)
        return

    recursive_partition(left, points_xy, params, out_nodes)
    recursive_partition(right, points_xy, params, out_nodes)


def build_rsgrove_aois_from_coastline(
    coast: gpd.GeoDataFrame,
    region_utmzone: str,
    params: RSParams,
) -> gpd.GeoDataFrame:
    """
    Uses an R*-Grove-style partitioner to create AOIs for the given shoreline.
    """
    if coast.empty:
        raise ValueError("Input coastline gdf is empty")
    coast_metric = coast.to_crs(params.metric_crs)
    pts_gdf = sample_points_along_lines(coast_metric, params.spacing_m) # sample coastline into points
    coords = np.column_stack([pts_gdf.geometry.x.values, pts_gdf.geometry.y.values])

    all_ids = np.arange(len(coords), dtype=int)
    root_bbox = padded_bbox(make_tight_bbox(coords, all_ids), params.min_box_side_m) # make root note (bbox over whole coastline file points extent)
    root = PartitionNode(
        bbox=root_bbox,
        point_ids=all_ids,
        depth=0,
    )

    leaves:List[PartitionNode] = []
    recursive_partition(root, coords, params, leaves) # leaves = out_nodes from recursion

    records = []
    for i, node in enumerate(leaves):
        geom = node.bbox
        area_km2 = geom.area/1_000_000.0
        records.append(
            {
                "region": region_utmzone,
                "aoi_id": f"{region_utmzone}_{i+1:04d}",
                "depth": node.depth,
                "n_points": len(node.point_ids),
                "area_km2_metric_bbox": area_km2,
                "priority": "L",
                "downloaded": "N",
                "analysis": "N",
                "analysis_version": None,
                "webmap": "N",
                "start_date": None,
                "end_date": None,
                "analysis_date": None,
                "comments": None,
                "geometry": geom,
            }
        )
    aois_metric = gpd.GeoDataFrame(records, crs=params.metric_crs)
    # optional: second pass overlap cleanup
    if params.second_pass_enabled:
        aois_metric = second_pass_remove_overlaps(aois_metric, params)

    aois_ll = aois_metric.to_crs("EPSG:4326")
    return aois_ll


def combine_all_to_gpkg(input_folder, output_gpkg, extension="*.gpkg"):
    """
    Combines all files with the given extension in the folder into a single .gpkg
    """
    files = sorted(Path(input_folder).glob(extension))
    gdfs = []
    for f in files:
        gdf = gpd.read_file(f)
        gdf["source_file"] = f.stem
        gdfs.append(gdf)
    combined = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs)
    combined.to_file(output_gpkg, driver="GPKG")


# def test():
#     """
#     Used to test with a subset of the shoreline.
#     """
#     coast = gpd.read_file(
#         r"C:\Users\jwatt\cs\06_scratch\20260217_procedural_aois_single\clip_bigger.shp"
#     ).to_crs("EPSG:4326")

#     params = RSParams(
#         spacing_m=25.0,
#         metric_crs="EPSG:32610",
#         max_aoi_area_km2=100.0,
#         max_points_per_box=10_000,
#         max_density_pts_per_km2=None,
#         min_box_side_m=6_000.0,
#         max_depth=18,
#         second_pass_enabled=True,
#         second_pass_pad_m=150.0,
#         second_pass_min_area_fraction=0.20,
#         second_pass_sort_by="n_points",
#     )
#     region_utmzone = "U_UTM10"
#     aois = build_rsgrove_aois_from_coastline(coast, region_utmzone, params)
#     aois.to_file(
#         r"C:\Users\jwatt\cs\06_scratch\20260310_RSGrove_partition_aois\aois_RSGrove_sandbox.gpkg",
#         driver="GPKG",
#     )
#     print(len(aois), aois["area_km2_metric_bbox"].sum())


def main():
    """
    Main function to create the procedural AOIs from a given shoreline.
    """
    # User I/O paths
    input_folder = Path(r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\greatlakes_by_utm_dissolved")
    output_folder = Path(r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\Great_Lakes_aois")
    output_folder.mkdir(parents=True, exist_ok=True)

    shp_files = sorted(input_folder.glob("shoreline_utm_*_*_*_singleparts.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No matching shapefiles found in: {input_folder}")
    print(f"Found {len(shp_files)} shoreline shapefiles.")

    for shp_path in shp_files:
        print("\n" + "=" * 80)
        print(f"Processing: {shp_path.name}")

        m = re.match(
            r"shoreline_utm_(\d+)_\d+_([A-Z])_singleparts\.shp$",
            shp_path.name,
        )
        if m is None:
            print(f"Skipping file with unexpected name formatting: {shp_path.name}")
            continue

        zone = int(m.group(1))
        band = m.group(2)
        metric_crs = f"EPSG:326{zone:02d}"
        region_utmzone = f"{band}_UTM{zone}"

        # coast = gpd.read_file(shp_path).to_crs("EPSG:4326")
        coast_original = gpd.read_file(shp_path)
        coast = coast_original.to_crs("EPSG:4326")
        print(f"Parsed zone={zone}, band={band}, metric_crs={metric_crs}, region={region_utmzone}")
        params = RSParams(
            spacing_m=25.0,
            metric_crs=metric_crs,
            max_aoi_area_km2=100.0,
            max_points_per_box=10_000,
            max_density_pts_per_km2=None,
            min_box_side_m=6_000.0,
            max_depth=18,
            second_pass_enabled=True,
            second_pass_pad_m=150.0,
            second_pass_min_area_fraction=0.20,
            second_pass_sort_by="n_points",
        )
        aois = build_rsgrove_aois_from_coastline(coast, region_utmzone, params)
        out_path = output_folder/f"aois_rstar_grove_{region_utmzone}.gpkg"
        aois.to_file(out_path, driver="GPKG")
        print(f"Saved: {out_path}")
        print(f"AOIs: {len(aois)}")
        print(f"Total area_km2_metric_bbox: {aois['area_km2_metric_bbox'].sum():.3f}")
    print("\nDone.")


if __name__ == "__main__":
    # test()
    main()
    combine_all_to_gpkg(
        r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\Great_Lakes_aois",
        r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\Great_Lakes_aois.gpkg",
        "*.gpkg"
    )
    # combine_all_to_gpkg(
    #     r"C:\Users\jwatt\cs\06_scratch\20260218_cancoast_by_utm\cancoast_by_utm_dissolved",
    #     r"C:\Users\jwatt\cs\06_scratch\20260218_cancoast_by_utm\cancoast_by_utm_dissolved.gpkg",
    #     "*.shp"
    # )
