"""Private local feedback inbox. Never served over HTTP."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from archive_store import canonical_json
from validate_sample import require

KINDS = {'text', 'attribution', 'branch', 'relationship', 'missing', 'usage'}


class FeedbackRateLimit(Exception):
    pass


class FeedbackConflict(Exception):
    pass


def feedback_payload(payload):
    require(isinstance(payload, dict) and set(payload) == {'request_id', 'kind', 'snapshot', 'reference', 'description', 'contact'}, 'invalid feedback fields')
    require(payload['kind'] in KINDS, 'invalid feedback kind')
    for field, maximum in [('snapshot', 160), ('reference', 160), ('description', 4000), ('contact', 200), ('request_id', 36)]:
        require(isinstance(payload[field], str) and len(payload[field]) <= maximum, 'invalid feedback value')
    require(bool(payload['description'].strip()), 'description required')
    require(str(uuid.UUID(payload['request_id'])) == payload['request_id'], 'invalid request id')
    return payload


def inbox_connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with private mode before SQLite writes any contact information.
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    path.chmod(0o600)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, received_at INTEGER NOT NULL, content_hash TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT \'open\')')
    connection.commit()
    return connection


def submit_feedback(payload, path, now=None):
    payload = feedback_payload(payload)
    now = int(time.time()) if now is None else now
    digest = hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()
    connection = inbox_connect(path)
    try:
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute('SELECT content_hash FROM feedback WHERE id = ?', (payload['request_id'],)).fetchone()
        if existing:
            if existing[0] != digest:
                raise FeedbackConflict('此提交标识已用于另一份反馈，请新建反馈。')
            return {'id': payload['request_id'], 'status': 'received', 'duplicate': True}
        if connection.execute('SELECT count(*) FROM feedback WHERE received_at > ?', (now - 600,)).fetchone()[0] >= 5:
            raise FeedbackRateLimit('本机十分钟内最多提交五条反馈，请稍后重试；内容仍保留在表单中。')
        connection.execute('INSERT INTO feedback (id, received_at, content_hash, payload) VALUES (?, ?, ?, ?)', (payload['request_id'], now, digest, canonical_json(payload)))
        connection.commit()
        return {'id': payload['request_id'], 'status': 'received', 'duplicate': False}
    finally:
        connection.close()


def read_feedback(path, include_contact=False):
    # Maintenance reads must not silently create an empty inbox.
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        result = []
        for identifier, received_at, payload, status in connection.execute('SELECT id, received_at, payload, status FROM feedback ORDER BY received_at, id'):
            content = json.loads(payload)
            if not include_contact:
                content.pop('contact')
            result.append({'id': identifier, 'received_at': received_at, 'status': status, **content})
        return result
    finally:
        connection.close()
