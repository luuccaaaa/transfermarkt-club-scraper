#!/usr/bin/env python3
"""Fetch club profiles and refresh the club IDs CSV with up-to-date names."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATA_DIR = Path(__file__).resolve().parent
CLUB_IDS_CSV = DATA_DIR / "club_ids.csv"
PLAYERS_DIR = DATA_DIR / "clubs"
PROFILE_URL = "http://localhost:8000/clubs/{club_id}/profile"
DEFAULT_DELAY_SECONDS = 5.0
DEFAULT_RETRIES = 3

def load_club_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing club IDs file: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        raise ValueError("club_ids.csv has no data rows")
    if "club_id" not in fieldnames:
        raise ValueError("club_ids.csv missing 'club_id' column header")
    if "club_name" not in fieldnames:
        fieldnames.append("club_name")
        for row in rows:
            row.setdefault("club_name", "")
    return rows, fieldnames


def fetch_club_profile(club_id: str) -> Dict[str, Any]:
    url = PROFILE_URL.format(club_id=club_id)
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def fetch_with_retry(club_id: str, *, retries: int, delay: float) -> Dict[str, Any]:
    attempt = 1
    while True:
        try:
            return fetch_club_profile(club_id)
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            if attempt >= retries:
                raise
            backoff = max(0.0, delay) * (2 ** (attempt - 1)) or 1.0
            print(f"    Attempt {attempt}/{retries} failed ({exc}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
            attempt += 1


def extract_club_name(profile: Dict[str, Any], club_id: str) -> str:
    for key in ("name", "officialName"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return club_id


def update_club_ids_csv(rows: List[Dict[str, str]], fieldnames: List[str], names: Dict[str, str]) -> None:
    if "club_name" not in fieldnames:
        fieldnames = fieldnames + ["club_name"]
    for row in rows:
        club_id = row.get("club_id", "").strip()
        if not club_id:
            continue
        new_name = names.get(club_id)
        if new_name:
            row["club_name"] = new_name
        else:
            row.setdefault("club_name", row.get("club_name", ""))
    with CLUB_IDS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update club_ids.csv with fresh club names from profiles.")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help="Base seconds to wait between profile requests (default: 5)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES,
                        help="Maximum attempts per club (default: 3)")
    parser.add_argument("--force", action="store_true",
                        help="Fetch profiles even if a club name is already present")
    args = parser.parse_args()

    if not PLAYERS_DIR.exists():
        raise FileNotFoundError(f"Missing players directory: {PLAYERS_DIR}")

    rows, fieldnames = load_club_rows(CLUB_IDS_CSV)
    club_names: Dict[str, str] = {}
    total = len(rows)

    for index, row in enumerate(rows, start=1):
        club_id = row.get("club_id", "").strip()
        if not club_id:
            continue

        existing_name = row.get("club_name", "").strip()
        need_fetch = args.force or not existing_name
        if not need_fetch:
            print(f"[{index}/{total}] Skipping club {club_id}; club name already recorded")
            continue

        print(f"[{index}/{total}] Fetching profile for club {club_id}…", flush=True)
        try:
            profile = fetch_with_retry(
                club_id,
                retries=max(1, args.max_retries),
                delay=max(0.0, args.delay),
            )
            club_name = extract_club_name(profile, club_id)
            club_names[club_id] = club_name
        except (HTTPError, URLError) as exc:
            print(f"    Failed to fetch profile for club {club_id}: {exc}")
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"    Failed to process profile for club {club_id}: {exc}")

        if index < total:
            time.sleep(max(0.0, args.delay))

    update_club_ids_csv(rows, fieldnames, club_names)
    print(f"Updated {CLUB_IDS_CSV} with club names")


if __name__ == "__main__":
    main()
