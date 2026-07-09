"""Synthetic geocoding for the Ames Housing dataset.

The Ames dataset only carries a categorical `Neighborhood` code (e.g. "NAmes",
"CollgCr") — there is no street address or lat/lng in the source data. For the
portfolio map view we approximate each neighborhood's real-world position in
Ames, Iowa with a hand-placed centroid, then deterministically jitter each
property within a small radius of its neighborhood centroid so every asset
gets a distinct, stable pin (same pid always lands on the same point).

Coordinates are approximate placements for visualization purposes only — not
surveyed addresses.
"""
import hashlib

# Approximate centroid (lat, lng) per Ames neighborhood code, placed roughly
# per their real-world position around Ames, Iowa (42.0308 N, -93.6319 W).
NEIGHBORHOOD_CENTROIDS = {
    "Blmngtn": (42.0614, -93.6392),
    "Blueste": (42.0092, -93.6465),
    "BrDale":  (42.0530, -93.6288),
    "BrkSide": (42.0288, -93.6198),
    "ClearCr": (42.0577, -93.6440),
    "CollgCr": (42.0208, -93.6602),
    "Crawfor": (42.0197, -93.6255),
    "Edwards": (42.0163, -93.6706),
    "Gilbert": (42.1067, -93.6382),
    "Greens":  (42.0587, -93.6431),
    "GrnHill": (42.0206, -93.6685),
    "IDOTRR":  (42.0223, -93.6187),
    "Landmrk": (42.0180, -93.6470),
    "MeadowV": (42.0135, -93.6053),
    "Mitchel": (41.9903, -93.6027),
    "NAmes":   (42.0458, -93.6197),
    "NPkVill": (42.0483, -93.6300),
    "NWAmes":  (42.0453, -93.6478),
    "NoRidge": (42.0553, -93.6535),
    "NridgHt": (42.0602, -93.6558),
    "OldTown": (42.0284, -93.6180),
    "SWISU":   (42.0231, -93.6470),
    "Sawyer":  (42.0362, -93.6531),
    "SawyerW": (42.0335, -93.6613),
    "Somerst": (42.0518, -93.6437),
    "StoneBr": (42.0592, -93.6501),
    "Timber":  (41.9985, -93.6489),
    "Veenker": (42.0430, -93.6512),
}

DEFAULT_CENTROID = (42.0308, -93.6319)  # downtown Ames fallback for unmapped codes
JITTER_RADIUS_DEG = 0.0055  # ~500m, keeps pins within their neighborhood cluster


def property_latlng(pid: int, neighborhood: str) -> tuple[float, float]:
    """Deterministic, stable per-property point near its neighborhood centroid."""
    lat0, lng0 = NEIGHBORHOOD_CENTROIDS.get(neighborhood, DEFAULT_CENTROID)
    digest = hashlib.sha256(f"{pid}".encode()).digest()
    ux = (int.from_bytes(digest[0:4], "big") / 0xFFFFFFFF) * 2 - 1
    uy = (int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF) * 2 - 1
    return round(lat0 + ux * JITTER_RADIUS_DEG, 6), round(lng0 + uy * JITTER_RADIUS_DEG, 6)
