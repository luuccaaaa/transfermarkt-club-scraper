#!/usr/bin/env python3
"""Augment club player CSVs with detailed player profile data.

The script iterates over CSV files in a clubs directory, fetching each
player's profile via the local API. Results are persisted incrementally after
every successful profile so the process can resume if interrupted."""
from __future__ import annotations

import argparse
import csv
import json
import random
import tempfile
import time
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener, install_opener, urlopen

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CLUBS_DIR = DATA_DIR / "clubs"
DEFAULT_API_BASE_URL = os.environ.get("TRANSFERMARKT_API_BASE_URL", "http://localhost:8000")
DEFAULT_DELAY_SECONDS = 5.0
DEFAULT_RETRIES = 3
NON_RETRIABLE_STATUS = {400, 401, 403, 404, 422}
PROXY_FILE = DATA_DIR / "proxy.txt"


def iter_club_files(directory: Path) -> Iterable[Path]:
    return sorted(p for p in directory.glob("*.csv") if p.is_file())


def read_rows(path: Path) -> tuple[List[Dict[str, str]], List[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def persist_rows(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent))
    try:
        with open(tmp_fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(tmp_path).replace(path)
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def load_proxies(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Proxy file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        proxies = [line.strip() for line in fh if line.strip()]
    if not proxies:
        raise ValueError("Proxy list is empty")
    return proxies


def choose_proxy(proxies: List[str]) -> str:
    return random.choice(proxies)


def build_profile_url(player_id: str, base_url: str | None = None) -> str:
    base = (base_url or DEFAULT_API_BASE_URL).rstrip("/")
    return f"{base}/players/{player_id}/profile"


def fetch_profile(player_id: str, proxy: str | None = None, *, base_url: str | None = None) -> Dict[str, Any]:
    url = build_profile_url(player_id, base_url)
    request = Request(url, headers={"Accept": "application/json"})

    if proxy:
        handler = ProxyHandler({"http": proxy, "https": proxy})
        opener = build_opener(handler)
        install_opener(opener)
    else:
        install_opener(build_opener())

    with urlopen(request) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def fetch_with_retry(
    player_id: str,
    *,
    retries: int,
    delay: float,
    proxies: List[str] | None,
    base_url: str | None,
) -> Dict[str, Any]:
    attempt = 1
    while True:
        proxy = choose_proxy(proxies) if proxies else None
        try:
            return fetch_profile(player_id, proxy=proxy, base_url=base_url)
        except HTTPError as exc:
            if exc.code in NON_RETRIABLE_STATUS:
                raise
            if attempt >= retries:
                raise
            backoff = max(0.0, delay) * (2 ** (attempt - 1)) or 1.0
            print(f"      Attempt {attempt}/{retries} failed ({exc}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
            attempt += 1
        except (URLError, json.JSONDecodeError) as exc:
            if attempt >= retries:
                raise
            backoff = max(0.0, delay) * (2 ** (attempt - 1)) or 1.0
            print(f"      Attempt {attempt}/{retries} failed ({exc}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
            attempt += 1


def serialise_value(value: Any) -> str:
    if isinstance(value, (str, int, float)) or value is None:
        return "" if value is None else str(value)
    if isinstance(value, list):
        return ";".join(serialise_value(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def flatten_profile(profile: Dict[str, Any]) -> Dict[str, str]:
    flat: Dict[str, str] = {}
    for key, value in profile.items():
        flat[f"profile_{key}"] = serialise_value(value)
    return flat


def determine_player_id(row: Dict[str, str]) -> str | None:
    for key in ("id", "player_id", "playerId", "profile_id"):
        value = row.get(key)
        if value and value.strip():
            return value.strip()
    return None


def process_club_file(
    path: Path,
    *,
    delay: float,
    retries: int,
    force: bool,
    cooldown: float,
    proxies: List[str] | None,
    base_url: str | None = None,
    logger: Callable[[str], None] | None = None,
) -> None:
    def log(message: str) -> None:
        if logger:
            logger(message)
        else:
            print(message)

    rows, fieldnames = read_rows(path)
    if not rows:
        log("    No rows found; skipping")
        return

    ordered_fields = list(fieldnames)
    total_players = len(rows)

    for idx, row in enumerate(rows, start=1):
        player_id = determine_player_id(row)
        if not player_id:
            continue
        if not force and row.get("profile_id"):
            continue

        log(f"    Player {idx}/{total_players}: fetching profile for {player_id}")
        try:
            profile = fetch_with_retry(
                player_id,
                retries=max(1, retries),
                delay=max(0.0, delay),
                proxies=proxies,
                base_url=base_url,
            )
        except HTTPError as exc:
            status = getattr(exc, "code", None)
            log(f"      Failed to fetch player {player_id}: {exc}")
            if status in {403, 429}:
                sleep_for = max(delay, cooldown)
                log(f"      Rate limit suspected; sleeping {sleep_for:.1f}s before continuing")
                time.sleep(sleep_for)
            continue
        except (URLError, json.JSONDecodeError, ValueError) as exc:
            log(f"      Failed to process player {player_id}: {exc}")
            continue

        flat = flatten_profile(profile)
        row_changed = False
        for key, value in flat.items():
            if key not in ordered_fields:
                ordered_fields.append(key)
            if row.get(key) != value:
                row[key] = value
                row_changed = True

        if row_changed:
            persist_rows(path, rows, ordered_fields)

        if idx < total_players:
            time.sleep(max(0.0, delay))

    persist_rows(path, rows, ordered_fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Append player profile data to club CSVs.")
    parser.add_argument("--clubs-dir", type=Path, default=DEFAULT_CLUBS_DIR,
                        help="Directory containing club CSV files (default: clubs)")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE_URL,
                        help="Base URL for the Transfermarkt API (default: env TRANSFERMARKT_API_BASE_URL or http://localhost:8000)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help="Seconds between successive API calls (default: 5)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES,
                        help="Max retry attempts for transient failures (default: 3)")
    parser.add_argument("--force", action="store_true",
                        help="Fetch profiles even if profile columns already exist")
    parser.add_argument("--cooldown", type=float, default=30.0,
                        help="Extra wait after rate-limit responses (default: 30)")
    parser.add_argument("--use-proxies", action="store_true",
                        help="Enable proxy rotation from proxy.txt")
    parser.add_argument("--proxy-file", default=str(PROXY_FILE),
                        help="Path to proxy list file (default: proxy.txt in data dir)")
    args = parser.parse_args()

    clubs_dir = args.clubs_dir
    api_base = args.api_base
    if not clubs_dir.exists():
        raise FileNotFoundError(f"Missing directory: {clubs_dir}")

    proxies: List[str] | None = None
    if args.use_proxies:
        proxies = load_proxies(Path(args.proxy_file))
        print(f"Loaded {len(proxies)} proxies")

    club_files = list(iter_club_files(clubs_dir))
    if not club_files:
        print(f"No CSV files found in {clubs_dir}")
        return

    for club_index, path in enumerate(club_files, start=1):
        print(f"[{club_index}/{len(club_files)}] Processing {path.name}")
        try:
            process_club_file(
                path,
                delay=max(0.0, args.delay),
                retries=max(1, args.max_retries),
                force=args.force,
                cooldown=max(0.0, args.cooldown),
                proxies=proxies,
                base_url=api_base,
                logger=None,
            )
        except KeyboardInterrupt:
            print("Interrupted by user; latest progress persisted.")
            raise


if __name__ == "__main__":
    main()
