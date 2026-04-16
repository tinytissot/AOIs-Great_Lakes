# README

## Date: 2026-04-16

This folder contains the materials used to create procedural AOIs for the Great Lakes.

 - create_RSGrove_partition_overlap.py: same as the script used to generate Cancoast AOIs, just changed filepaths
 - Shorelines_Great_Lakes_V4_flipped/: Great Lakes shapefile copied from the shared drive ("P:\CoastSat\Shapefiles\Shoreline_Great_Lakes_V4_flipped.shp")



Processing steps:
Same workflow as the cancoast_by_utm materials: "C:\Users\jwatt\cs\06_scratch\20260218_cancoast_by_utm\README.txt",
and the AOIs: P:\CoastSat\AOIs.
The original script paths have been updated to use Great Lake paths.

	Preparing the shoreline to be input:
	1. get_cancoast_by_utm_GREATLAKES.py: saves output to greatlakes_by_utm/
	2. dissolve_qgis_GREATLAKES.py: run in QGIS, saves output to greatlakes_by_utm_dissolved/

	Creating the AOIs:
	3. create_RSGrove_partition_overlap_GREATLAKES.py

	Saving the AOIs as individual KML files:
	4. save_individual_aoi_kml_GREATLAKES.py

	Later, when downloading from the P:drive for processing:
	5. save_intersecting_kmls_GREATLAKES.py