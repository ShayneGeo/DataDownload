import os
import gc
import math
import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
import s3fs
import pytz
from datetime import datetime, timedelta
import rasterio
from rasterio.env import Env
from PIL import Image, ImageDraw, ImageFont

# -------------------------
# CONFIG
# -------------------------
OUT_DIR = r"C:\Users\magst\Desktop\HRRR\test1"
os.makedirs(OUT_DIR, exist_ok=True)

WINDOW_HOURS = 48
CYCLE_HOURS = 6
CONSOLIDATED = False

# HRRR Zarr can lag cycle init by a few hours
ARCHIVE_LAG_HOURS = 3
MAX_CYCLES_BACK = 6

# Units
TMP_UNITS = "F"  # "F", "C", or "K"

# GeoTIFF options
TIF_COMPRESS = "DEFLATE"   # None, "LZW", "DEFLATE"
TIF_ZLEVEL = 6
TIF_TILED = True
GDAL_NUM_THREADS = "ALL_CPUS"

# Chunking hint
OPEN_CHUNKS = {"projection_y_coordinate": 1200, "projection_x_coordinate": 1200}

# HRRR native projection
HRRR_NATIVE_CRS = (
    "+proj=lcc +lat_1=38.5 +lat_2=38.5 +lat_0=38.5 "
    "+lon_0=262.5 +a=6371229 +b=6371229 +units=m +no_defs"
)

# Variables
VARS = {
    "GUST": {"level": "surface",         "name": "GUST", "convert": "mps_to_mph"},
    "TMP":  {"level": "2m_above_ground", "name": "TMP",  "convert": f"tmp_{TMP_UNITS.lower()}"},
    "RH":   {"level": "2m_above_ground", "name": "RH",   "convert": "none"},
}

# GIF settings
MAKE_GIFS = True
GIF_DURATION_MS = 250
GIF_DOWNSAMPLE = 2

GIF_SPECS = {
    "GUST": {"vmin": 0,   "vmax": 70,  "cmap": "inferno", "units": "mph"},
    "TMP":  {"vmin": -10, "vmax": 60,  "cmap": "magma",   "units": TMP_UNITS},
    "RH":   {"vmin": 0,   "vmax": 100, "cmap": "viridis", "units": "%"},
}

GIF_ANNOTATE = True
GIF_ANNOTATE_TZ = "America/Denver"
GIF_ANNOTATE_FONT = None
GIF_ANNOTATE_FONTSIZE = 18


