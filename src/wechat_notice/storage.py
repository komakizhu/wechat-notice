from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import (
    AppSettings,
    AttachmentRecord,
    DeliveryStatus,
    MessageRecord,
    MessageRelation,
    NoticeRecord,
    NoticeStatus,
    ReminderStatus,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _safe_name(name: str, fallback: str = "attachment") -> str:
    clean = Path(name).name
    clean = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "_", clean).strip(" .")
    return clean[:180] or fallback


class NoticeStore:
    """SQLite-backed runtime store for batches, notices and reminders."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.root = Path(data_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.attachments_root = self.root / "batches"
        self.attachments_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.attachments_root, 0o700)
        self.db_path = self.root / "notice.sqlite3"
        self._initialize()
        if self.db_path.exists():
            os.chmod(self.db_path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    source_group TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_complete INTEGER NOT NULL DEFAULT 0,
                    read_stop_reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    local_id TEXT NOT NULL,
                    source_group TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    message_type TEXT NOT NULL DEFAULT 'unknown',
                    sender TEXT,
                    timestamp TEXT,
                    quote_id TEXT,
                    attachment_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (batch_id, local_id)
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    source_group TEXT NOT NULL,
                    source_message_id TEXT,
                    original_name TEXT NOT NULL,
                    stored_path TEXT,
                    mime_type TEXT,
                    extraction_status TEXT NOT NULL,
                    extracted_text TEXT NOT NULL DEFAULT '',
                    locations_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS message_relations (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    source_message_id TEXT NOT NULL,
                    related_message_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (batch_id, source_message_id, related_message_id, relation_type)
                );
                CREATE TABLE IF NOT EXISTS notices (
                    notice_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    title TEXT NOT NULL,
                    facts_json TEXT NOT NULL DEFAULT '{}',
                    source_message_ids_json TEXT NOT NULL DEFAULT '[]',
                    attachment_ids_json TEXT NOT NULL DEFAULT '[]',
                    collection_required INTEGER NOT NULL DEFAULT 0,
                    original_deadline TEXT,
                    class_deadline TEXT,
                    advance_days INTEGER,
                    show_original_deadline INTEGER,
                    reminder_offsets_json TEXT,
                    reminder_template TEXT NOT NULL,
                    submission_method TEXT NOT NULL,
                    polished_text TEXT NOT NULL DEFAULT '',
                    concise_text TEXT NOT NULL DEFAULT '',
                    review_notes TEXT NOT NULL DEFAULT '',
                    target_group TEXT,
                    reminders_enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id TEXT NOT NULL REFERENCES notices(notice_id),
                    scheduled_for TEXT NOT NULL,
                    offset_days INTEGER NOT NULL,
                    notice_revision INTEGER NOT NULL,
                    rendered_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    generated_at TEXT,
                    approved_at TEXT,
                    sent_at TEXT,
                    UNIQUE (notice_id, scheduled_for, notice_revision)
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id TEXT NOT NULL REFERENCES notices(notice_id),
                    notice_revision INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    attachment_id TEXT,
                    target_group TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS deliveries_notice_idx
                    ON deliveries(notice_id, notice_revision);
                CREATE INDEX IF NOT EXISTS reminders_due_idx
                    ON reminders(status, scheduled_for);
                CREATE TABLE IF NOT EXISTS overdue_reports (
                    notice_id TEXT NOT NULL,
                    notice_revision INTEGER NOT NULL,
                    reported_at TEXT NOT NULL,
                    PRIMARY KEY (notice_id, notice_revision),
                    FOREIGN KEY (notice_id) REFERENCES notices(notice_id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    notice_id TEXT NOT NULL REFERENCES notices(notice_id),
                    notice_revision INTEGER NOT NULL,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (notice_id, notice_revision, artifact_type)
                );
                CREATE TABLE IF NOT EXISTS seen_messages (
                    source_group TEXT NOT NULL,
                    stable_key TEXT NOT NULL,
                    local_id TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (source_group, stable_key)
                );
                CREATE TABLE IF NOT EXISTS monitor_cursors (
                    source_group TEXT PRIMARY KEY,
                    cursor_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS materials (
                    material_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    source_url TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    locations_json TEXT NOT NULL DEFAULT '[]',
                    linked_urls_json TEXT NOT NULL DEFAULT '[]',
                    image_urls_json TEXT NOT NULL DEFAULT '[]',
                    ocr_locations_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    read_at TEXT NOT NULL,
                    UNIQUE (batch_id, source_url)
                );
                """
            )
            notice_columns = {
                row[1] for row in db.execute("PRAGMA table_info(notices)").fetchall()
            }
            if "reminders_enabled" not in notice_columns:
                db.execute(
                    "ALTER TABLE notices ADD COLUMN reminders_enabled INTEGER NOT NULL DEFAULT 1"
                )
            if "facts_json" not in notice_columns:
                db.execute(
                    "ALTER TABLE notices ADD COLUMN facts_json TEXT NOT NULL DEFAULT '{}'"
                )

    def save_settings(self, settings: AppSettings) -> None:
        payload = settings.to_dict()
        with self._connect() as db:
            db.execute(
                """INSERT INTO settings(key, value_json, updated_at)
                   VALUES ('app', ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                                                 updated_at=excluded.updated_at""",
                (_json(payload), utc_now()),
            )

    def load_settings(self) -> AppSettings:
        with self._connect() as db:
            row = db.execute("SELECT value_json FROM settings WHERE key='app'").fetchone()
        return AppSettings.from_dict(_load_json(row["value_json"], {}) if row else {})

    def save_batch(
        self,
        batch_id: str,
        source_group: str,
        messages: Iterable[MessageRecord],
        *,
        read_complete: bool = False,
        read_stop_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        message_list = list(messages)
        with self._connect() as db:
            db.execute(
                """INSERT INTO batches(batch_id, source_group, created_at, read_complete,
                   read_stop_reason, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(batch_id) DO UPDATE SET source_group=excluded.source_group,
                   read_complete=excluded.read_complete,
                   read_stop_reason=excluded.read_stop_reason,
                   metadata_json=excluded.metadata_json""",
                (
                    batch_id,
                    source_group,
                    utc_now(),
                    int(read_complete),
                    read_stop_reason,
                    _json(metadata or {}),
                ),
            )
            db.execute("DELETE FROM messages WHERE batch_id=?", (batch_id,))
            db.execute("DELETE FROM message_relations WHERE batch_id=?", (batch_id,))
            db.executemany(
                """INSERT INTO messages(batch_id, local_id, source_group, sequence, text,
                   message_type, sender, timestamp, quote_id, attachment_ids_json, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        batch_id,
                        message.local_id,
                        message.source_group,
                        message.sequence,
                        message.text,
                        message.message_type,
                        message.sender,
                        message.timestamp,
                        message.quote_id,
                        _json(list(message.attachment_ids)),
                        _json(message.metadata),
                    )
                    for message in message_list
                ],
            )

    def save_message_relations(
        self, batch_id: str, relations: Iterable[MessageRelation]
    ) -> None:
        relation_list = list(relations)
        with self._connect() as db:
            db.execute("DELETE FROM message_relations WHERE batch_id=?", (batch_id,))
            db.executemany(
                """INSERT INTO message_relations(
                   batch_id, source_message_id, related_message_id,
                   relation_type, confirmed, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        batch_id,
                        relation.source_message_id,
                        relation.related_message_id,
                        relation.relation_type,
                        int(relation.confirmed),
                        relation.note,
                    )
                    for relation in relation_list
                ],
            )

    def list_message_relations(self, batch_id: str) -> list[MessageRelation]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT source_message_id, related_message_id, relation_type,
                          confirmed, note
                   FROM message_relations
                   WHERE batch_id=?
                   ORDER BY rowid""",
                (batch_id,),
            ).fetchall()
        return [
            MessageRelation(
                source_message_id=row["source_message_id"],
                related_message_id=row["related_message_id"],
                relation_type=row["relation_type"],
                confirmed=bool(row["confirmed"]),
                note=row["note"],
            )
            for row in rows
        ]

    def get_batch_messages(self, batch_id: str) -> list[MessageRecord]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE batch_id=? ORDER BY sequence, local_id", (batch_id,)
            ).fetchall()
        return [
            MessageRecord(
                local_id=row["local_id"],
                source_group=row["source_group"],
                sequence=row["sequence"],
                text=row["text"],
                message_type=row["message_type"],
                sender=row["sender"],
                timestamp=row["timestamp"],
                quote_id=row["quote_id"],
                attachment_ids=tuple(_load_json(row["attachment_ids_json"], [])),
                metadata=_load_json(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def get_batch_info(self, batch_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            return None
        return {
            "batch_id": row["batch_id"],
            "source_group": row["source_group"],
            "created_at": row["created_at"],
            "read_complete": bool(row["read_complete"]),
            "read_stop_reason": row["read_stop_reason"],
            "metadata": _load_json(row["metadata_json"], {}),
        }

    def save_attachment(
        self,
        batch_id: str,
        attachment: AttachmentRecord,
        source_path: str | Path | None = None,
    ) -> AttachmentRecord:
        stored_path = attachment.stored_path
        with self._connect() as db:
            existing = db.execute(
                "SELECT batch_id FROM attachments WHERE attachment_id=?",
                (attachment.attachment_id,),
            ).fetchone()
        if existing is not None and existing["batch_id"] != batch_id:
            raise ValueError(f"附件编号已属于其他批次: {attachment.attachment_id}")
        if source_path is not None:
            source = Path(source_path).expanduser()
            if not source.is_file():
                raise FileNotFoundError(f"附件不存在或不是文件: {source}")
            destination_dir = self.attachments_root / _safe_name(batch_id, "batch")
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"{_safe_name(attachment.attachment_id)}-{_safe_name(attachment.original_name)}"
            shutil.copy2(source, destination)
            os.chmod(destination, 0o600)
            stored_path = str(destination)

        record = AttachmentRecord(
            attachment_id=attachment.attachment_id,
            source_group=attachment.source_group,
            source_message_id=attachment.source_message_id,
            original_name=attachment.original_name,
            stored_path=stored_path,
            mime_type=attachment.mime_type or mimetypes.guess_type(attachment.original_name)[0],
            extraction_status=attachment.extraction_status,
            extracted_text=attachment.extracted_text,
            locations=attachment.locations,
            error=attachment.error,
        )
        with self._connect() as db:
            existing = db.execute(
                "SELECT batch_id FROM attachments WHERE attachment_id=?",
                (record.attachment_id,),
            ).fetchone()
            if existing is not None and existing["batch_id"] != batch_id:
                raise ValueError(
                    f"附件编号已属于其他批次: {record.attachment_id}"
                )
            db.execute(
                """INSERT INTO attachments(attachment_id, batch_id, source_group,
                   source_message_id, original_name, stored_path, mime_type,
                   extraction_status, extracted_text, locations_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(attachment_id) DO UPDATE SET batch_id=excluded.batch_id,
                   source_group=excluded.source_group,
                   source_message_id=excluded.source_message_id,
                   original_name=excluded.original_name, stored_path=excluded.stored_path,
                   mime_type=excluded.mime_type, extraction_status=excluded.extraction_status,
                   extracted_text=excluded.extracted_text, locations_json=excluded.locations_json,
                   error=excluded.error""",
                (
                    record.attachment_id,
                    batch_id,
                    record.source_group,
                    record.source_message_id,
                    record.original_name,
                    record.stored_path,
                    record.mime_type,
                    record.extraction_status,
                    record.extracted_text,
                    _json(list(record.locations)),
                    record.error,
                ),
            )
        return record

    def get_attachment(self, attachment_id: str) -> AttachmentRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM attachments WHERE attachment_id=?", (attachment_id,)).fetchone()
        if row is None:
            return None
        return AttachmentRecord(
            attachment_id=row["attachment_id"],
            source_group=row["source_group"],
            source_message_id=row["source_message_id"],
            original_name=row["original_name"],
            stored_path=row["stored_path"],
            mime_type=row["mime_type"],
            extraction_status=row["extraction_status"],
            extracted_text=row["extracted_text"],
            locations=tuple(_load_json(row["locations_json"], [])),
            error=row["error"],
        )

    def list_batch_attachments(self, batch_id: str) -> list[AttachmentRecord]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM attachments WHERE batch_id=? ORDER BY attachment_id", (batch_id,)
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                AttachmentRecord(
                    attachment_id=row["attachment_id"],
                    source_group=row["source_group"],
                    source_message_id=row["source_message_id"],
                    original_name=row["original_name"],
                    stored_path=row["stored_path"],
                    mime_type=row["mime_type"],
                    extraction_status=row["extraction_status"],
                    extracted_text=row["extracted_text"],
                    locations=tuple(_load_json(row["locations_json"], [])),
                    error=row["error"],
                )
            )
        return result

    def save_notice(self, notice: NoticeRecord) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO notices(
                   notice_id, batch_id, title, facts_json, source_message_ids_json,
                   attachment_ids_json, collection_required, original_deadline,
                   class_deadline, advance_days, show_original_deadline,
                   reminder_offsets_json, reminder_template, submission_method,
                   polished_text, concise_text, review_notes, target_group,
                   reminders_enabled, status, delivery_status, revision, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(notice_id) DO UPDATE SET batch_id=excluded.batch_id,
                   title=excluded.title, facts_json=excluded.facts_json,
                   source_message_ids_json=excluded.source_message_ids_json,
                   attachment_ids_json=excluded.attachment_ids_json,
                   collection_required=excluded.collection_required,
                   original_deadline=excluded.original_deadline,
                   class_deadline=excluded.class_deadline, advance_days=excluded.advance_days,
                   show_original_deadline=excluded.show_original_deadline,
                   reminder_offsets_json=excluded.reminder_offsets_json,
                   reminder_template=excluded.reminder_template,
                   submission_method=excluded.submission_method,
                   polished_text=excluded.polished_text, concise_text=excluded.concise_text,
                   review_notes=excluded.review_notes, target_group=excluded.target_group,
                   reminders_enabled=excluded.reminders_enabled,
                   status=excluded.status, delivery_status=excluded.delivery_status,
                   revision=excluded.revision, updated_at=excluded.updated_at""",
                (
                    notice.notice_id,
                    notice.batch_id,
                    notice.title,
                    _json(notice.facts),
                    _json(notice.source_message_ids),
                    _json(notice.attachment_ids),
                    int(notice.collection_required),
                    notice.original_deadline,
                    notice.class_deadline,
                    notice.advance_days,
                    None if notice.show_original_deadline is None else int(notice.show_original_deadline),
                    None if notice.reminder_offsets is None else _json(notice.reminder_offsets),
                    notice.reminder_template,
                    notice.submission_method,
                    notice.polished_text,
                    notice.concise_text,
                    notice.review_notes,
                    notice.target_group,
                    int(notice.reminders_enabled),
                    notice.status.value,
                    notice.delivery_status.value,
                    notice.revision,
                    utc_now(),
                ),
            )

    def _notice_from_row(self, row: sqlite3.Row) -> NoticeRecord:
        return NoticeRecord(
            notice_id=row["notice_id"],
            batch_id=row["batch_id"],
            title=row["title"],
            facts=_load_json(row["facts_json"], {}) if "facts_json" in row.keys() else {},
            source_message_ids=list(_load_json(row["source_message_ids_json"], [])),
            attachment_ids=list(_load_json(row["attachment_ids_json"], [])),
            collection_required=bool(row["collection_required"]),
            original_deadline=row["original_deadline"],
            class_deadline=row["class_deadline"],
            advance_days=row["advance_days"],
            show_original_deadline=None if row["show_original_deadline"] is None else bool(row["show_original_deadline"]),
            reminder_offsets=None
            if row["reminder_offsets_json"] is None
            else list(_load_json(row["reminder_offsets_json"], [])),
            reminder_template=row["reminder_template"],
            submission_method=row["submission_method"],
            polished_text=row["polished_text"],
            concise_text=row["concise_text"],
            review_notes=row["review_notes"],
            target_group=row["target_group"],
            reminders_enabled=bool(row["reminders_enabled"]),
            status=NoticeStatus(row["status"]),
            delivery_status=DeliveryStatus(row["delivery_status"]),
            revision=row["revision"],
        )

    def save_artifact(
        self,
        *,
        notice_id: str,
        notice_revision: int,
        artifact_type: str,
        path: str | Path,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Bind one generated file to the exact notice revision."""
        if not artifact_type.strip():
            raise ValueError("artifact_type 不能为空")
        candidate = Path(path).expanduser().resolve()
        with self._connect() as db:
            notice = db.execute(
                "SELECT revision FROM notices WHERE notice_id=?", (notice_id,)
            ).fetchone()
            if notice is None:
                raise KeyError(f"通知不存在: {notice_id}")
            if int(notice["revision"]) != notice_revision:
                raise ValueError("产出文件绑定的通知版本已失效")
            identifier = artifact_id or f"artifact-{uuid.uuid4().hex}"
            db.execute(
                """INSERT INTO artifacts(
                   artifact_id, notice_id, notice_revision, artifact_type, path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(notice_id, notice_revision, artifact_type) DO UPDATE SET
                   artifact_id=excluded.artifact_id, path=excluded.path,
                   created_at=excluded.created_at""",
                (
                    identifier,
                    notice_id,
                    notice_revision,
                    artifact_type,
                    str(candidate),
                    utc_now(),
                ),
            )
        return {
            "artifact_id": identifier,
            "notice_id": notice_id,
            "notice_revision": notice_revision,
            "artifact_type": artifact_type,
            "path": str(candidate),
        }

    def list_artifacts(
        self, notice_id: str, *, notice_revision: int | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM artifacts WHERE notice_id=?"
        params: list[Any] = [notice_id]
        if notice_revision is not None:
            query += " AND notice_revision=?"
            params.append(notice_revision)
        query += " ORDER BY artifact_type"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def mark_message_seen(
        self,
        *,
        source_group: str,
        stable_key: str,
        local_id: str,
        text_hash: str,
        at: str | None = None,
    ) -> bool:
        """Record a stable message key and return whether it was new."""
        if not stable_key.strip():
            raise ValueError("stable_key 不能为空")
        timestamp = at or utc_now()
        with self._connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO seen_messages(
                   source_group, stable_key, local_id, text_hash, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source_group, stable_key, local_id, text_hash, timestamp, timestamp),
            )
            db.execute(
                """UPDATE seen_messages SET last_seen_at=?, local_id=?, text_hash=?
                   WHERE source_group=? AND stable_key=?""",
                (timestamp, local_id, text_hash, source_group, stable_key),
            )
        return cursor.rowcount == 1

    def save_monitor_cursor(
        self, source_group: str, cursor: dict[str, Any], *, at: str | None = None
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO monitor_cursors(source_group, cursor_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(source_group) DO UPDATE SET cursor_json=excluded.cursor_json,
                   updated_at=excluded.updated_at""",
                (source_group, _json(cursor), at or utc_now()),
            )

    def get_monitor_cursor(self, source_group: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT cursor_json FROM monitor_cursors WHERE source_group=?",
                (source_group,),
            ).fetchone()
        return _load_json(row["cursor_json"], {}) if row else None

    def save_material(
        self,
        batch_id: str,
        material: dict[str, Any],
        *,
        material_id: str | None = None,
        at: str | None = None,
    ) -> str:
        source_url = str(material.get("source_url", "")).strip()
        if not source_url:
            raise ValueError("material.source_url 不能为空")
        identifier = material_id or f"material-{uuid.uuid4().hex}"
        with self._connect() as db:
            if db.execute("SELECT 1 FROM batches WHERE batch_id=?", (batch_id,)).fetchone() is None:
                raise KeyError(f"批次不存在: {batch_id}")
            existing = db.execute(
                "SELECT material_id FROM materials WHERE batch_id=? AND source_url=?",
                (batch_id, source_url),
            ).fetchone()
            if existing is not None:
                identifier = str(existing["material_id"])
            db.execute(
                """INSERT INTO materials(
                   material_id, batch_id, source_url, kind, status, title, text,
                   locations_json, linked_urls_json, image_urls_json,
                   ocr_locations_json, error, read_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(material_id) DO UPDATE SET source_url=excluded.source_url,
                   kind=excluded.kind, status=excluded.status, title=excluded.title,
                   text=excluded.text, locations_json=excluded.locations_json,
                   linked_urls_json=excluded.linked_urls_json, image_urls_json=excluded.image_urls_json,
                   ocr_locations_json=excluded.ocr_locations_json, error=excluded.error,
                   read_at=excluded.read_at""",
                (
                    identifier,
                    batch_id,
                    source_url,
                    str(material.get("kind", "web")),
                    str(material.get("status", "unknown")),
                    str(material.get("title", "")),
                    str(material.get("text", "")),
                    _json(material.get("locations", [])),
                    _json(material.get("linked_urls", [])),
                    _json(material.get("image_urls", [])),
                    _json(material.get("ocr_locations", [])),
                    material.get("error"),
                    at or utc_now(),
                ),
            )
        return identifier

    def list_materials(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM materials WHERE batch_id=? ORDER BY material_id", (batch_id,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in (
                "locations_json",
                "linked_urls_json",
                "image_urls_json",
                "ocr_locations_json",
            ):
                item[key.removesuffix("_json")] = _load_json(item.pop(key), [])
            result.append(item)
        return result

    def get_notice(self, notice_id: str) -> NoticeRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM notices WHERE notice_id=?", (notice_id,)).fetchone()
        return self._notice_from_row(row) if row else None

    def list_notices(self, *, include_cancelled: bool = False) -> list[NoticeRecord]:
        query = "SELECT * FROM notices"
        params: tuple[Any, ...] = ()
        if not include_cancelled:
            query += " WHERE status != ?"
            params = (NoticeStatus.CANCELLED.value,)
        query += " ORDER BY updated_at, notice_id"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._notice_from_row(row) for row in rows]

    def approve_notice(self, notice_id: str) -> NoticeRecord:
        notice = self.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        if notice.status == NoticeStatus.CANCELLED:
            raise ValueError("已取消的通知不能重新审核")
        self._validate_approval(notice)
        notice.status = NoticeStatus.APPROVED
        self.save_notice(notice)
        return notice

    def cancel_notice(self, notice_id: str) -> NoticeRecord:
        notice = self.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        notice.status = NoticeStatus.CANCELLED
        self.save_notice(notice)
        with self._connect() as db:
            db.execute(
                "UPDATE reminders SET status=? WHERE notice_id=? AND status IN (?, ?, ?)",
                (
                    ReminderStatus.CANCELLED.value,
                    notice_id,
                    ReminderStatus.PENDING.value,
                    ReminderStatus.GENERATED.value,
                    ReminderStatus.APPROVED.value,
                ),
            )
        return notice

    def save_review(
        self,
        notice_id: str,
        *,
        polished_text: str,
        concise_text: str,
        review_notes: str = "",
        approved: bool = False,
    ) -> NoticeRecord:
        notice = self.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        if notice.status == NoticeStatus.CANCELLED:
            raise ValueError("已取消的通知不能重新审核")
        if approved:
            self._validate_approval(
                notice,
                polished_text=polished_text,
                concise_text=concise_text,
            )
        notice.polished_text = polished_text
        notice.concise_text = concise_text
        notice.review_notes = review_notes
        notice.status = NoticeStatus.APPROVED if approved else NoticeStatus.DRAFT
        notice.revision += 1
        notice.delivery_status = DeliveryStatus.NOT_ATTEMPTED
        self.save_notice(notice)
        return notice

    @staticmethod
    def _validate_approval(
        notice: NoticeRecord,
        *,
        polished_text: str | None = None,
        concise_text: str | None = None,
    ) -> None:
        polished = notice.polished_text if polished_text is None else polished_text
        concise = notice.concise_text if concise_text is None else concise_text
        if not polished.strip() or not concise.strip():
            raise ValueError("审核通过前必须同时提供通知润色版和省流版")
        if not notice.target_group or not notice.target_group.strip():
            raise ValueError("审核通过前必须明确目标群")

    def sync_reminders(self, reminders: Iterable[tuple[str, int, str, str, int]]) -> None:
        """Reconcile pending reminder rows with desired (notice, offset, time, text) rows."""
        desired = {(notice_id, scheduled_for, offset, revision): text for notice_id, offset, scheduled_for, text, revision in reminders}
        with self._connect() as db:
            rows = db.execute(
                "SELECT reminder_id, notice_id, scheduled_for, offset_days, notice_revision, status FROM reminders"
            ).fetchall()
            for row in rows:
                key = (row["notice_id"], row["scheduled_for"], row["offset_days"], row["notice_revision"])
                if key not in desired and row["status"] in {
                    ReminderStatus.PENDING.value,
                    ReminderStatus.GENERATED.value,
                    ReminderStatus.APPROVED.value,
                }:
                    db.execute(
                        "UPDATE reminders SET status=? WHERE reminder_id=?",
                        (ReminderStatus.CANCELLED.value, row["reminder_id"]),
                    )
            db.executemany(
                """INSERT OR IGNORE INTO reminders(
                   notice_id, scheduled_for, offset_days, notice_revision,
                   rendered_text, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (notice_id, scheduled_for, offset, revision, text, ReminderStatus.PENDING.value)
                    for (notice_id, scheduled_for, offset, revision), text in desired.items()
                ],
            )

    def prepare_due_reminders(self, now_iso: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            # Serialize the claim so two simultaneous Codex wake-ups cannot
            # both observe the same pending rows.
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT r.* FROM reminders AS r
                   JOIN notices AS n ON n.notice_id=r.notice_id
                   WHERE r.status=? AND r.scheduled_for<=?
                     AND n.status=? AND n.reminders_enabled=1
                     AND n.revision=r.notice_revision
                   ORDER BY r.scheduled_for, r.reminder_id""",
                (ReminderStatus.PENDING.value, now_iso, NoticeStatus.APPROVED.value),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE reminders SET status=?, generated_at=? WHERE reminder_id=?",
                    (ReminderStatus.GENERATED.value, now_iso, row["reminder_id"]),
                )
        result = []
        for row in rows:
            item = dict(row)
            item["status"] = ReminderStatus.GENERATED.value
            item["generated_at"] = now_iso
            result.append(item)
        return result

    def record_delivery(
        self,
        *,
        notice_id: str,
        notice_revision: int,
        content_type: str,
        target_group: str,
        status: DeliveryStatus,
        attachment_id: str | None = None,
        detail: str | None = None,
        at: str | None = None,
    ) -> int:
        if content_type not in {"text", "file"}:
            raise ValueError("content_type must be text or file")
        with self._connect() as db:
            notice = db.execute(
                "SELECT revision, status, target_group FROM notices WHERE notice_id=?",
                (notice_id,),
            ).fetchone()
            if notice is None:
                raise KeyError(f"通知不存在: {notice_id}")
            if notice["status"] != NoticeStatus.APPROVED.value:
                raise ValueError("只有已审核通知可以记录逐项投递")
            if notice["revision"] != notice_revision:
                raise ValueError("投递记录的通知版本已失效")
            if not notice["target_group"] or notice["target_group"] != target_group:
                raise ValueError("投递记录的目标群与审核记录不一致")
            cursor = db.execute(
                """INSERT INTO deliveries(
                   notice_id, notice_revision, content_type, attachment_id,
                   target_group, status, detail, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    notice_id,
                    notice_revision,
                    content_type,
                    attachment_id,
                    target_group,
                    status.value,
                    detail,
                    at or utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_deliveries(self, notice_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM deliveries WHERE notice_id=? ORDER BY delivery_id",
                (notice_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_delivery_status(
        self,
        delivery_id: int,
        status: DeliveryStatus,
        *,
        at: str | None = None,
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT status FROM deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"投递记录不存在: {delivery_id}")
            current = DeliveryStatus(row["status"])
            allowed = {
                DeliveryStatus.NOT_ATTEMPTED: {
                    DeliveryStatus.NOT_ATTEMPTED,
                    DeliveryStatus.RESULT_UNCERTAIN,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.RESULT_UNCERTAIN: {
                    DeliveryStatus.RESULT_UNCERTAIN,
                    DeliveryStatus.OBSERVED_SENT,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.OBSERVED_SENT: {
                    DeliveryStatus.OBSERVED_SENT,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.USER_CONFIRMED_SENT: {
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
            }
            if status not in allowed[current]:
                raise ValueError(f"不允许的投递状态迁移: {current} -> {status}")
            db.execute(
                "UPDATE deliveries SET status=?, recorded_at=? WHERE delivery_id=?",
                (status.value, at or utc_now(), delivery_id),
            )

    def list_reminders(self, notice_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM reminders WHERE notice_id=? ORDER BY reminder_id", (notice_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_overdue_report(self, notice_id: str, notice_revision: int, now_iso: str) -> bool:
        """Claim one overdue notice report for a particular notice revision."""
        with self._connect() as db:
            db.execute(
                """UPDATE reminders SET status=?
                   WHERE notice_id=? AND notice_revision=?
                     AND status=?""",
                (
                    ReminderStatus.CANCELLED.value,
                    notice_id,
                    notice_revision,
                    ReminderStatus.PENDING.value,
                ),
            )
            cursor = db.execute(
                """INSERT OR IGNORE INTO overdue_reports(notice_id, notice_revision, reported_at)
                   VALUES (?, ?, ?)""",
                (notice_id, notice_revision, now_iso),
            )
        return cursor.rowcount == 1

    def set_reminder_status(
        self,
        reminder_id: int,
        status: ReminderStatus,
        *,
        at: str | None = None,
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT status FROM reminders WHERE reminder_id=?", (reminder_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"提醒记录不存在: {reminder_id}")
            current = ReminderStatus(row["status"])
            allowed = {
                ReminderStatus.PENDING: {
                    ReminderStatus.PENDING,
                    ReminderStatus.CANCELLED,
                },
                ReminderStatus.GENERATED: {
                    ReminderStatus.GENERATED,
                    ReminderStatus.APPROVED,
                    ReminderStatus.CANCELLED,
                },
                ReminderStatus.APPROVED: {
                    ReminderStatus.APPROVED,
                    ReminderStatus.SENT,
                    ReminderStatus.CANCELLED,
                },
                ReminderStatus.SENT: {ReminderStatus.SENT},
                ReminderStatus.CANCELLED: {ReminderStatus.CANCELLED},
            }
            if status not in allowed[current]:
                raise ValueError(f"不允许的提醒状态迁移: {current} -> {status}")
            field = {
                ReminderStatus.APPROVED: "approved_at",
                ReminderStatus.SENT: "sent_at",
            }.get(status)
            if field:
                db.execute(
                    f"UPDATE reminders SET status=?, {field}=? WHERE reminder_id=?",
                    (status.value, at or utc_now(), reminder_id),
                )
            else:
                db.execute(
                    "UPDATE reminders SET status=? WHERE reminder_id=?",
                    (status.value, reminder_id),
                )

    def cancel_reminders(self, reminder_ids: Iterable[int]) -> None:
        ids = list(reminder_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as db:
            db.execute(
                f"UPDATE reminders SET status=? WHERE reminder_id IN ({placeholders})",
                (ReminderStatus.CANCELLED.value, *ids),
            )

    def set_delivery_status(self, notice_id: str, status: DeliveryStatus) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT status, delivery_status FROM notices WHERE notice_id=?",
                (notice_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"通知不存在: {notice_id}")
            current = DeliveryStatus(row["delivery_status"])
            if status != current and status != DeliveryStatus.NOT_ATTEMPTED:
                if row["status"] != NoticeStatus.APPROVED.value:
                    raise ValueError("只有已审核通知可以记录投递结果")
            allowed = {
                DeliveryStatus.NOT_ATTEMPTED: {
                    DeliveryStatus.NOT_ATTEMPTED,
                    DeliveryStatus.RESULT_UNCERTAIN,
                    DeliveryStatus.OBSERVED_SENT,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.RESULT_UNCERTAIN: {
                    DeliveryStatus.RESULT_UNCERTAIN,
                    DeliveryStatus.OBSERVED_SENT,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.OBSERVED_SENT: {
                    DeliveryStatus.OBSERVED_SENT,
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
                DeliveryStatus.USER_CONFIRMED_SENT: {
                    DeliveryStatus.USER_CONFIRMED_SENT,
                },
            }
            if status not in allowed[current]:
                raise ValueError(f"不允许的投递状态迁移: {current} -> {status}")
            db.execute(
                "UPDATE notices SET delivery_status=?, updated_at=? WHERE notice_id=?",
                (status.value, utc_now(), notice_id),
            )
