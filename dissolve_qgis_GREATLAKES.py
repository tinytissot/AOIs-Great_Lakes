# NOTE: run in QGIS

# NOTE: updated Paths to create Great Lakes AOIs (2026-04-14)

import os
import processing
from qgis.core import QgsVectorLayer


input_folder = r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\greatlakes_by_utm"
output_folder = r"C:\Users\jwatt\cs\06_scratch\202060414_AOIs_Great_Lakes\greatlakes_by_utm_dissolved"

dissolve_field = None

os.makedirs(output_folder, exist_ok=True)

for file in os.listdir(input_folder):
    if not file.lower().endswith(".shp"):
        continue

    input_path = os.path.join(input_folder, file)
    base = os.path.splitext(file)[0]
    output_path = os.path.join(output_folder, f"{base}_singleparts.shp")
    print(f"Processing: {file}")
    layer = QgsVectorLayer(input_path, base, "ogr")
    if not layer.isValid():
        print(f"Failed to load {file}")
        continue

    dissolve_params = { # dissolve tool
        'INPUT': layer,
        'FIELD': [dissolve_field] if dissolve_field else [],
        'SEPARATE_DISJOINT': True,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    }
    dissolve_result = processing.run("native:dissolve", dissolve_params)
    dissolved_layer = dissolve_result['OUTPUT']
    singleparts_params = { # multiparts to singleparts tools (MultiLinestrings to Linestrings)
        'INPUT': dissolved_layer,
        'OUTPUT': output_path
    }
    processing.run("native:multiparttosingleparts", singleparts_params)
    print(f"Saved: {output_path}")

print("Batch processing complete.")