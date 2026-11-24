"""
Orientation analysis of digitized linear features - QGIS Python Console version.

How to run: in QGIS open Plugins > Python Console > Show Editor,
open this file, and press Run. It reads the layer "linear_features"
from the open project, so nothing has to be installed.

It computes the orientation of every line segment as axial data (0-180 deg),
length-weighted circular statistics (angle doubling, Mardia & Jupp 2000),
and saves a rose diagram and CSV tables in a "results" folder next to the
GeoPackage.
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from qgis.core import QgsProject, QgsWkbTypes

LAYER_NAME = "linear_features"
TYPE_FIELD = "type"
BIN_WIDTH = 10  # degrees


def axial_azimuth(x1, y1, x2, y2):
    """Azimuth from north, clockwise, folded to 0-180 deg."""
    return (np.degrees(np.arctan2(x2 - x1, y2 - y1)) % 360.0) % 180.0


def axial_stats(az, w):
    """Length-weighted mean axial direction and mean resultant length R."""
    az, w = np.asarray(az, float), np.asarray(w, float)
    d = np.radians(2.0 * az)
    c = np.sum(w * np.cos(d)) / np.sum(w)
    s = np.sum(w * np.sin(d)) / np.sum(w)
    return (np.degrees(np.arctan2(s, c)) / 2.0) % 180.0, float(np.hypot(c, s))


layers = QgsProject.instance().mapLayersByName(LAYER_NAME)
if not layers:
    raise Exception(f"Layer '{LAYER_NAME}' not found in the project.")
layer = layers[0]
if layer.crs().isGeographic():
    raise Exception("Layer CRS is geographic (degrees). Use a projected CRS in metres, e.g. EPSG:32617.")

has_type = TYPE_FIELD in layer.fields().names()
segments, features = [], []

for f in layer.getFeatures():
    geom = f.geometry()
    if geom.isEmpty() or geom.type() != QgsWkbTypes.LineGeometry:
        continue
    ftype = (f[TYPE_FIELD] if has_type else None) or "unclassified"
    parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
    for part in parts:
        for p1, p2 in zip(part[:-1], part[1:]):
            length = float(np.hypot(p2.x() - p1.x(), p2.y() - p1.y()))
            if length > 0:
                segments.append((f.id(), ftype, length, float(axial_azimuth(p1.x(), p1.y(), p2.x(), p2.y()))))
    first, last = parts[0][0], parts[-1][-1]
    features.append((f.id(), ftype, geom.length(),
                     float(axial_azimuth(first.x(), first.y(), last.x(), last.y()))))

if not segments:
    raise Exception("No line segments found in the layer.")

# Output folder next to the GeoPackage
src = layer.source().split("|")[0]
out = os.path.join(os.path.dirname(src), "results")
os.makedirs(out, exist_ok=True)

ids = np.array([s[0] for s in segments])
types = np.array([s[1] for s in segments])
lengths = np.array([s[2] for s in segments])
az = np.array([s[3] for s in segments])

# Summary: all features, then per type
summary = []
groups = [("all", np.ones(len(az), bool))] + [(t, types == t) for t in sorted(set(types))]
for name, m in groups:
    mean_dir, r = axial_stats(az[m], lengths[m])
    summary.append([name, len(set(ids[m])), int(m.sum()), round(lengths[m].sum(), 1),
                    round(mean_dir, 1), round(r, 3)])

with open(os.path.join(out, "segments.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["feature_id", "type", "length_m", "azimuth_deg"])
    w.writerows([[a, b, round(c, 2), round(d, 2)] for a, b, c, d in segments])
with open(os.path.join(out, "features.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["feature_id", "type", "length_m", "start_end_azimuth_deg"])
    w.writerows([[a, b, round(c, 2), round(d, 2)] for a, b, c, d in features])
with open(os.path.join(out, "summary.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["group", "n_features", "n_segments", "total_length_m",
                "mean_axial_direction_deg", "mean_resultant_length_R"])
    w.writerows(summary)

# Rose diagram (mirrored, length-weighted)
mean_dir, r = summary[0][4], summary[0][5]
az2 = np.concatenate([az, az + 180.0])
w2 = np.concatenate([lengths, lengths])
edges = np.arange(0, 360 + BIN_WIDTH, BIN_WIDTH)
counts, _ = np.histogram(az2, bins=edges, weights=w2)
counts = counts / counts.sum() * 100.0

fig = plt.figure(figsize=(6, 6))
ax = fig.add_subplot(projection="polar")
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)
ax.bar(np.radians(edges[:-1]), counts, width=np.radians(BIN_WIDTH), align="edge",
       color="#4C72B0", edgecolor="white", linewidth=0.8)
for d in (mean_dir, mean_dir + 180.0):
    ax.plot([np.radians(d)] * 2, [0, counts.max() * 1.05], color="#C44E52", lw=2)
ax.set_yticklabels([])
ax.set_title(f"Orientation of digitized linear features\n"
             f"n = {summary[0][1]} features, {summary[0][2]} segments, "
             f"mean = {mean_dir:.0f}°, R = {r:.2f}", fontsize=10, pad=18)
fig.text(0.5, 0.02, "Length-weighted, 10° bins; red line = mean axial direction",
         ha="center", fontsize=8, color="grey")
fig.savefig(os.path.join(out, "rose_diagram.png"), dpi=200, bbox_inches="tight")
plt.close(fig)

print("group | n_features | n_segments | total_length_m | mean_dir_deg | R")
for row in summary:
    print(" | ".join(str(v) for v in row))
print("Results saved in:", out)
