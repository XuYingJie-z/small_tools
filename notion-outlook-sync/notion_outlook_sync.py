#!/usr/bin/env python3
"""One-way synchronization: multiple Notion data sources -> Outlook Calendar.

The script reads dated pages from configured Notion data sources and mirrors them
as events in an Outlook calendar through Microsoft Graph. A local SQLite database
stores the Notion page ID -> Outlook event ID mapping.

Python 3.11+
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import msal
import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv

NOTION_BASE_URL = "https://api.notion.com"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_NOTION_API_VERSION = "2026-03-11"
DEFAULT_SCOPES = ["User.Read", "Calendars.ReadWrite"]

LOG = logging.getLogger("notion_outlook_sync")


class SyncError(RuntimeError):
    """Base error for the synchronizer."""


class ApiError(SyncError):
    """HTTP/API error with response details."""

    def __init__(self, service: str, status_code: int, message: str):
        super().__init__(f"{service} API {status_code}: {message}")
        self.service = service
        self.status_code = status_code
        self.message = message


class GraphNotFound(ApiError):
    """The mapped Outlook event no longer exists."""


class NotionClient:
    def __init__(self, token: str, api_version: str, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": api_version,
                "Content-Type": "application/json",
            }
        )

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{NOTION_BASE_URL}{path}"
        for attempt in range(1, 6):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt == 5:
                    raise SyncError(f"Notion request failed: {exc}") from exc
                time.sleep(min(2 ** (attempt - 1), 16))
                continue

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == 5:
                    raise ApiError("Notion", response.status_code, _response_message(response))
                retry_after = _retry_after_seconds(response, attempt)
                LOG.warning(
                    "Notion temporarily unavailable (%s); retrying in %.1fs",
                    response.status_code,
                    retry_after,
                )
                time.sleep(retry_after)
                continue

            if not response.ok:
                raise ApiError("Notion", response.status_code, _response_message(response))

            return response.json()

        raise AssertionError("unreachable")

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/data_sources/{quote(data_source_id, safe='')}",
        )

    def query_data_source(self, data_source_id: str) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request(
                "POST",
                f"/v1/data_sources/{quote(data_source_id, safe='')}/query",
                json_body=body,
            )
            for result in payload.get("results", []):
                if result.get("object") == "page":
                    yield result
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break


class GraphClient:
    def __init__(self, access_token: str, calendar_id: str | None, timeout: int = 30):
        self.calendar_id = calendar_id.strip() if calendar_id else None
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{GRAPH_BASE_URL}{path}"
        for attempt in range(1, 6):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt == 5:
                    raise SyncError(f"Microsoft Graph request failed: {exc}") from exc
                time.sleep(min(2 ** (attempt - 1), 16))
                continue

            if response.status_code in (404, 410) and allow_not_found:
                raise GraphNotFound(
                    "Microsoft Graph", response.status_code, _response_message(response)
                )

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == 5:
                    raise ApiError(
                        "Microsoft Graph", response.status_code, _response_message(response)
                    )
                retry_after = _retry_after_seconds(response, attempt)
                LOG.warning(
                    "Microsoft Graph temporarily unavailable (%s); retrying in %.1fs",
                    response.status_code,
                    retry_after,
                )
                time.sleep(retry_after)
                continue

            if not response.ok:
                raise ApiError("Microsoft Graph", response.status_code, _response_message(response))

            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        raise AssertionError("unreachable")

    def create_event(self, event_payload: dict[str, Any]) -> str:
        payload = dict(event_payload)
        # Keep one transaction ID for all HTTP retries in this create call. A new
        # create call gets a new ID, so an intentionally recreated event is allowed.
        payload["transactionId"] = str(uuid.uuid4())
        if self.calendar_id:
            path = f"/me/calendars/{quote(self.calendar_id, safe='')}/events"
        else:
            path = "/me/events"
        result = self._request("POST", path, json_body=payload)
        if not result or not result.get("id"):
            raise SyncError("Microsoft Graph created an event but did not return an event ID")
        return str(result["id"])

    def update_event(self, event_id: str, event_payload: dict[str, Any]) -> None:
        self._request(
            "PATCH",
            f"/me/events/{quote(event_id, safe='')}",
            json_body=event_payload,
            allow_not_found=True,
        )

    def delete_event(self, event_id: str) -> None:
        try:
            self._request(
                "DELETE",
                f"/me/events/{quote(event_id, safe='')}",
                allow_not_found=True,
            )
        except GraphNotFound:
            LOG.info("Outlook event already absent: %s", event_id)


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mappings (
                notion_page_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                outlook_event_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                last_seen_run TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mappings_source ON mappings(source_id)"
        )
        self.connection.commit()

    def get(self, notion_page_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM mappings WHERE notion_page_id = ?", (notion_page_id,)
        ).fetchone()

    def upsert(
        self,
        *,
        notion_page_id: str,
        source_id: str,
        source_name: str,
        outlook_event_id: str,
        content_hash: str,
        run_id: str,
    ) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO mappings (
                notion_page_id, source_id, source_name, outlook_event_id,
                content_hash, last_seen_run, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(notion_page_id) DO UPDATE SET
                source_id = excluded.source_id,
                source_name = excluded.source_name,
                outlook_event_id = excluded.outlook_event_id,
                content_hash = excluded.content_hash,
                last_seen_run = excluded.last_seen_run,
                updated_at = excluded.updated_at
            """,
            (
                notion_page_id,
                source_id,
                source_name,
                outlook_event_id,
                content_hash,
                run_id,
                now,
            ),
        )
        self.connection.commit()

    def touch(self, notion_page_id: str, run_id: str) -> None:
        self.connection.execute(
            "UPDATE mappings SET last_seen_run = ? WHERE notion_page_id = ?",
            (run_id, notion_page_id),
        )
        self.connection.commit()

    def delete(self, notion_page_id: str) -> None:
        self.connection.execute("DELETE FROM mappings WHERE notion_page_id = ?", (notion_page_id,))
        self.connection.commit()

    def all_for_source(self, source_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM mappings WHERE source_id = ?", (source_id,)
        ).fetchall()

    def close(self) -> None:
        self.connection.close()


