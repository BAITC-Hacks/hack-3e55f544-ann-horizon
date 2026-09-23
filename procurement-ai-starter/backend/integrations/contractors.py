import csv
import json
import os
from pathlib import Path
from typing import Protocol

from backend.models.contractor import ContractorProfile


class ContractorCatalogAdapter(Protocol):
    def list_profiles(self) -> list[ContractorProfile]: ...


class FileContractorCatalogAdapter:
    """Reads the provided anonymized JSONL/CSV catalog without rewriting its records."""

    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        configured = path or os.getenv("CONTRACTOR_CATALOG_PATH")
        self.path = Path(configured) if configured else root / "data" / "hackathon-dataset-anonymized.jsonl"

    def list_profiles(self) -> list[ContractorProfile]:
        path = self.path
        if not path.exists() and path.name == "hackathon-dataset-anonymized.jsonl":
            csv_path = path.with_suffix(".csv")
            if csv_path.exists():
                path = csv_path
        if not path.exists():
            raise FileNotFoundError(
                f"Contractor catalog is missing. Put hackathon-dataset-anonymized.jsonl in data/ "
                f"or set CONTRACTOR_CATALOG_PATH. Expected: {self.path}"
            )
        if path.suffix.casefold() == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif path.suffix.casefold() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        elif path.suffix.casefold() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("profiles", [])
        else:
            raise ValueError("Contractor catalog must be a .jsonl, .csv or .json file")
        return [ContractorProfile.model_validate(self._normalize_row(row)) for row in rows]

    @classmethod
    def _normalize_row(cls, row: dict) -> dict:
        result = dict(row)
        for field in ("categories", "event_formats", "languages", "busy_dates"):
            result[field] = cls._list_value(result.get(field))
        for field in ("synthetic", "city_imputed", "price_imputed"):
            value = result.get(field, False)
            result[field] = value if isinstance(value, bool) else str(value).strip().casefold() in {"1", "true", "yes"}
        max_hours = result.get("max_hours")
        if max_hours is None or str(max_hours).strip().casefold() in {"", "null", "none"}:
            result["max_hours"] = None
        return result

    @staticmethod
    def _list_value(value) -> list:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        text = str(value).strip()
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        return [part.strip() for part in text.replace(";", "|").replace(",", "|").split("|") if part.strip()]
