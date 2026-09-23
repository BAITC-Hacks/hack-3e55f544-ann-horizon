"""Daily archived-weather replay for the HackAlemAI wind forecast case."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = ROOT / "outputs"
RUN_CACHE = CACHE_DIR / "runs"
TIMEZONE = "Asia/Almaty"
LOCAL_TZ = ZoneInfo(TIMEZONE)
MODEL_NAME = "ecmwf_ifs"  # ECMWF IFS HRES, 9 km
SINGLE_RUN_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_100m",
    "wind_direction_80m",
    "wind_gusts_10m",
]
FEATURE_COLUMNS = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_100m",
    "wind_gusts_10m",
    "wind_direction_sin",
    "wind_direction_cos",
    "hour_sin",
    "hour_cos",
    "day_of_year_sin",
    "day_of_year_cos",
    "lead_hours",
    "run_lead_hours",
]
POWER_FEATURE_COLUMNS = [*FEATURE_COLUMNS, "wind_speed_site_estimate"]
COORDINATES = {
    "turbine_1": {"latitude": 43.645150, "longitude": 78.535604},
    "turbine_2": {"latitude": 43.643198, "longitude": 78.538828},
}
# The turbines are less than 0.5 km apart and resolve to the same 9 km IFS grid cell.
WEATHER_POINT = {
    "latitude": sum(x["latitude"] for x in COORDINATES.values()) / 2,
    "longitude": sum(x["longitude"] for x in COORDINATES.values()) / 2,
}
SOURCE_COLUMNS = {
    "timestamp": "Статистическое время",
    "wind_speed": "Средняя скорость ветра(m/s)",
    "power": "Нормализованная активная мощность",
    "temperature": "Средняя температура окружающей среды(°C)",
}


class AgentError(RuntimeError):
    """An actionable failure found by one of the forecast agents."""


@dataclass
class IssueForecast:
    issue_date: date
    target_date: date
    run_utc: datetime
    weather: pd.DataFrame
    fallback_used: bool


class EventJournal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, issue_date: date | str, stage: str, status: str, **details: Any) -> None:
        event = {
            "event_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "issue_date": str(issue_date),
            "stage": stage,
            "status": status,
            **details,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


class WeatherArchiveTool:
    """Fetch one complete, archived ECMWF run and cache the raw response."""

    def __init__(self, journal: EventJournal, refresh: bool = False):
        self.journal = journal
        self.refresh = refresh
        RUN_CACHE.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_path(run_utc: datetime) -> Path:
        return RUN_CACHE / f"ecmwf_ifs_{run_utc:%Y%m%dT%H}Z.json"

    def fetch_run(self, run_utc: datetime) -> dict[str, Any]:
        if run_utc.tzinfo is None:
            run_utc = run_utc.replace(tzinfo=timezone.utc)
        run_utc = run_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        cache_path = self._cache_path(run_utc)
        if cache_path.exists() and not self.refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("error"):
                raise AgentError(payload.get("reason", "Cached weather error"))
            return payload

        params = {
            "latitude": f"{WEATHER_POINT['latitude']:.6f}",
            "longitude": f"{WEATHER_POINT['longitude']:.6f}",
            "run": run_utc.strftime("%Y-%m-%dT%H:%M"),
            "models": MODEL_NAME,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": TIMEZONE,
            "wind_speed_unit": "ms",
            "temperature_unit": "celsius",
            "forecast_days": 4,
        }
        url = SINGLE_RUN_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "HackAlem-Wind-Agent/1.0 (archived forecast replay)"},
        )
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("error"):
                    raise AgentError(payload.get("reason", "Open-Meteo returned an error"))
                if "hourly" not in payload or "time" not in payload["hourly"]:
                    raise AgentError("The archived weather response has no hourly series")
                cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                self.journal.write(
                    "weather-cache",
                    "fetch_archived_run",
                    "fetched",
                    run_utc=run_utc.isoformat(),
                    cache_file=str(cache_path.relative_to(ROOT)),
                    url=url,
                )
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AgentError) as exc:
                last_error = exc
                if isinstance(exc, AgentError) and "not available" in str(exc).lower():
                    break
                time.sleep(1.25 * (attempt + 1))
        raise AgentError(f"Cannot retrieve ECMWF run {run_utc:%Y-%m-%dT%H:%M} UTC: {last_error}")

    @staticmethod
    def to_frame(payload: dict[str, Any]) -> pd.DataFrame:
        hourly = payload["hourly"]
        frame = pd.DataFrame(hourly)
        frame["time"] = pd.to_datetime(frame["time"])
        for col in HOURLY_VARIABLES:
            if col not in frame:
                frame[col] = np.nan
        direction = np.deg2rad(pd.to_numeric(frame["wind_direction_80m"], errors="coerce"))
        frame["wind_direction_sin"] = np.sin(direction)
        frame["wind_direction_cos"] = np.cos(direction)
        return frame.set_index("time").sort_index()

    def issue_forecast(self, issue_date: date, cache_group: str) -> IssueForecast:
        """At local midnight, use the latest cycle expected to be published by then."""
        target_date = issue_date + timedelta(days=1)
        previous_utc_date = issue_date - timedelta(days=1)
        # 00:00 local in Kazakhstan is 19:00 UTC on the prior date. ECMWF 12Z
        # is normally published by 16-18Z; older cycles are deterministic fallbacks.
        candidates = [
            datetime.combine(previous_utc_date, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=h)
            for h in (12, 6, 0)
        ]
        errors: list[str] = []
        for candidate_index, run_utc in enumerate(candidates):
            try:
                payload = self.fetch_run(run_utc)
                weather = self.to_frame(payload)
                day = weather[weather.index.date == target_date]
                required = ["wind_speed_80m", "temperature_2m"]
                if len(day) != 24 or day[required].isna().any().any():
                    raise AgentError(
                        f"Run has {len(day)} target-day hours or missing required weather values"
                    )
                self.journal.write(
                    issue_date,
                    "weather_agent",
                    "selected",
                    target_date=target_date,
                    run_utc=run_utc.isoformat(),
                    run_fallback_rank=candidate_index,
                    cache_group=cache_group,
                    valid_hours=len(day),
                    location={**WEATHER_POINT, "timezone": TIMEZONE},
                    model=MODEL_NAME,
                )
                return IssueForecast(
                    issue_date=issue_date,
                    target_date=target_date,
                    run_utc=run_utc,
                    weather=day.copy(),
                    fallback_used=candidate_index > 0,
                )
            except Exception as exc:
                errors.append(f"{run_utc:%Y-%m-%dT%H}: {exc}")
        raise AgentError(f"No valid archived run for issue {issue_date}: {'; '.join(errors)}")


def read_operational_history() -> dict[str, pd.DataFrame]:
    history: dict[str, pd.DataFrame] = {}
    for turbine in COORDINATES:
        path = RAW_DIR / f"{turbine}.csv"
        if not path.exists():
            raise AgentError(f"Missing input CSV: {path}")
        raw = pd.read_csv(path, encoding="utf-8-sig")
        missing = [column for column in SOURCE_COLUMNS.values() if column not in raw.columns]
        if missing:
            raise AgentError(f"{path.name} is missing columns: {missing}")
        raw = raw[[SOURCE_COLUMNS[k] for k in SOURCE_COLUMNS]].copy()
        raw.columns = ["timestamp", "wind_observed", "power", "temperature_observed"]
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
        for name in ("wind_observed", "power", "temperature_observed"):
            raw[name] = pd.to_numeric(raw[name], errors="coerce")
        raw = raw.dropna(subset=["timestamp", "power", "wind_observed"])
        raw["hour"] = raw["timestamp"].dt.floor("h")
        hourly = raw.groupby("hour", sort=True).agg(
            wind_observed=("wind_observed", "mean"),
            power=("power", "mean"),
            temperature_observed=("temperature_observed", "mean"),
            source_samples=("timestamp", "size"),
        )
        hourly.index.name = "time"
        # Ignore hours with too little source coverage; complete hours have six samples.
        hourly.loc[hourly["source_samples"] < 3, ["wind_observed", "power"]] = np.nan
        hourly["turbine"] = turbine
        history[turbine] = hourly
    return history


def issue_dates_for_training() -> list[date]:
    start = date(2024, 3, 15)  # ECMWF IFS HRES Single Runs archive starts on 2024-03-14.
    end = date(2025, 12, 31)
    dates: set[date] = set()
    current = start
    while current <= end:
        dates.add(current)
        current += timedelta(days=3)
    # Daily archived runs near the end support the January frozen-model holdout.
    current = date(2025, 12, 31)
    while current <= date(2026, 1, 30):
        dates.add(current)
        current += timedelta(days=1)
    return sorted(dates)


def build_features(weather: pd.DataFrame, issue_date: date, run_utc: datetime) -> pd.DataFrame:
    index = weather.index
    features = weather[HOURLY_VARIABLES].copy()
    direction = np.deg2rad(pd.to_numeric(features["wind_direction_80m"], errors="coerce"))
    features["wind_direction_sin"] = np.sin(direction)
    features["wind_direction_cos"] = np.cos(direction)
    hours = index.hour.to_numpy(dtype=float)
    doy = index.dayofyear.to_numpy(dtype=float)
    features["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    features["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    features["day_of_year_sin"] = np.sin(2 * np.pi * doy / 365.25)
    features["day_of_year_cos"] = np.cos(2 * np.pi * doy / 365.25)

    issue_local = datetime.combine(issue_date, datetime.min.time()).replace(tzinfo=LOCAL_TZ)
    valid_local = [stamp.to_pydatetime().replace(tzinfo=LOCAL_TZ) for stamp in index]
    features["lead_hours"] = [(stamp - issue_local).total_seconds() / 3600 for stamp in valid_local]
    run_utc = run_utc.astimezone(timezone.utc)
    features["run_lead_hours"] = [
        (stamp.astimezone(timezone.utc) - run_utc).total_seconds() / 3600
        for stamp in valid_local
    ]
    return features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)


def hash_training_data(data: pd.DataFrame) -> str:
    view = data[["time", "turbine", *FEATURE_COLUMNS, "wind_observed", "power"]].sort_values(
        ["time", "turbine"]
    )
    digest = hashlib.sha256(pd.util.hash_pandas_object(view, index=False).values.tobytes()).hexdigest()
    return digest[:20]


def training_records(
    archive: dict[date, IssueForecast],
    history: dict[str, pd.DataFrame],
    issue_cutoff: datetime,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    cutoff = pd.Timestamp(issue_cutoff.replace(tzinfo=None))
    for issue_day, issued in sorted(archive.items()):
        features = build_features(issued.weather, issue_day, issued.run_utc)
        for turbine, hourly in history.items():
            joined = features.join(hourly[["power", "wind_observed", "source_samples"]], how="inner")
            joined = joined.loc[(joined.index < cutoff) & joined["power"].notna()].copy()
            if joined.empty:
                continue
            joined["time"] = joined.index
            joined["turbine"] = turbine
            rows.append(joined.reset_index(drop=True))
    if not rows:
        raise AgentError(f"No training rows were available before {issue_cutoff}")
    data = pd.concat(rows, ignore_index=True)
    data = data.dropna(subset=["power", "wind_speed_80m"])
    if len(data) < 800:
        raise AgentError(f"Only {len(data)} paired training hours are available")
    return data


class TurbinePowerModel:
    def __init__(self, turbine: str):
        self.turbine = turbine
        self.model = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.06,
            max_iter=220,
            max_leaf_nodes=15,
            min_samples_leaf=45,
            l2_regularization=3.0,
            early_stopping=False,
            random_state=23,
        )
        self.fill_values: np.ndarray | None = None
        self.train_rows = 0

    def fit(self, frame: pd.DataFrame) -> None:
        own = frame[frame["turbine"] == self.turbine]
        if len(own) < 300:
            raise AgentError(f"Too few training rows for {self.turbine}: {len(own)}")
        x = own[POWER_FEATURE_COLUMNS].to_numpy(dtype=float)
        self.fill_values = np.nanmedian(x, axis=0)
        self.fill_values = np.where(np.isfinite(self.fill_values), self.fill_values, 0.0)
        x = np.where(np.isfinite(x), x, self.fill_values)
        y = own["power"].to_numpy(dtype=float)
        self.model.fit(x, np.clip(y, 0, 1))
        self.train_rows = len(own)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if self.fill_values is None:
            raise AgentError(f"{self.turbine} model has not been trained")
        x = features[POWER_FEATURE_COLUMNS].to_numpy(dtype=float)
        x = np.where(np.isfinite(x), x, self.fill_values)
        return np.clip(self.model.predict(x), 0.0, 1.0)


class TurbineWindModel:
    """Calibrate forecast winds to each turbine's historical wind sensor."""

    def __init__(self, turbine: str):
        self.turbine = turbine
        self.model = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.06,
            max_iter=180,
            max_leaf_nodes=15,
            min_samples_leaf=45,
            l2_regularization=3.0,
            early_stopping=False,
            random_state=23,
        )
        self.fill_values: np.ndarray | None = None
        self.train_rows = 0

    def fit(self, frame: pd.DataFrame) -> None:
        own = frame[frame["turbine"] == self.turbine].dropna(subset=["wind_observed"])
        if len(own) < 300:
            raise AgentError(f"Too few wind calibration rows for {self.turbine}: {len(own)}")
        x = own[FEATURE_COLUMNS].to_numpy(dtype=float)
        self.fill_values = np.nanmedian(x, axis=0)
        self.fill_values = np.where(np.isfinite(self.fill_values), self.fill_values, 0.0)
        x = np.where(np.isfinite(x), x, self.fill_values)
        y = np.maximum(own["wind_observed"].to_numpy(dtype=float), 0.0)
        self.model.fit(x, y)
        self.train_rows = len(own)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if self.fill_values is None:
            raise AgentError(f"{self.turbine} wind calibration model has not been trained")
        x = features[FEATURE_COLUMNS].to_numpy(dtype=float)
        x = np.where(np.isfinite(x), x, self.fill_values)
        return np.clip(self.model.predict(x), 0.0, 35.0)