class Synchronizer:
    def __init__(
        self,
        *,
        notion: NotionClient,
        graph: GraphClient | None,
        state: StateStore,
        config: dict[str, Any],
        default_timezone: ZoneInfo,
        delete_missing: bool,
        dry_run: bool,
    ):
        self.notion = notion
        self.graph = graph
        self.state = state
        self.config = config
        self.default_timezone = default_timezone
        self.delete_missing = delete_missing
        self.dry_run = dry_run
        self.default_duration_minutes = int(config.get("default_event_duration_minutes", 60))
        self.all_day_end_inclusive = bool(config.get("notion_all_day_end_is_inclusive", True))
        self.stats = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
        }

    def run(self, selected_sources: set[str] | None = None) -> int:
        sources = self.config.get("sources")
        if not isinstance(sources, list) or not sources:
            raise SyncError(".config.json must contain a non-empty 'sources' list")

        for source in sources:
            _validate_source(source)
        configured_names = {str(source["name"]) for source in sources}
        if selected_sources:
            unknown = selected_sources - configured_names
            if unknown:
                raise SyncError(f"Unknown --source names: {', '.join(sorted(unknown))}")

        failures = 0
        for source in sources:
            source_name = str(source["name"])
            if selected_sources and source_name not in selected_sources:
                continue
            try:
                self._sync_source(source)
            except Exception:
                failures += 1
                self.stats["errors"] += 1
                LOG.exception("Source failed: %s", source_name)

        LOG.info(
            "Summary: created=%d updated=%d deleted=%d unchanged=%d skipped=%d errors=%d",
            self.stats["created"],
            self.stats["updated"],
            self.stats["deleted"],
            self.stats["unchanged"],
            self.stats["skipped"],
            self.stats["errors"],
        )
        return 1 if failures else 0

    def _sync_source(self, source: dict[str, Any]) -> None:
        source_id = str(source["data_source_id"])
        source_name = str(source["name"])
        run_id = uuid.uuid4().hex
        LOG.info("Syncing source: %s", source_name)
        schema = self.notion.retrieve_data_source(source_id)
        _validate_source_properties(source, schema)

        page_count = 0
        seen_page_ids: set[str] = set()
        for page in self.notion.query_data_source(source_id):
            page_count += 1
            seen_page_ids.add(str(page["id"]))
            self._sync_page(source, page, run_id)

        if self.delete_missing:
            for mapping in self.state.all_for_source(source_id):
                if str(mapping["notion_page_id"]) not in seen_page_ids:
                    self._delete_mapping(
                        mapping,
                        reason="Notion page was deleted/trashed or is no longer returned by the data source",
                    )

        LOG.info("Source complete: %s (%d pages read)", source_name, page_count)

    def _sync_page(self, source: dict[str, Any], page: dict[str, Any], run_id: str) -> None:
        page_id = str(page["id"])
        mapping = self.state.get(page_id)
        title = _property_text(page, str(source["title_property"])) or "Untitled"
        label = f"{source['name']} / {title}"

        inactive_reason = _inactive_reason(source, page)
        if inactive_reason:
            if mapping:
                self._delete_mapping(mapping, reason=inactive_reason)
            else:
                LOG.debug("Skipping %s: %s", label, inactive_reason)
                self.stats["skipped"] += 1
            return

        notion_date = _property_date(page, str(source["date_property"]))
        if not notion_date or not notion_date.get("start"):
            if mapping:
                self._delete_mapping(mapping, reason="date property is empty")
            else:
                LOG.debug("Skipping %s: date property is empty", label)
                self.stats["skipped"] += 1
            return

        payload = self._build_event_payload(source, page, notion_date)
        content_hash = _stable_hash(payload)

        if not mapping:
            if self.dry_run:
                LOG.info("[DRY RUN] CREATE %s", label)
                self.stats["created"] += 1
                return
            assert self.graph is not None
            event_id = self.graph.create_event(payload)
            self.state.upsert(
                notion_page_id=page_id,
                source_id=str(source["data_source_id"]),
                source_name=str(source["name"]),
                outlook_event_id=event_id,
                content_hash=content_hash,
                run_id=run_id,
            )
            LOG.info("CREATE %s", label)
            self.stats["created"] += 1
            return

        if mapping["content_hash"] == content_hash:
            if not self.dry_run:
                self.state.touch(page_id, run_id)
            LOG.debug("UNCHANGED %s", label)
            self.stats["unchanged"] += 1
            return

        if self.dry_run:
            LOG.info("[DRY RUN] UPDATE %s", label)
            self.stats["updated"] += 1
            return

        assert self.graph is not None
        event_id = str(mapping["outlook_event_id"])
        try:
            self.graph.update_event(event_id, payload)
        except GraphNotFound:
            LOG.warning("Mapped Outlook event is missing; recreating: %s", label)
            event_id = self.graph.create_event(payload)

        self.state.upsert(
            notion_page_id=page_id,
            source_id=str(source["data_source_id"]),
            source_name=str(source["name"]),
            outlook_event_id=event_id,
            content_hash=content_hash,
            run_id=run_id,
        )
        LOG.info("UPDATE %s", label)
        self.stats["updated"] += 1

    def _delete_mapping(self, mapping: sqlite3.Row, reason: str) -> None:
        label = f"{mapping['source_name']} / {mapping['notion_page_id']}"
        if self.dry_run:
            LOG.info("[DRY RUN] DELETE %s (%s)", label, reason)
            self.stats["deleted"] += 1
            return
        assert self.graph is not None
        self.graph.delete_event(str(mapping["outlook_event_id"]))
        self.state.delete(str(mapping["notion_page_id"]))
        LOG.info("DELETE %s (%s)", label, reason)
        self.stats["deleted"] += 1

    def _build_event_payload(
        self,
        source: dict[str, Any],
        page: dict[str, Any],
        notion_date: dict[str, Any],
    ) -> dict[str, Any]:
        raw_title = _property_text(page, str(source["title_property"])) or "Untitled"
        subject = f"{source.get('title_prefix', '')}{raw_title}"
        start, end, all_day = _outlook_times(
            notion_date,
            self.default_timezone,
            self.default_duration_minutes,
            self.all_day_end_inclusive,
        )

        description = ""
        description_property = source.get("description_property")
        if description_property:
            description = _property_text(page, str(description_property))

        notion_url = str(page.get("url") or "")
        body_parts = [f"<p><strong>Notion 来源：</strong>{html.escape(str(source['name']))}</p>"]
        if description:
            body_parts.append(f"<p>{html.escape(description).replace(chr(10), '<br>')}</p>")
        if notion_url:
            escaped_url = html.escape(notion_url, quote=True)
            body_parts.append(f'<p><a href="{escaped_url}">在 Notion 中打开</a></p>')

        payload: dict[str, Any] = {
            "subject": subject[:255],
            "body": {"contentType": "HTML", "content": "".join(body_parts)},
            "start": start,
            "end": end,
            "isAllDay": all_day,
            "showAs": str(source.get("show_as", "busy")),
            "sensitivity": str(source.get("sensitivity", "normal")),
        }

        location_property = source.get("location_property")
        if location_property:
            location = _property_text(page, str(location_property))
            if location:
                payload["location"] = {"displayName": location}

        categories = source.get("categories")
        if isinstance(categories, list) and categories:
            payload["categories"] = [str(item) for item in categories]

        return payload