# -------------------------
# HELPERS
# -------------------------
def most_recent_cycle_utc(now_utc: datetime, cycle_hours: int = 6) -> datetime:
    now_utc = now_utc.replace(minute=0, second=0, microsecond=0, tzinfo=pytz.utc)
    hour_block = (now_utc.hour // cycle_hours) * cycle_hours
    return now_utc.replace(hour=hour_block)

def cycle_candidates_utc(now_utc: datetime, cycle_hours: int = 6, lag_hours: int = 3, max_cycles_back: int = 6):
    safe_time = now_utc - timedelta(hours=lag_hours)
    first = most_recent_cycle_utc(safe_time, cycle_hours=cycle_hours)
    for i in range(max_cycles_back + 1):
        yield first - timedelta(hours=i * cycle_hours)

def dataset_exists(fs, path: str) -> bool:
    try:
        return fs.exists(path) or fs.exists(path + "/.zgroup") or fs.exists(path + "/.zmetadata")
    except Exception:
        return False

def open_hrrr_fcst_ds(fs, init_time_utc: datetime, level: str, var: str) -> xr.Dataset:
    run_date = init_time_utc.strftime("%Y%m%d")
    run_hr = init_time_utc.strftime("%H")

    group_path = f"hrrrzarr/sfc/{run_date}/{run_date}_{run_hr}z_fcst.zarr/{level}/{var}"
    subgroup_path = f"{group_path}/{level}"

    if dataset_exists(fs, group_path):
        store = s3fs.S3Map(root=group_path, s3=fs, check=False)
        ds = xr.open_zarr(
            store,
            consolidated=CONSOLIDATED,
            chunks=OPEN_CHUNKS,
            decode_timedelta=True,
        )
        if var in ds.data_vars:
            return ds

    if dataset_exists(fs, subgroup_path):
        store = s3fs.S3Map(root=subgroup_path, s3=fs, check=False)
        ds = xr.open_zarr(
            store,
            consolidated=CONSOLIDATED,
            chunks=OPEN_CHUNKS,
            decode_timedelta=True,
        )
        if var in ds.data_vars:
            return ds

    raise FileNotFoundError(
        f"Could not open HRRR Zarr for run={init_time_utc.isoformat()} level={level} var={var}. "
        f"Tried:\n  s3://{group_path}\n  s3://{subgroup_path}"
    )

def detect_time_dim(da: xr.DataArray) -> str:
    for cand in ["forecast_period", "time", "valid_time", "step"]:
        if cand in da.dims:
            return cand
    spatial = {"projection_x_coordinate", "projection_y_coordinate", "x", "y"}
    for d in da.dims:
        if d not in spatial and da.sizes.get(d, 0) > 1:
            return d
    raise ValueError(f"Could not detect forecast/valid time dimension from dims={da.dims}")

def ensure_spatial_and_crs(da: xr.DataArray) -> xr.DataArray:
    rename_map = {}
    if "projection_x_coordinate" in da.dims:
        rename_map["projection_x_coordinate"] = "x"
    if "projection_y_coordinate" in da.dims:
        rename_map["projection_y_coordinate"] = "y"

    if rename_map:
        da = da.rename(rename_map)

    da = da.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
    da = da.rio.write_crs(HRRR_NATIVE_CRS, inplace=False)
    return da

def convert_units(var_key: str, da: xr.DataArray) -> xr.DataArray:
    c = VARS[var_key]["convert"]
    if c == "mps_to_mph":
        return da * 2.23694
    if c == "tmp_f":
        return (da - 273.15) * 9 / 5 + 32
    if c == "tmp_c":
        return da - 273.15
    if c == "tmp_k":
        return da
    return da

def tif_kwargs():
    kw = dict(tiled=TIF_TILED, BIGTIFF="IF_SAFER")
    if TIF_COMPRESS:
        kw["compress"] = TIF_COMPRESS
        if TIF_COMPRESS.upper() == "DEFLATE":
            kw["zlevel"] = TIF_ZLEVEL
    return kw

def out_units_for(var_key: str) -> str:
    if var_key == "GUST":
        return "mph"
    if var_key == "TMP":
        return TMP_UNITS
    if var_key == "RH":
        return "%"
    return ""

def multiband_out_path(var_key: str, init_time_utc: datetime, start_fh: int, end_fh: int) -> str:
    units = out_units_for(var_key)
    return os.path.join(
        OUT_DIR,
        f"HRRR_{var_key}_{units}_init{init_time_utc.strftime('%Y%m%d_%HZ')}_f{start_fh:02d}_f{end_fh:02d}_MULTIBAND.tif"
    )

def _load_font():
    if not GIF_ANNOTATE:
        return None
    try:
        if GIF_ANNOTATE_FONT and os.path.exists(GIF_ANNOTATE_FONT):
            return ImageFont.truetype(GIF_ANNOTATE_FONT, GIF_ANNOTATE_FONTSIZE)
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def _annotate(im: Image.Image, text: str, font):
    if not GIF_ANNOTATE:
        return im
    draw = ImageDraw.Draw(im)
    pad = 8
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = draw.textsize(text, font=font)
    x0, y0 = pad, pad
    bg = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 120))
    im_rgba = im.convert("RGBA")
    im_rgba.paste(bg, (x0 - pad, y0 - pad), bg)
    draw = ImageDraw.Draw(im_rgba)
    draw.text((x0, y0), text, fill=(255, 255, 255, 255), font=font)
    return im_rgba.convert("RGB")

def make_gif_from_multiband(multiband_path: str, var_key: str, init_time_utc: datetime, start_fh: int, end_fh: int, out_gif_path: str):
    import matplotlib.pyplot as plt

    spec = GIF_SPECS.get(var_key, {"vmin": 0, "vmax": 1, "cmap": "viridis", "units": ""})
    vmin, vmax, cmap_name, units = spec["vmin"], spec["vmax"], spec["cmap"], spec["units"]

    tz = pytz.timezone(GIF_ANNOTATE_TZ) if GIF_ANNOTATE_TZ else pytz.utc
    font = _load_font()

    frames = []
    with rasterio.open(multiband_path) as src:
        nbands = src.count
        expected = end_fh - start_fh + 1
        if nbands != expected:
            raise RuntimeError(f"Band count mismatch: file has {nbands}, expected {expected}")

        cmap = plt.get_cmap(cmap_name)

        for b in range(1, nbands + 1):
            fh = start_fh + (b - 1)
            valid_utc = init_time_utc + timedelta(hours=int(fh))
            valid_local = valid_utc.astimezone(tz)

            arr = src.read(b).astype(np.float32)
            arr = np.clip(arr, vmin, vmax)
            arr = (arr - vmin) / (vmax - vmin + 1e-9)
            arr8 = (arr * 255).astype(np.uint8)

            if GIF_DOWNSAMPLE and GIF_DOWNSAMPLE > 1:
                arr8 = arr8[::GIF_DOWNSAMPLE, ::GIF_DOWNSAMPLE]

            rgba = (cmap(arr8 / 255.0) * 255).astype(np.uint8)
            rgb = rgba[..., :3]
            im = Image.fromarray(rgb, mode="RGB")

            label = (
                f"HRRR {var_key} ({units})  f{fh:02d}  "
                f"valid {valid_local.strftime('%Y-%m-%d %H:%M %Z')}  "
                f"(init {init_time_utc.strftime('%Y-%m-%d %H:%MZ')})"
            )
            im = _annotate(im, label, font)
            frames.append(im)

    if not frames:
        raise RuntimeError("No frames created for GIF.")

    frames[0].save(
        out_gif_path,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=GIF_DURATION_MS,
        loop=0,
        optimize=False,
    )

