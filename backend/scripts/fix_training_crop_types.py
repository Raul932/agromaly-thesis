"""
One-time fix script: update crop_type for parcels imported from training_gpx.

Reads all .gpx files in backend/data/training_gpx/, extracts parcel name and
crop type from each, then updates any DB parcels with a matching name that
currently have crop_type = 'unknown'.

Usage (from repo root, with DB reachable):
    cd backend
    python scripts/fix_training_crop_types.py

Requires: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST env vars
(same as the .env file used by Docker Compose).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Crop detection — mirrors the logic in gpx_upload.py
# ---------------------------------------------------------------------------

_CROP_MAP: dict[str, str] = {
    "porumb":      "CORN",
    "corn":        "CORN",
    "grau":        "WHEAT",   # matches "grâu" after diacritic stripping
    "wheat":       "WHEAT",
    "floarea":     "SUNFLOWER",
    "sunflower":   "SUNFLOWER",
    "soia":        "SOYBEAN",
    "soybean":     "SOYBEAN",
    "rapita":      "RAPESEED",
    "rapeseed":    "RAPESEED",
    "orz":         "BARLEY",
    "barley":      "BARLEY",
    "cartof":      "POTATO",
    "potato":      "POTATO",
    "sfecla":      "SUGAR_BEET",
    "vie":         "VINEYARD",
    "viticultura": "VINEYARD",
    "livada":      "ORCHARD",
    "fanete":      "MEADOW",  # matches "fânețe" after diacritic stripping
    "pasune":      "MEADOW",
    "meadow":      "MEADOW",
    "grassland":   "MEADOW",
}

_DIACRITIC_TABLE = str.maketrans("âÂăĂîÎșȘşŞțȚţŢ", "aAaAiIsSSStTtT")


def _detect_crop(hint: str | None) -> str:
    if not hint:
        return "unknown"
    normalized = hint.translate(_DIACRITIC_TABLE).lower()
    for keyword, crop in _CROP_MAP.items():
        if keyword in normalized:
            return crop
    return "unknown"


# ---------------------------------------------------------------------------
# Parse all GPX files and build name → crop_type map
# ---------------------------------------------------------------------------

def build_crop_map(gpx_dir: Path) -> dict[str, str]:
    """Return {parcel_name: crop_type} for every GPX file in gpx_dir."""
    try:
        import gpxpy  # type: ignore
    except ImportError:
        sys.exit("gpxpy not installed — run: pip install gpxpy")

    mapping: dict[str, str] = {}
    for gpx_file in sorted(gpx_dir.glob("*.gpx")):
        try:
            gpx = gpxpy.parse(gpx_file.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            print(f"  WARNING: Could not parse {gpx_file.name}: {exc}")
            continue

        for track in gpx.tracks:
            name = (track.name or gpx_file.stem).strip()
            detected_crop = (track.description or "").strip() or None
            crop = _detect_crop(detected_crop)
            mapping[name] = crop
            print(f"  {gpx_file.name}: '{name}' → {crop} (from '{detected_crop}')")

    return mapping


# ---------------------------------------------------------------------------
# Apply updates directly via psycopg2
# ---------------------------------------------------------------------------

def apply_updates(crop_map: dict[str, str]) -> None:
    try:
        import psycopg2  # type: ignore
    except ImportError:
        sys.exit("psycopg2 not installed — run: pip install psycopg2-binary")

    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = int(os.getenv("POSTGRES_PORT", "5432"))
    db_name = os.getenv("POSTGRES_DB", "agromaly")
    db_user = os.getenv("POSTGRES_USER", "agromaly")
    db_pass = os.getenv("POSTGRES_PASSWORD", "")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_pass,
    )
    conn.autocommit = False
    cur = conn.cursor()

    # Query the actual valid enum values so we never crash on missing ones.
    cur.execute(
        "SELECT enumlabel FROM pg_enum "
        "WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'croptype') "
        "ORDER BY enumsortorder"
    )
    valid_db_values = {row[0] for row in cur.fetchall()}
    print(f"Valid croptype values in DB: {sorted(valid_db_values)}\n")

    updated = 0
    skipped = 0
    missing_from_enum = []

    for name, crop in crop_map.items():
        if crop == "UNKNOWN":
            skipped += 1
            continue  # Nothing to fix — source GPX itself has no crop

        if crop not in valid_db_values:
            print(f"  SKIP '{name}': crop '{crop}' not in DB enum yet — run the migration first")
            missing_from_enum.append(crop)
            continue

        cur.execute(
            """
            UPDATE parcels
               SET crop_type  = %s::croptype,
                   updated_at = NOW()
             WHERE name            = %s
               AND crop_type::text = 'UNKNOWN'
            """,
            (crop, name),
        )
        rows = cur.rowcount
        if rows:
            print(f"  Updated {rows} row(s): '{name}' → {crop}")
            updated += rows
        else:
            print(f"  No match (already correct or not in DB): '{name}'")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone — {updated} row(s) updated, {skipped} GPX file(s) had no detectable crop.")
    if missing_from_enum:
        missing = sorted(set(missing_from_enum))
        print(f"\nWARNING: {len(missing)} crop value(s) not yet in the DB enum: {missing}")
        print("Run this to add them, then re-run the script:")
        for v in missing:
            print(f"  docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -c \"ALTER TYPE croptype ADD VALUE '{v}';\"")



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    gpx_dir = Path(__file__).parent.parent / "data" / "training_gpx"
    if not gpx_dir.is_dir():
        sys.exit(f"GPX directory not found: {gpx_dir}")

    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv  # type: ignore
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            print(f"Loaded env from {env_file}")
    except ImportError:
        pass

    print(f"\nReading GPX files from: {gpx_dir}\n")
    crop_map = build_crop_map(gpx_dir)

    print(f"\nFound {len(crop_map)} parcel(s) in GPX files. Applying DB updates…\n")
    apply_updates(crop_map)