def _inactive_reason(source: dict[str, Any], page: dict[str, Any]) -> str | None:
    condition = source.get("sync_only_when")
    if condition:
        if not isinstance(condition, dict) or not condition.get("property"):
            raise SyncError(f"Invalid sync_only_when in source {source.get('name')}")
        actual = _property_scalar(page, str(condition["property"]))
        if "equals" in condition and actual != condition["equals"]:
            return f"sync condition is not met ({actual!r} != {condition['equals']!r})"
        if "in" in condition and actual not in condition["in"]:
            return f"sync condition is not met ({actual!r} not in configured values)"

    status_property = source.get("status_property")
    cancelled_values = source.get("cancelled_values", [])
    if status_property and cancelled_values:
        status = _property_scalar(page, str(status_property))
        normalized_cancelled = {str(value).strip().casefold() for value in cancelled_values}
        if isinstance(status, str) and status.strip().casefold() in normalized_cancelled:
            return f"status is cancelled ({status})"

    if page.get("in_trash") is True or page.get("archived") is True:
        return "Notion page is in trash/archived"
    return None


def _property(page: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = page.get("properties", {}).get(name)
    return value if isinstance(value, dict) else None


def _property_text(page: dict[str, Any], name: str) -> str:
    prop = _property(page, name)
    if not prop:
        return ""
    value = _property_scalar_from_object(prop)
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _property_scalar(page: dict[str, Any], name: str) -> Any:
    prop = _property(page, name)
    return _property_scalar_from_object(prop) if prop else None


def _property_scalar_from_object(prop: dict[str, Any]) -> Any:
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(
            str(item.get("plain_text", ""))
            for item in (prop.get(prop_type) or [])
            if isinstance(item, dict)
        )
    if prop_type in ("select", "status"):
        value = prop.get(prop_type)
        return value.get("name") if isinstance(value, dict) else None
    if prop_type == "multi_select":
        return [item.get("name", "") for item in prop.get("multi_select", [])]
    if prop_type == "checkbox":
        return bool(prop.get("checkbox"))
    if prop_type in ("number", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return prop.get(prop_type)
    if prop_type == "people":
        return [item.get("name") or item.get("id", "") for item in prop.get("people", [])]
    if prop_type == "formula":
        formula = prop.get("formula") or {}
        return formula.get(formula.get("type"))
    if prop_type == "rollup":
        rollup = prop.get("rollup") or {}
        return rollup.get(rollup.get("type"))
    if prop_type == "unique_id":
        value = prop.get("unique_id") or {}
        prefix = value.get("prefix") or ""
        number = value.get("number")
        return f"{prefix}{number}" if number is not None else None
    return None


def _property_date(page: dict[str, Any], name: str) -> dict[str, Any] | None:
    prop = _property(page, name)
    if not prop:
        return None
    prop_type = prop.get("type")
    if prop_type == "date":
        value = prop.get("date")
        return value if isinstance(value, dict) else None
    if prop_type == "formula":
        formula = prop.get("formula") or {}
        if formula.get("type") == "date" and isinstance(formula.get("date"), dict):
            return formula["date"]
    if prop_type == "rollup":
        rollup = prop.get("rollup") or {}
        if rollup.get("type") == "date" and isinstance(rollup.get("date"), dict):
            return rollup["date"]
    raise SyncError(f"Property '{name}' is not a date, date formula, or date rollup")


def _outlook_times(
    notion_date: dict[str, Any],
    default_timezone: ZoneInfo,
    default_duration_minutes: int,
    all_day_end_inclusive: bool,
) -> tuple[dict[str, str], dict[str, str], bool]:
    raw_start = str(notion_date["start"])
    raw_end = notion_date.get("end")
    all_day = "T" not in raw_start

    if all_day:
        start_date = dt.date.fromisoformat(raw_start)
        if raw_end:
            end_date = dt.date.fromisoformat(str(raw_end))
            if all_day_end_inclusive:
                end_date += dt.timedelta(days=1)
        else:
            end_date = start_date + dt.timedelta(days=1)
        if end_date <= start_date:
            end_date = start_date + dt.timedelta(days=1)
        return (
            {"dateTime": f"{start_date.isoformat()}T00:00:00", "timeZone": "UTC"},
            {"dateTime": f"{end_date.isoformat()}T00:00:00", "timeZone": "UTC"},
            True,
        )

    start_dt = _parse_notion_datetime(raw_start, notion_date.get("time_zone"), default_timezone)
    if raw_end:
        end_dt = _parse_notion_datetime(
            str(raw_end), notion_date.get("time_zone"), default_timezone
        )
    else:
        end_dt = start_dt + dt.timedelta(minutes=default_duration_minutes)
    if end_dt <= start_dt:
        end_dt = start_dt + dt.timedelta(minutes=default_duration_minutes)

    start_utc = start_dt.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = end_dt.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return (
        {"dateTime": start_utc.isoformat(timespec="seconds"), "timeZone": "UTC"},
        {"dateTime": end_utc.isoformat(timespec="seconds"), "timeZone": "UTC"},
        False,
    )


def _parse_notion_datetime(
    value: str, notion_timezone: Any, default_timezone: ZoneInfo
) -> dt.datetime:
    parsed = date_parser.isoparse(value)
    if parsed.tzinfo is None:
        timezone = default_timezone
        if notion_timezone:
            try:
                timezone = ZoneInfo(str(notion_timezone))
            except ZoneInfoNotFoundError:
                LOG.warning("Unknown Notion timezone %r; using default", notion_timezone)
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(float(value), 0.5)
        except ValueError:
            pass
    return float(min(2 ** (attempt - 1), 16))


def _response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            return str(payload.get("message") or payload.get("code") or payload)
    except ValueError:
        pass
    return response.text[:1000] or response.reason


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except FileNotFoundError as exc:
        raise SyncError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SyncError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"Top-level JSON value in {path} must be an object")
    return value


def _validate_source_properties(source: dict[str, Any], schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise SyncError(
            f"Notion did not return a property schema for source {source.get('name')}. "
            "Confirm that this is a data source ID and that the original database is shared with the integration."
        )

    configured: dict[str, str] = {
        "title_property": str(source["title_property"]),
        "date_property": str(source["date_property"]),
    }
    for key in ("status_property", "description_property", "location_property"):
        if source.get(key):
            configured[key] = str(source[key])
    condition = source.get("sync_only_when")
    if isinstance(condition, dict) and condition.get("property"):
        configured["sync_only_when.property"] = str(condition["property"])

    missing = [f"{label}={name!r}" for label, name in configured.items() if name not in properties]
    if missing:
        available = ", ".join(sorted(str(name) for name in properties))
        raise SyncError(
            f"Source {source.get('name')} has unknown property names: {', '.join(missing)}. "
            f"Available properties: {available}"
        )

    date_schema = properties.get(str(source["date_property"]), {})
    date_type = date_schema.get("type") if isinstance(date_schema, dict) else None
    if date_type not in {"date", "formula", "rollup"}:
        raise SyncError(
            f"Source {source.get('name')} date_property {source['date_property']!r} "
            f"has unsupported schema type {date_type!r}"
        )


def _validate_source(source: Any) -> None:
    if not isinstance(source, dict):
        raise SyncError("Each source entry must be a JSON object")
    required = ("name", "data_source_id", "title_property", "date_property")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise SyncError(f"Source is missing required fields: {', '.join(missing)}")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SyncError(f"Missing required environment variable: {name}")
    return value


def _load_token_cache(path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if path.exists():
        try:
            cache.deserialize(path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOG.warning("Could not read MSAL token cache %s: %s", path, exc)
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    if not cache.has_state_changed:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cache.serialize(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def acquire_graph_token(client_id: str, authority: str, cache_path: Path) -> str:
    cache = _load_token_cache(cache_path)
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    result: dict[str, Any] | None = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(DEFAULT_SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=DEFAULT_SCOPES)
        if "user_code" not in flow:
            raise SyncError(f"Could not start Microsoft device-code login: {flow}")
        print(
            flow.get("message")
            or f"Open {flow.get('verification_uri')} and enter {flow.get('user_code')}"
        )
        result = app.acquire_token_by_device_flow(flow)

    _save_token_cache(cache, cache_path)

    if not result or "access_token" not in result:
        error = result or {}
        raise SyncError(
            "Microsoft sign-in failed: "
            f"{error.get('error_description') or error.get('error') or error}"
        )
    return str(result["access_token"])


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize multiple Notion data sources to an Outlook calendar."
    )
    parser.add_argument(
        "--config",
        default=os.getenv("SYNC_CONFIG", ".config.json"),
        help="Path to config JSON (default: .config.json or SYNC_CONFIG)",
    )
    parser.add_argument(
        "--source",
        action="append",
        help="Only sync this source name; may be supplied multiple times",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show actions without changing Outlook or SQLite"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    load_dotenv()
    args = build_argument_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG
        if args.verbose
        else getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    notion_token = _require_env("NOTION_TOKEN")
    notion_version = os.getenv("NOTION_API_VERSION", DEFAULT_NOTION_API_VERSION).strip()
    default_timezone_name = os.getenv("DEFAULT_TIMEZONE", "Asia/Shanghai").strip()
    try:
        default_timezone = ZoneInfo(default_timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise SyncError(f"Unknown DEFAULT_TIMEZONE: {default_timezone_name}") from exc

    config_path = Path(args.config).expanduser().resolve()
    config = _load_json(config_path)

    state_path = Path(os.getenv("STATE_DB", "sync_state.sqlite3")).expanduser().resolve()
    token_cache_path = (
        Path(os.getenv("TOKEN_CACHE", "msal_token_cache.json")).expanduser().resolve()
    )
    dry_run = args.dry_run or _env_bool("DRY_RUN", False)
    delete_missing = _env_bool("DELETE_MISSING_EVENTS", False)

    notion = NotionClient(notion_token, notion_version)
    graph: GraphClient | None = None
    if not dry_run:
        microsoft_client_id = _require_env("MICROSOFT_CLIENT_ID")
        authority = os.getenv(
            "MICROSOFT_AUTHORITY", "https://login.microsoftonline.com/common"
        ).strip()
        access_token = acquire_graph_token(microsoft_client_id, authority, token_cache_path)
        graph = GraphClient(access_token, os.getenv("OUTLOOK_CALENDAR_ID"))
    else:
        LOG.warning("DRY RUN: Outlook and SQLite will not be changed")

    state = StateStore(state_path)
    try:
        synchronizer = Synchronizer(
            notion=notion,
            graph=graph,
            state=state,
            config=config,
            default_timezone=default_timezone,
            delete_missing=delete_missing,
            dry_run=dry_run,
        )
        return synchronizer.run(set(args.source) if args.source else None)
    finally:
        state.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except SyncError as exc:
        LOG.error("%s", exc)
        raise SystemExit(1)