def choose_available_cycle(fs, now_utc: datetime):
    last_error = None
    for cand in cycle_candidates_utc(
        now_utc,
        cycle_hours=CYCLE_HOURS,
        lag_hours=ARCHIVE_LAG_HOURS,
        max_cycles_back=MAX_CYCLES_BACK,
    ):
        try:
            _ = open_hrrr_fcst_ds(fs, cand, "surface", "GUST")
            return cand
        except Exception as e:
            last_error = e
            print(f"Cycle unavailable: {cand.isoformat()} -> {e}")
    raise RuntimeError(f"No usable HRRR forecast cycle found. Last error: {last_error}")


# -------------------------
# RUN
# -------------------------
now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
fs = s3fs.S3FileSystem(anon=True, default_fill_cache=False, default_cache_type="none")

print(f"NOW (UTC): {now_utc.isoformat()}")
print(f"OUT_DIR: {os.path.abspath(OUT_DIR)}")

init_time_utc = choose_available_cycle(fs, now_utc)
print(f"Using available HRRR init cycle (UTC): {init_time_utc.isoformat()}")

elapsed_hours = (now_utc - init_time_utc).total_seconds() / 3600.0
start_fh = int(math.ceil(max(1.0, elapsed_hours)))
requested_end_fh = start_fh + WINDOW_HOURS

print(f"Window request: start_fh=f{start_fh:02d} (>= now), requested_end_fh=f{requested_end_fh:02d} (now+{WINDOW_HOURS}h)")

with Env(GDAL_NUM_THREADS=GDAL_NUM_THREADS):
    for var_key, spec in VARS.items():
        level = spec["level"]
        varname = spec["name"]

        print(f"\nOpening {var_key} ({varname}) at level '{level}' ...")
        ds = open_hrrr_fcst_ds(fs, init_time_utc, level, varname)
        da = ds[varname]
        tdim = detect_time_dim(da)

        n_avail = int(da.sizes[tdim])
        max_fh_avail = n_avail
        var_end_fh = requested_end_fh

        if start_fh > max_fh_avail:
            ds.close()
            raise RuntimeError(
                f"start_fh=f{start_fh:02d} is beyond available forecast max f{max_fh_avail:02d}"
            )

        if var_end_fh > max_fh_avail:
            print(f"WARNING: Requested end_fh=f{var_end_fh:02d} but only up to f{max_fh_avail:02d} available; clipping.")
            var_end_fh = max_fh_avail

        # HRRR forecast zarr indexing is typically 0-based for f01..fXX
        isel_start = start_fh - 1
        isel_end_exclusive = var_end_fh

        da_all = da.isel({tdim: slice(isel_start, isel_end_exclusive)})
        da_all = convert_units(var_key, da_all)
        da_all = da_all.rename({tdim: "band"})
        da_all = ensure_spatial_and_crs(da_all)
        da_all = da_all.assign_coords(band=np.arange(1, (var_end_fh - start_fh + 1) + 1))

        mb_path = multiband_out_path(var_key, init_time_utc, start_fh, var_end_fh)
        print(f"  writing MULTIBAND: {os.path.basename(mb_path)} (bands=f{start_fh:02d}..f{var_end_fh:02d})")
        da_all.rio.to_raster(mb_path, **tif_kwargs())

        ds.close()
        del ds, da, da_all
        gc.collect()

        if MAKE_GIFS:
            out_gif = os.path.join(
                OUT_DIR,
                f"HRRR_{var_key}_init{init_time_utc.strftime('%Y%m%d_%HZ')}_f{start_fh:02d}_f{var_end_fh:02d}.gif"
            )
            print(f"  making GIF -> {os.path.basename(out_gif)}")
            make_gif_from_multiband(mb_path, var_key, init_time_utc, start_fh, var_end_fh, out_gif)

print(f"\nDone. Outputs in: {os.path.abspath(OUT_DIR)}")
