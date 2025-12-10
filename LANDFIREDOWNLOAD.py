import os
import requests
from pyproj import Transformer
from xml.etree import ElementTree as ET

# ================================================================
# USER CONFIG
# ================================================================

YEARS = [2001, 
         #2016, 
         #2020, 
         #2022, 
         #2023, 
         #2024
]

# High-level LANDFIRE codes you want; we'll expand some of these to
# their actual coverage ID substrings in keyword_match().
INCLUDE = [
    # Canopy / structure
    "CBD", "CBH", "CC", "CH",
    "EVC", "EVH", "EVT",
    # Fuel models / fuels
    "F13", "F40", "FVC", "FVH", "FVT",
    "FCCS", "BPS", "FLM", "FRG", "MFRI",
    "PLS", "PMS", "PRS",
    "SCla", "VCC", "VDep",
    # Topography:
    "slope", "slp", "dem", "elev", "aspect",
]

# Entire output root folder
ROOT_OUT = r"D:\LANDFIRE_ALL_TEST"
os.makedirs(ROOT_OUT, exist_ok=True)

# BBOX in EPSG:4326
BBOX_WGS84 = (-105.85, 39.65, -105.15, 40.35)

# Resolution (meters)
RES_M = 30

# ================================================================
# WCS endpoints by LANDFIRE year
# ================================================================

LANDFIRE_WCS = {
    2024: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_250/wcs",
    2023: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_240/wcs",
    2022: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_230/wcs",
    2020: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_220/wcs",
    2016: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_200/wcs",
    2001: "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_105/wcs",
}

# Topographic WCS (DEM, slope, aspect)
TOPO_WCS = "https://edcintl.cr.usgs.gov/geoserver/landfire_wcs/us_topo/wcs"

# ================================================================
# REPROJECT BBOX TO EPSG:5070
# ================================================================

transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
minx, miny = transformer.transform(*BBOX_WGS84[0:2])
maxx, maxy = transformer.transform(*BBOX_WGS84[2:4])
BBOX_5070 = (minx, miny, maxx, maxy)

print("Reprojected BBOX (EPSG:5070):", BBOX_5070)

# ================================================================
# FUNCTIONS
# ================================================================

def wcs_get_coverages(url):
    params = {"service": "WCS", "request": "GetCapabilities", "version": "2.0.1"}
    r = requests.get(url, params=params)
    r.raise_for_status()

    xml = ET.fromstring(r.content)
    ns = {"wcs": "http://www.opengis.net/wcs/2.0"}

    coverages = []
    for cs in xml.findall(".//wcs:CoverageSummary", ns):
        cov = cs.find("wcs:CoverageId", ns)
        if cov is not None:
            coverages.append(cov.text)

    return coverages


def keyword_match(available, keys):
    """
    Smarter keyword matcher:
    - Uses simple substring match on full coverage ID.
    - Also expands certain short LANDFIRE codes (e.g., F13, F40, SCla)
      into the actual substrings present in coverage IDs (fbfm13, fbfm40, sclass).
    """

    # Map "nice" short codes -> list of substrings that actually appear in coverage IDs
    SPECIAL_MAP = {
        # fuel models
        "f13": ["fbfm13"],
        "f40": ["fbfm40"],
        # structure class
        "scla": ["sclass"],
        # vdep already appears as vdep, but keep pattern here if you want to customize
        "vdep": ["vdep"],
        # evt sometimes appears exactly as evt
        "evt": ["evt"],
        # others can be added here as needed
        # "fvc": ["fvc"],
        # "fvh": ["fvh"],
        # "fvt": ["fvt"],
    }

    keys_lower = [k.lower() for k in keys]

    # Build full list of search terms: original keys + any expanded patterns.
    search_terms = []
    for k in keys_lower:
        search_terms.append(k)
        if k in SPECIAL_MAP:
            search_terms.extend(SPECIAL_MAP[k])

    result = []
    for cov in available:
        low = cov.lower()
        if any(term in low for term in search_terms):
            result.append(cov)

    return result


def download_wcs(cov_id, wcs_url, bbox5070, res_m, out_file):
    minx, miny, maxx, maxy = bbox5070

    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": cov_id,
        "format": "image/tiff",
        "subset": [
            f"X({minx},{maxx})",
            f"Y({miny},{maxy})"
        ],
        "resx": str(res_m),
        "resy": str(res_m),
    }

    print(f"  → Requesting {cov_id}")
    r = requests.get(wcs_url, params=params, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {cov_id}")

    with open(out_file, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    print(f"    Saved {out_file}")


# ================================================================
# 1. PROCESS ALL LANDFIRE YEARS
# ================================================================

for YEAR in YEARS:

    if YEAR not in LANDFIRE_WCS:
        continue

    print("\n==============================================================")
    print(f"PROCESSING LANDFIRE YEAR {YEAR}")
    print("==============================================================")

    WCS_URL = LANDFIRE_WCS[YEAR]

    year_folder = os.path.join(ROOT_OUT, str(YEAR))
    os.makedirs(year_folder, exist_ok=True)

    # Get all coverages for this year
    all_cov = wcs_get_coverages(WCS_URL)

    print(f"\nAvailable coverages for {YEAR}:")
    for c in all_cov:
        print(" ", c)

    # Match using smarter keywords
    matched = keyword_match(all_cov, INCLUDE)

    print(f"\nMatched for {YEAR}:")
    for m in matched:
        print(" ", m)

    # Download them
    for cov_id in matched:
        out_file = os.path.join(year_folder, f"{cov_id}.tif")
        if os.path.exists(out_file):
            print(f"  Skipping existing {out_file}")
            continue
        try:
            download_wcs(cov_id, WCS_URL, BBOX_5070, RES_M, out_file)
        except Exception as e:
            print("  FAILED:", cov_id, "→", e)

# ================================================================
# 2. PROCESS TOPOGRAPHY (DEM, slope, aspect)
# ================================================================

print("\n==============================================================")
print("PROCESSING TOPOGRAPHY (DEM, slope, aspect)")
print("==============================================================")

topo_folder = os.path.join(ROOT_OUT, "TOPO")
os.makedirs(topo_folder, exist_ok=True)

topo_cov = wcs_get_coverages(TOPO_WCS)

print("\nTopography coverages:")
for c in topo_cov:
    print(" ", c)

topo_matched = keyword_match(topo_cov, INCLUDE)

print("\nMatched topo layers:")
for m in topo_matched:
    print(" ", m)

for cov_id in topo_matched:
    out_file = os.path.join(topo_folder, f"{cov_id}.tif")
    if os.path.exists(out_file):
        print(f"Skipping existing {out_file}")
        continue
    try:
        download_wcs(cov_id, TOPO_WCS, BBOX_5070, RES_M, out_file)
    except Exception as e:
        print("FAILED:", cov_id, "→", e)

print("\n\nAll processing complete!")
