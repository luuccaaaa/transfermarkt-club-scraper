from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import requests

import sys
from pathlib import Path

# Add the scripts directory to the path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_players
import augment_player_profiles
from build_team_workbook import (
    DEFAULT_FIELD_ORDER,
    DEFAULT_OUTPUT as DEFAULT_WORKBOOK_PATH,
    load_club_names,
    iter_csv_files,
    read_rows,
    infer_club_name,
    build_workbook,
    get_available_fields,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent
CLUB_IDS_CSV = DATA_DIR / "data" / "club_ids.csv"
CLUBS_DIR = DATA_DIR / "data" / "clubs"
TEAM_WORKBOOK = DATA_DIR / "data" / "exports" / "team_list.xlsx"
AVAILABLE_FIELDS = get_available_fields()

DEFAULT_API_BASE_URL = os.environ.get("TRANSFERMARKT_API_BASE_URL", "http://localhost:8000")


@dataclass
class WorkflowResult:
    team_details: List[Dict[str, str]]
    club_ids_csv: Path
    generated_csvs: List[Path]
    augmented_csvs: List[Path]
    workbook_path: Path
    selected_fields: List[str]


class WorkflowError(Exception):
    """Raised when the workflow cannot be completed."""


def get_api_base_url() -> str:
    base_url = os.environ.get("TRANSFERMARKT_API_BASE_URL", DEFAULT_API_BASE_URL)
    return base_url.rstrip("/")


def get_proxy_status(*, base_url: Optional[str] = None) -> Dict[str, object]:
    url = f"{(base_url or get_api_base_url()).rstrip('/')}/status/proxies"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    payload = response.json()
    enabled = bool(payload.get("enabled"))
    count = int(payload.get("count", 0)) if payload.get("count") is not None else 0
    return {"enabled": enabled, "count": count}


def fetch_club_profile(club_id: str, base_url: str) -> Dict[str, str]:
    url = f"{base_url}/clubs/{club_id}/profile"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_club_name(profile: Dict[str, str], club_id: str) -> str:
    for key in ("name", "officialName"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return club_id


def fetch_club_players(club_id: str, base_url: str, season_id: Optional[str]) -> Dict:
    url = f"{base_url}/clubs/{club_id}/players"
    params = {"season_id": season_id} if season_id else None
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def write_club_ids_csv(team_details: Iterable[Dict[str, str]], destination: Path = CLUB_IDS_CSV) -> Path:
    rows = list(team_details)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["club_id", "club_name"])
        writer.writeheader()
        writer.writerows(rows)
    return destination


def generate_player_csv(club_id: str, club_name: str, payload: Dict) -> Path:
    parsed = fetch_players.extract_players_payload(payload, club_id)
    players = parsed["players"]
    fieldnames = fetch_players.normalise_fieldnames(players)
    if "club_id" not in fieldnames:
        fieldnames = ["club_id", *fieldnames]
    if "club_name" not in fieldnames:
        insert_index = 1 if fieldnames[0] == "club_id" else 0
        fieldnames = fieldnames[:insert_index] + ["club_name"] + fieldnames[insert_index:]
    target = CLUBS_DIR / f"{club_id}.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for player in players:
            if isinstance(player, dict):
                row = {
                    key: fetch_players.serialise_value(player.get(key))
                    for key in fieldnames
                    if key not in {"club_id", "club_name"}
                }
            else:
                value_key = next(
                    (name for name in fieldnames if name not in {"club_id", "club_name"}),
                    fieldnames[-1],
                )
                row = {value_key: fetch_players.serialise_value(player)}
            row["club_id"] = club_id
            row["club_name"] = club_name
            writer.writerow(row)
    return target


def build_team_workbook(
    output: Path = TEAM_WORKBOOK,
    *,
    field_ids: Sequence[str] | None = None,
    specific_csvs: List[Path] | None = None,
) -> Path:
    if not CLUBS_DIR.exists():
        raise WorkflowError("No club CSVs available; run player fetch first.")

    club_lookup = load_club_names(CLUB_IDS_CSV)
    club_rows: List[tuple[str, List[dict[str, str]]]] = []

    # Use specific CSVs if provided, otherwise fall back to all CSVs in directory
    csv_paths = specific_csvs if specific_csvs else list(iter_csv_files(CLUBS_DIR))

    for path in csv_paths:
        if not path.exists():
            continue
        rows = read_rows(path)
        if not rows:
            continue
        club_name = infer_club_name(path, rows, club_lookup)
        club_rows.append((club_name, rows))

    if not club_rows:
        raise WorkflowError("No club data available to build workbook.")

    build_workbook(club_rows, output, field_ids=field_ids)
    return output


def run_workflow(
    team_ids: Iterable[str],
    *,
    season_id: Optional[str] = None,
    base_url: Optional[str] = None,
    selected_fields: Sequence[str] | None = None,
    logger: Callable[[str], None] | None = None,
) -> WorkflowResult:
    base = (base_url or get_api_base_url()).rstrip("/")
    team_details: List[Dict[str, str]] = []

    def emit(message: str) -> None:
        if logger:
            logger(message)
        else:
            print(message)

    selected_fields_list = list(selected_fields) if selected_fields else list(DEFAULT_FIELD_ORDER)
    selected_fields_list = [field for field in selected_fields_list if field in AVAILABLE_FIELDS]
    if not selected_fields_list:
        selected_fields_list = list(DEFAULT_FIELD_ORDER)
    team_ids_list = [club_id.strip() for club_id in team_ids if club_id and club_id.strip()]
    emit(f"Starting workflow for {len(team_ids_list)} club IDs")
    if not team_ids_list:
        raise WorkflowError("No valid club IDs provided.")

    emit("Step 1: fetching club profiles")

    # Step 1: fetch club profiles to gather names
    for club_id in team_ids_list:
        profile = fetch_club_profile(club_id, base)
        club_name = extract_club_name(profile, club_id)
        team_details.append({"club_id": club_id, "club_name": club_name})
        emit(f"  Retrieved profile: {club_id} — {club_name}")

    # Step 2: persist club IDs CSV
    emit("Step 2: writing club_ids.csv")
    club_ids_csv = write_club_ids_csv(team_details)
    emit(f"  Saved {club_ids_csv}")

    # Step 3: fetch players and create CSVs
    CLUBS_DIR.mkdir(parents=True, exist_ok=True)
    generated_csvs: List[Path] = []
    emit("Step 3: fetching players and exporting CSVs")
    for details in team_details:
        payload = fetch_club_players(details["club_id"], base, season_id)
        csv_path = generate_player_csv(details["club_id"], details["club_name"], payload)
        generated_csvs.append(csv_path)
        emit(f"  Exported roster CSV: {csv_path.name}")

    # Step 4: augment player CSVs
    augmented_csvs: List[Path] = []
    emit("Step 4: augmenting player profiles")
    for csv_path in generated_csvs:
        emit(f"  Augmenting {csv_path.name}")
        augment_player_profiles.process_club_file(
            csv_path,
            delay=0.0,
            retries=augment_player_profiles.DEFAULT_RETRIES,
            force=True,
            cooldown=30.0,
            proxies=None,
            base_url=base,
            logger=emit,
        )
        augmented_csvs.append(csv_path)

    # Step 5: build Excel workbook
    emit("Step 5: building Excel workbook")
    workbook_path = build_team_workbook(field_ids=selected_fields_list, specific_csvs=augmented_csvs)
    emit(f"Workflow complete. Workbook saved to {workbook_path}")

    return WorkflowResult(
        team_details=team_details,
        club_ids_csv=club_ids_csv,
        generated_csvs=generated_csvs,
        augmented_csvs=augmented_csvs,
        workbook_path=workbook_path,
        selected_fields=selected_fields_list,
    )
