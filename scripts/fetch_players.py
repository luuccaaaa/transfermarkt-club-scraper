#!/usr/bin/env python3
"""Fetch club players from the local API and export them as CSV files.

Skips clubs where a CSV already exists unless --force is used, and retries
failed requests with exponential backoff."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATA_DIR = Path(__file__).resolve().parent
CLUB_IDS_CSV = DATA_DIR / "club_ids.csv"
OUTPUT_DIR = DATA_DIR / "clubs"
BASE_URL = "http://localhost:8000/clubs/{club_id}/players"
DEFAULT_DELAY_SECONDS = 5.0
DEFAULT_RETRIES = 3


def load_club_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing club IDs file: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        raise ValueError("club_ids.csv has no data rows")
    if "club_id" not in rows[0]:
        raise ValueError("club_ids.csv missing 'club_id' column header")
    return rows


def fetch_players(club_id: str, season_id: str | None) -> Any:
    query = ""
    if season_id:
        query = "?" + urlencode({"season_id": season_id})
    url = BASE_URL.format(club_id=club_id) + query
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def fetch_with_retry(club_id: str, season_id: str | None, *, retries: int, delay: float) -> Any:
    attempt = 0
    while True:
        attempt += 1
        try:
            return fetch_players(club_id, season_id)
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            if attempt > retries:
                raise
            backoff = delay * (2 ** (attempt - 1))
            print(f"    Attempt {attempt}/{retries} failed ({exc}); retrying in {backoff:.1f}s")
            time.sleep(backoff)


def extract_players_payload(payload: Any, club_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected payload type; expected object")

    players = payload.get("players")
    if not isinstance(players, list):
        raise ValueError("Missing players array in response")

    club_name = payload.get("id")
    if not isinstance(club_name, str) or not club_name.strip():
        club_name = f"club_{club_id}"

    return {"club_name": club_name, "players": players}


def normalise_fieldnames(players: Iterable[Any]) -> List[str]:
    fieldnames: List[str] = []
    seen = set()
    for player in players:
        if isinstance(player, dict):
            for key in player.keys():
                if key not in seen:
                    fieldnames.append(key)
                    seen.add(key)
        else:
            if "value" not in seen:
                fieldnames.append("value")
                seen.add("value")
    if not fieldnames:
        fieldnames.append("player")
    return fieldnames


def sanitise_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    safe = safe.strip("_")
    return safe.lower() or "club"


def serialise_value(value: Any) -> str:
    if isinstance(value, (str, int, float)) or value is None:
        return "" if value is None else str(value)
    if isinstance(value, list):
        return ";".join(serialise_value(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def existing_csv_for_club(club_id: str, club_name: str | None) -> Path | None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    direct = OUTPUT_DIR / f"{club_id}.csv"
    if direct.exists():
        return direct
    if club_name:
        base = sanitise_filename(club_name)
        for candidate in OUTPUT_DIR.glob(f"{base}*.csv"):
            if candidate.is_file():
                return candidate
    matches = sorted(OUTPUT_DIR.glob(f"*{club_id}*.csv"))
    return matches[0] if matches else None


def write_players_csv(club_name: str, players: Sequence[Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = sanitise_filename(club_name)
    target = OUTPUT_DIR / f"{filename}.csv"

    fieldnames = normalise_fieldnames(players)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for player in players:
            if isinstance(player, dict):
                writer.writerow({key: serialise_value(player.get(key)) for key in fieldnames})
            else:
                writer.writerow({fieldnames[0]: serialise_value(player)})
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch club player lists and export CSV files.")
    parser.add_argument("--season-id", help="Optional season_id query parameter", default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help="Base seconds to wait between requests (default: 5)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES,
                        help="Number of retry attempts on failure (default: 3)")
    parser.add_argument("--force", action="store_true",
                        help="Fetch even if a CSV already exists")
    args = parser.parse_args()

    rows = load_club_rows(CLUB_IDS_CSV)
    total = len(rows)

    for index, row in enumerate(rows, start=1):
        club_id = row.get("club_id", "").strip()
        club_name_hint = row.get("club_name", "").strip()
        if not club_id:
            continue
        existing = existing_csv_for_club(club_id, club_name_hint or None)
        if existing and not args.force:
            print(f"[{index}/{total}] Skipping club {club_id}; CSV already exists ({existing.name})")
            continue

        print(f"[{index}/{total}] Fetching club {club_id}…", flush=True)
        try:
            raw_payload = fetch_with_retry(
                club_id,
                args.season_id,
                retries=max(1, args.max_retries),
                delay=max(0.0, args.delay),
            )
            parsed = extract_players_payload(raw_payload, club_id)
            target = write_players_csv(parsed["club_name"], parsed["players"])
            print(f"    Saved {target}")
        except (HTTPError, URLError) as exc:
            print(f"    Failed to fetch club {club_id}: {exc}")
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            print(f"    Failed to process club {club_id}: {exc}")

        if index < total:
            time.sleep(max(0.0, args.delay))


if __name__ == "__main__":
    main()
