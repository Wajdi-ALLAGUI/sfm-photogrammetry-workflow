"""
Orientation analysis of linear features digitized in QGIS.

Reads a GeoPackage of LineString features (projected CRS, metres),
computes the orientation of every line segment as axial data (0-180 deg),
summarises it with length-weighted circular statistics, and draws a
rose diagram. This is the kind of analysis used for directional field
data such as glacial striations or flutes.

Usage:
    python orientation_analysis.py features.gpkg
    python orientation_analysis.py features.gpkg --layer linear_features --out results

Outputs (in the --out folder):
    segments.csv          one row per segment: feature id, type, length, azimuth
    features.csv          one row per feature: total length, start-to-end azimuth
    summary.csv           circular statistics, overall and per type
    rose_diagram.png      length-weighted rose diagram (10 degree bins)
"""

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def axial_azimuth(x1, y1, x2, y2):
    """Azimuth from north, clockwise, folded to 0-180 deg (a line has no direction)."""
    az = np.degrees(np.arctan2(x2 - x1, y2 - y1)) % 360.0
    return az % 180.0


def axial_stats(azimuths, weights=None):
    """Circular mean and mean resultant length for axial data.

    Axial data are handled by doubling the angles, averaging on the circle,
    then halving the mean (e.g. Mardia & Jupp, Directional Statistics, 2000).
    """
    az = np.asarray(azimuths, dtype=float)
    w = np.ones_like(az) if weights is None else np.asarray(weights, dtype=float)
    doubled = np.radians(2.0 * az)
    c = np.sum(w * np.cos(doubled)) / np.sum(w)
    s = np.sum(w * np.sin(doubled)) / np.sum(w)
    mean_dir = (np.degrees(np.arctan2(s, c)) / 2.0) % 180.0
    r = float(np.hypot(c, s))  # 0 = no preferred orientation, 1 = all parallel
    return mean_dir, r


def explode_segments(gdf, type_col):
    rows = []
    for fid, geom, ftype in zip(gdf.index, gdf.geometry, gdf[type_col]):
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for part in parts:
            xy = np.asarray(part.coords)[:, :2]
            for (x1, y1), (x2, y2) in zip(xy[:-1], xy[1:]):
                length = float(np.hypot(x2 - x1, y2 - y1))
                if length == 0:
                    continue
                rows.append({
                    "feature_id": fid,
                    "type": ftype,
                    "length_m": length,
                    "azimuth_deg": float(axial_azimuth(x1, y1, x2, y2)),
                })
    return pd.DataFrame(rows)


def feature_table(gdf, type_col):
    rows = []
    for fid, geom, ftype in zip(gdf.index, gdf.geometry, gdf[type_col]):
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        first = np.asarray(parts[0].coords)[0]
        last = np.asarray(parts[-1].coords)[-1]
        rows.append({
            "feature_id": fid,
            "type": ftype,
            "length_m": float(geom.length),
            "start_end_azimuth_deg": float(axial_azimuth(first[0], first[1], last[0], last[1])),
        })
    return pd.DataFrame(rows)


def rose_diagram(seg, mean_dir, r, out_png, bin_width=10):
    # Mirror axial data so the rose is symmetric (a line at 30 deg also points to 210 deg)
    az = np.concatenate([seg["azimuth_deg"], seg["azimuth_deg"] + 180.0])
    w = np.concatenate([seg["length_m"], seg["length_m"]])
    edges = np.arange(0, 360 + bin_width, bin_width)
    counts, _ = np.histogram(az, bins=edges, weights=w)
    counts = counts / counts.sum() * 100.0  # percent of total length

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.bar(np.radians(edges[:-1]), counts, width=np.radians(bin_width),
           align="edge", color="#4C72B0", edgecolor="white", linewidth=0.8)
    for d in (mean_dir, mean_dir + 180.0):
        ax.plot([np.radians(d)] * 2, [0, counts.max() * 1.05], color="#C44E52", lw=2)
    ax.set_yticklabels([])
    ax.set_title(
        f"Orientation of digitized linear features\n"
        f"n = {seg['feature_id'].nunique()} features, {len(seg)} segments, "
        f"mean = {mean_dir:.0f}°, R = {r:.2f}",
        fontsize=10, pad=18,
    )
    fig.text(0.5, 0.02, "Length-weighted, 10° bins; red line = mean axial direction",
             ha="center", fontsize=8, color="grey")
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("gpkg", help="GeoPackage with LineString features")
    p.add_argument("--layer", default=None, help="layer name (default: first layer)")
    p.add_argument("--type-col", default="type", help="column with the feature type")
    p.add_argument("--out", default="results", help="output folder")
    args = p.parse_args()

    gdf = gpd.read_file(args.gpkg, layer=args.layer)
    if gdf.crs is None or not gdf.crs.is_projected:
        raise SystemExit(f"Layer CRS is {gdf.crs}; use a projected CRS in metres (e.g. UTM).")
    if args.type_col not in gdf.columns:
        gdf[args.type_col] = "unclassified"
    gdf[args.type_col] = gdf[args.type_col].fillna("unclassified")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seg = explode_segments(gdf, args.type_col)
    if seg.empty:
        raise SystemExit("No line segments found.")
    feats = feature_table(gdf, args.type_col)

    summary = []
    for name, grp in [("all", seg)] + list(seg.groupby("type")):
        mean_dir, r = axial_stats(grp["azimuth_deg"], grp["length_m"])
        summary.append({
            "group": name,
            "n_features": grp["feature_id"].nunique(),
            "n_segments": len(grp),
            "total_length_m": round(grp["length_m"].sum(), 1),
            "mean_axial_direction_deg": round(mean_dir, 1),
            "mean_resultant_length_R": round(r, 3),
        })
    summary = pd.DataFrame(summary)

    seg.round(2).to_csv(out / "segments.csv", index=False)
    feats.round(2).to_csv(out / "features.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)

    overall = summary.iloc[0]
    rose_diagram(seg, overall["mean_axial_direction_deg"], overall["mean_resultant_length_R"],
                 out / "rose_diagram.png")

    print(f"CRS: {gdf.crs.to_string()}")
    print(summary.to_string(index=False))
    print(f"\nResults written to: {out.resolve()}")


if __name__ == "__main__":
    main()