class ForecastAgent:
    """Orchestrate archive retrieval, training, forecasting, and autonomous QA."""

    def __init__(self, refresh_weather: bool = False):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.journal = EventJournal(OUTPUT_DIR / "agent_events.jsonl")
        self.weather_tool = WeatherArchiveTool(self.journal, refresh=refresh_weather)
        self.model_hash: str | None = None
        self.models: dict[str, TurbinePowerModel] = {}
        self.wind_models: dict[str, TurbineWindModel] = {}

    def fetch_training_archive(self, issue_days: list[date]) -> dict[date, IssueForecast]:
        result: dict[date, IssueForecast] = {}

        def fetch(issue_day: date) -> tuple[date, IssueForecast | None, str | None]:
            try:
                return issue_day, self.weather_tool.issue_forecast(issue_day, "training"), None
            except Exception as exc:
                return issue_day, None, str(exc)

        total = len(issue_days)
        self.journal.write("training", "weather_archive_agent", "started", issue_dates=total)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch, day): day for day in issue_days}
            finished = 0
            for future in concurrent.futures.as_completed(futures):
                day, forecast, error = future.result()
                finished += 1
                if forecast is not None:
                    result[day] = forecast
                else:
                    self.journal.write(day, "weather_archive_agent", "skipped", error=error)
                if finished % 30 == 0 or finished == total:
                    logging.info("Archived training cycles: %s/%s", finished, total)
        if len(result) < int(total * 0.85):
            raise AgentError(
                f"Only {len(result)} of {total} historical training weather cycles were retrieved"
            )
        self.journal.write(
            "training",
            "weather_archive_agent",
            "complete",
            requested_cycles=total,
            retrieved_cycles=len(result),
        )
        return result

    def fit_if_changed(self, data: pd.DataFrame) -> tuple[str, bool]:
        current_hash = hash_training_data(data)
        if current_hash == self.model_hash:
            return current_hash, False
        models: dict[str, TurbinePowerModel] = {}
        wind_models: dict[str, TurbineWindModel] = {}
        prepared = data.copy()
        prepared["wind_speed_site_estimate"] = np.nan
        for turbine in COORDINATES:
            wind_model = TurbineWindModel(turbine)
            wind_model.fit(data)
            own_mask = prepared["turbine"] == turbine
            prepared.loc[own_mask, "wind_speed_site_estimate"] = wind_model.predict(
                prepared.loc[own_mask]
            )
            wind_models[turbine] = wind_model
        for turbine in COORDINATES:
            model = TurbinePowerModel(turbine)
            model.fit(prepared)
            models[turbine] = model
        self.models = models
        self.wind_models = wind_models
        self.model_hash = current_hash
        return current_hash, True

    def forecast_cycle(
        self,
        issue_day: date,
        archive: dict[date, IssueForecast],
        history: dict[str, pd.DataFrame],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        self.journal.write(issue_day, "cycle_agent", "started", issue_time_local=f"{issue_day} 00:00")
        issued = self.weather_tool.issue_forecast(issue_day, "replay")
        cutoff = datetime.combine(issue_day, datetime.min.time())
        train = training_records(archive, history, cutoff)
        model_hash, retrained = self.fit_if_changed(train)
        self.journal.write(
            issue_day,
            "model_agent",
            "trained" if retrained else "reused",
            model_hash=model_hash,
            training_rows={k: self.models[k].train_rows for k in self.models},
            wind_calibration_rows={k: self.wind_models[k].train_rows for k in self.wind_models},
            latest_training_timestamp=str(train["time"].max()),
            training_cutoff_local=cutoff.isoformat(),
        )

        features = build_features(issued.weather, issue_day, issued.run_utc)
        output = pd.DataFrame(index=features.index)
        output.index.name = "forecast_timestamp_local"
        for turbine, model in self.models.items():
            site_wind = self.wind_models[turbine].predict(features)
            power_features = features.copy()
            power_features["wind_speed_site_estimate"] = site_wind
            output[f"{turbine}_estimated_site_wind_mps"] = site_wind
            output[f"{turbine}_normalized_power"] = model.predict(power_features)
        output["farm_average_normalized_power"] = output[
            [f"{name}_normalized_power" for name in COORDINATES]
        ].mean(axis=1)
        output["forecast_wind_10m_mps"] = issued.weather["wind_speed_10m"]
        output["forecast_wind_80m_mps"] = issued.weather["wind_speed_80m"]
        output["forecast_wind_100m_mps"] = issued.weather["wind_speed_100m"]
        output["forecast_wind_direction_80m_deg"] = issued.weather["wind_direction_80m"]
        output["forecast_temperature_2m_c"] = issued.weather["temperature_2m"]
        output["forecast_gust_10m_mps"] = issued.weather["wind_gusts_10m"]
        output["issue_date"] = str(issue_day)
        output["target_date"] = str(issued.target_date)
        output["issue_time_local"] = f"{issue_day} 00:00"
        output["weather_run_utc"] = issued.run_utc.strftime("%Y-%m-%d %H:%M")
        output["lead_hours_from_issue"] = features["lead_hours"].to_numpy()
        output["lead_hours_from_weather_run"] = features["run_lead_hours"].to_numpy()
        output["weather_model"] = "ECMWF IFS HRES 9 km"
        output["weather_fallback_used"] = issued.fallback_used

        issues: list[str] = []
        if len(output) != 24:
            issues.append(f"Expected 24 forecast hours, found {len(output)}")
        prediction_columns = [f"{name}_normalized_power" for name in COORDINATES]
        if output[prediction_columns].isna().any().any():
            issues.append("Forecast contains missing normalized power values")
        if ((output[prediction_columns] < 0) | (output[prediction_columns] > 1)).any().any():
            issues.append("Forecast exceeds normalized power bounds [0, 1]")
        if output[prediction_columns].nunique().max() < 4:
            issues.append("Forecast is nearly constant for both turbines")
        if issues:
            self.journal.write(issue_day, "analysis_agent", "warning", findings=issues)
            raise AgentError(f"Forecast QA failed on {issue_day}: {'; '.join(issues)}")
        self.journal.write(
            issue_day,
            "analysis_agent",
            "accepted",
            forecast_hours=len(output),
            prediction_range={
                col: [round(float(output[col].min()), 4), round(float(output[col].max()), 4)]
                for col in prediction_columns
            },
            weather_fallback_used=issued.fallback_used,
        )
        return output.reset_index(), {
            "issue_date": str(issue_day),
            "target_date": str(issued.target_date),
            "weather_run_utc": issued.run_utc.strftime("%Y-%m-%d %H:%M"),
            "weather_fallback_used": issued.fallback_used,
            "training_rows_turbine_1": self.models["turbine_1"].train_rows,
            "training_rows_turbine_2": self.models["turbine_2"].train_rows,
            "training_data_hash": model_hash,
            "forecast_hours": len(output),
            "forecast_power_t1_mean": float(output["turbine_1_normalized_power"].mean()),
            "forecast_power_t2_mean": float(output["turbine_2_normalized_power"].mean()),
            "forecast_power_farm_mean": float(output["farm_average_normalized_power"].mean()),
        }

    def run_replay(
        self,
        issue_days: list[date],
        archive: dict[date, IssueForecast],
        history: dict[str, pd.DataFrame],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        all_forecasts: list[pd.DataFrame] = []
        cycle_summaries: list[dict[str, Any]] = []
        for issue_day in issue_days:
            try:
                forecast, summary = self.forecast_cycle(issue_day, archive, history)
            except Exception as exc:
                self.journal.write(issue_day, "cycle_agent", "failed", error=str(exc))
                raise
            all_forecasts.append(forecast)
            cycle_summaries.append(summary)
            logging.info(
                "Issue %s -> %s: 24 hours, IFS run %s UTC",
                summary["issue_date"],
                summary["target_date"],
                summary["weather_run_utc"],
            )
        return pd.concat(all_forecasts, ignore_index=True), pd.DataFrame(cycle_summaries)


def holdout_validation(
    agent: ForecastAgent,
    archive: dict[date, IssueForecast],
    history: dict[str, pd.DataFrame],
    first_target_day: date,
    last_target_day: date,
) -> pd.DataFrame:
    """Verify January 2026 with one frozen model trained only through December."""
    predictions: list[pd.DataFrame] = []
    original_hash = agent.model_hash
    original_models = agent.models
    original_wind_models = agent.wind_models
    issue_day = first_target_day - timedelta(days=1)
    final_issue = last_target_day - timedelta(days=1)
    if issue_day not in archive:
        raise AgentError(f"Missing validation weather cycle for issue date {issue_day}")
    cutoff = datetime.combine(first_target_day, datetime.min.time())
    train = training_records(archive, history, cutoff)
    agent.fit_if_changed(train)
    while issue_day <= final_issue:
        if issue_day not in archive:
            raise AgentError(f"Missing validation weather cycle for issue date {issue_day}")
        issued = archive[issue_day]
        features = build_features(issued.weather, issue_day, issued.run_utc)
        day_frame = pd.DataFrame(index=features.index)
        day_frame.index.name = "time"
        for turbine, model in agent.models.items():
            site_wind = agent.wind_models[turbine].predict(features)
            power_features = features.copy()
            power_features["wind_speed_site_estimate"] = site_wind
            day_frame[f"{turbine}_prediction"] = model.predict(power_features)
            actual = history[turbine]["power"].reindex(features.index)
            day_frame[f"{turbine}_actual"] = actual
        day_frame["issue_date"] = str(issue_day)
        predictions.append(day_frame.reset_index())
        issue_day += timedelta(days=1)

    agent.model_hash = original_hash
    agent.models = original_models
    agent.wind_models = original_wind_models
    joined = pd.concat(predictions, ignore_index=True)
    summaries: list[dict[str, Any]] = []
    baseline_predictions: dict[str, np.ndarray] = {}
    validation_times = pd.DatetimeIndex(joined["time"])
    training_cutoff = pd.Timestamp(first_target_day)
    for turbine in COORDINATES:
        train_power = history[turbine].loc[
            history[turbine].index < training_cutoff, "power"
        ].dropna()
        hour_means = train_power.groupby(train_power.index.hour).mean()
        baseline_predictions[turbine] = np.array(
            [float(hour_means.get(stamp.hour, train_power.mean())) for stamp in validation_times]
        )
        actual = joined[f"{turbine}_actual"].to_numpy(dtype=float)
        predicted = joined[f"{turbine}_prediction"].to_numpy(dtype=float)
        valid = np.isfinite(actual) & np.isfinite(predicted)
        error = predicted[valid] - actual[valid]
        baseline_valid = np.isfinite(actual) & np.isfinite(baseline_predictions[turbine])
        baseline_error = baseline_predictions[turbine][baseline_valid] - actual[baseline_valid]
        baseline_mae = float(np.mean(np.abs(baseline_error)))
        model_mae = float(np.mean(np.abs(error)))
        summaries.append(
            {
                "series": turbine,
                "validation_period": f"{first_target_day} to {last_target_day}",
                "hours": int(valid.sum()),
                "mae_normalized_power": model_mae,
                "rmse_normalized_power": float(np.sqrt(np.mean(error**2))),
                "bias_normalized_power": float(np.mean(error)),
                "hourly_climatology_mae_normalized_power": baseline_mae,
                "mae_skill_vs_hourly_climatology": float(1 - model_mae / baseline_mae),
                "mean_actual_normalized_power": float(np.mean(actual[valid])),
                "mean_predicted_normalized_power": float(np.mean(predicted[valid])),
            }
        )
    actual_farm = joined[[f"{name}_actual" for name in COORDINATES]].mean(axis=1, skipna=False).to_numpy(dtype=float)
    predicted_farm = joined[[f"{name}_prediction" for name in COORDINATES]].mean(axis=1, skipna=False).to_numpy(dtype=float)
    baseline_farm = np.mean(np.vstack(list(baseline_predictions.values())), axis=0)
    valid = np.isfinite(actual_farm) & np.isfinite(predicted_farm)
    error = predicted_farm[valid] - actual_farm[valid]
    baseline_valid = np.isfinite(actual_farm) & np.isfinite(baseline_farm)
    baseline_error = baseline_farm[baseline_valid] - actual_farm[baseline_valid]
    baseline_mae = float(np.mean(np.abs(baseline_error)))
    model_mae = float(np.mean(np.abs(error)))
    summaries.append(
        {
            "series": "farm_equal_capacity_average",
            "validation_period": f"{first_target_day} to {last_target_day}",
            "hours": int(valid.sum()),
            "mae_normalized_power": model_mae,
            "rmse_normalized_power": float(np.sqrt(np.mean(error**2))),
            "bias_normalized_power": float(np.mean(error)),
            "hourly_climatology_mae_normalized_power": baseline_mae,
            "mae_skill_vs_hourly_climatology": float(1 - model_mae / baseline_mae),
            "mean_actual_normalized_power": float(np.mean(actual_farm[valid])),
            "mean_predicted_normalized_power": float(np.mean(predicted_farm[valid])),
        }
    )
    return pd.DataFrame(summaries)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Use YYYY-MM-DD: {text}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run daily 24-hour archived-weather forecasts for the HackAlemAI wind case."
    )
    parser.add_argument("--start-issue-date", type=parse_day, default=date(2026, 1, 31))
    parser.add_argument("--end-issue-date", type=parse_day, default=date(2026, 2, 27))
    parser.add_argument("--refresh-weather", action="store_true", help="Re-fetch cached ECMWF runs")
    parser.add_argument("--skip-validation", action="store_true", help="Skip the January frozen-model holdout")
    args = parser.parse_args()
    if args.end_issue_date < args.start_issue_date:
        parser.error("--end-issue-date must be on or after --start-issue-date")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "agent_events.jsonl").write_text("", encoding="utf-8")
    agent = ForecastAgent(refresh_weather=args.refresh_weather)
    agent.journal.write("setup", "input_agent", "started")
    history = read_operational_history()
    source_ends = {name: str(frame.index.max()) for name, frame in history.items()}
    agent.journal.write(
        "setup",
        "input_agent",
        "loaded",
        hourly_rows={name: len(frame) for name, frame in history.items()},
        latest_hour_by_turbine=source_ends,
        filtering_rule="training labels are cut off at each issue time; hourly labels require >=3 ten-minute records",
    )

    archive_days = set(issue_dates_for_training())
    if not args.skip_validation:
        val_issue = date(2025, 12, 31)
        while val_issue <= date(2026, 1, 30):
            archive_days.add(val_issue)
            val_issue += timedelta(days=1)
    # Training archive windows and requested replay windows share the same API cache.
    issue = args.start_issue_date
    replay_days: list[date] = []
    while issue <= args.end_issue_date:
        replay_days.append(issue)
        issue += timedelta(days=1)
    training_archives = agent.fetch_training_archive(sorted(archive_days))

    if not args.skip_validation:
        agent.journal.write("validation", "analysis_agent", "started", first_target="2026-01-01", last_target="2026-01-31")
        validation = holdout_validation(
            agent,
            training_archives,
            history,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        validation.to_csv(OUTPUT_DIR / "validation_metrics_january_2026.csv", index=False, float_format="%.6f")
        agent.journal.write(
            "validation",
            "analysis_agent",
            "complete",
            metrics=validation.to_dict(orient="records"),
            note="January holdout trained through December 31; no January or February labels are used to fit this validation model.",
        )

    forecasts, cycle_summaries = agent.run_replay(replay_days, training_archives, history)
    expected_target_start = args.start_issue_date + timedelta(days=1)
    expected_target_end = args.end_issue_date + timedelta(days=1)
    predictions_path = OUTPUT_DIR / f"forecast_{expected_target_start:%Y_%m_%d}_to_{expected_target_end:%Y_%m_%d}.csv"
    forecasts.to_csv(predictions_path, index=False, float_format="%.6f")
    cycle_summaries.to_csv(OUTPUT_DIR / "daily_cycle_summary.csv", index=False, float_format="%.6f")

    manifest = {
        "case": "HackAlemAI Agentic AI for Wind Farm Generation Forecasting",
        "timezone": TIMEZONE,
        "weather_source": "Open-Meteo Single Runs API",
        "weather_model": "ECMWF IFS HRES 9 km (ecmwf_ifs)",
        "coordinates": COORDINATES,
        "weather_grid_point": WEATHER_POINT,
        "issue_date_range": [str(args.start_issue_date), str(args.end_issue_date)],
        "target_date_range": [str(expected_target_start), str(expected_target_end)],
        "issue_time_local": "00:00",
        "forecast_hours_per_issue": 24,
        "lead_hours_from_issue": [24, 47],
        "aggregation": "Mean of each turbine's normalized active power; farm average assumes equal turbine ratings",
        "training_weather_issue_days": len(training_archives),
        "historical_power_ends": source_ends,
        "forecast_rows": len(forecasts),
        "prediction_file": str(predictions_path.relative_to(ROOT)),
        "validation_file": None if args.skip_validation else "outputs/validation_metrics_january_2026.csv",
        "label_cutoff_rule": "Only power observations earlier than the issue timestamp are used in each cycle.",
        "availability_assumption": "The previous day's 12Z IFS run is expected online by the 19Z issue time; 06Z and 00Z are fallback runs.",
    }
    save_json(OUTPUT_DIR / "run_manifest.json", manifest)
    agent.journal.write("run", "cycle_agent", "complete", manifest=manifest)
    print(f"Forecast: {predictions_path}")
    print(f"Cycles: {OUTPUT_DIR / 'daily_cycle_summary.csv'}")
    if not args.skip_validation:
        print(f"Validation: {OUTPUT_DIR / 'validation_metrics_january_2026.csv'}")
    print(f"Agent trace: {OUTPUT_DIR / 'agent_events.jsonl'}")


if __name__ == "__main__":
    main()
