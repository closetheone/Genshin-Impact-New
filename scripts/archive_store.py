import hashlib
import json
from pathlib import Path
import sqlite3

from validate_sample import validate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data/local/archive.sqlite3"
COLLECTIONS = ("sources", "entries", "characters", "passages", "relationships")
SCHEMA_VERSION = 1
SCHEMA = (
    "CREATE TABLE snapshots (id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, metadata TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE identities (id TEXT PRIMARY KEY, collection TEXT NOT NULL CHECK(collection IN ('sources', 'entries', 'characters', 'passages', 'relationships')))",
    "CREATE TABLE records (snapshot_id TEXT NOT NULL REFERENCES snapshots(id), id TEXT NOT NULL REFERENCES identities(id), collection TEXT NOT NULL, position INTEGER NOT NULL CHECK(position >= 0), payload TEXT NOT NULL, PRIMARY KEY(snapshot_id, id), UNIQUE(snapshot_id, collection, position))",
    "CREATE TABLE source_policies (id TEXT PRIMARY KEY REFERENCES identities(id), rights TEXT NOT NULL)",
    "CREATE TABLE withdrawals (id TEXT PRIMARY KEY REFERENCES identities(id), first_snapshot_id TEXT NOT NULL REFERENCES snapshots(id))",
    "CREATE TABLE archive_state (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), active_snapshot_id TEXT REFERENCES snapshots(id))",
    "INSERT INTO archive_state (singleton, active_snapshot_id) VALUES (1, NULL)",
)


class StoreError(Exception):
    pass


class SnapshotNotFound(StoreError):
    pass


def ensure_synthetic_dataset(data, source_name=None):
    """Reject source-audit metadata and non-synthetic payloads before opening storage."""
    if not isinstance(data, dict):
        raise ValueError("Synthetic importer accepts a JSON object only.")
    if (source_name == "source-audit.json"
            or data.get("schema_version") == "source-audit-0.1"
            or data.get("record_kind") == "source_metadata"
            or ("pages" in data and "dataset_kind" not in data)):
        raise ValueError(
            "Refusing to import source-audit metadata; run report_source_admission.py first, "
            "then provide an admitted synthetic fixture to import_sample.py."
        )
    if data.get("dataset_kind") != "synthetic":
        raise ValueError(
            "Synthetic importer accepts dataset_kind: synthetic only; real sources must first "
            "pass report_source_admission.py and a separate authorized import workflow."
        )
    return data


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(data):
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def connect(database, writable=False):
    path = Path(database).expanduser().resolve()
    if writable:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"{path.as_uri()}?mode={'rwc' if writable else 'ro'}", uri=True, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_schema(connection, initialize=False):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version != 0 or not initialize:
        raise StoreError("Unsupported or uninitialized archive schema; use the importer with an empty database.")
    if connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
        raise StoreError("Refusing to initialize an unrelated database.")
    for statement in SCHEMA:
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def import_snapshot(data, database=DEFAULT_DATABASE, activate=False):
    ensure_synthetic_dataset(data)
    indexes = validate(data)
    digest = content_hash(data)
    snapshot_id = data["snapshot_id"]
    connection = connect(database, writable=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_schema(connection, initialize=True)
        from query_index import ensure_indexes, build_index
        ensure_indexes(connection)
        existing = connection.execute("SELECT content_hash FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if existing and existing["content_hash"] != digest:
            raise StoreError("Snapshot ID already exists with different content; create a new snapshot ID instead of overwriting citations.")
        if existing:
            read_snapshot(connection, snapshot_id)
            ready = connection.execute('SELECT ready FROM query_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
            if not ready or not ready['ready']:
                build_index(connection, data)
        else:
            metadata = {key: value for key, value in data.items() if key not in COLLECTIONS}
            connection.execute("INSERT INTO snapshots (id, content_hash, metadata) VALUES (?, ?, ?)", (snapshot_id, digest, canonical_json(metadata)))
            for collection in COLLECTIONS:
                for position, record in enumerate(data[collection]):
                    identity = connection.execute("SELECT collection FROM identities WHERE id = ?", (record["id"],)).fetchone()
                    if identity and identity["collection"] != collection:
                        raise StoreError("A stable identifier cannot change collection across snapshots.")
                    connection.execute("INSERT OR IGNORE INTO identities (id, collection) VALUES (?, ?)", (record["id"], collection))
                    connection.execute(
                        "INSERT INTO records (snapshot_id, id, collection, position, payload) VALUES (?, ?, ?, ?, ?)",
                        (snapshot_id, record["id"], collection, position, canonical_json(record)),
                    )
            for source in data["sources"]:
                previous = connection.execute("SELECT rights FROM source_policies WHERE id = ?", (source["id"],)).fetchone()
                previous_rights = json.loads(previous["rights"]) if previous else source["rights"]
                combined = {}
                for purpose, right in source["rights"].items():
                    values = {right, previous_rights[purpose]}
                    combined[purpose] = "denied" if "denied" in values else "unknown" if "unknown" in values else "allowed"
                connection.execute("INSERT INTO source_policies (id, rights) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET rights = excluded.rights", (source["id"], canonical_json(combined)))
            connection.executemany(
                "INSERT OR IGNORE INTO withdrawals (id, first_snapshot_id) VALUES (?, ?)",
                [(identifier, snapshot_id) for identifier in data["withdrawn_ids"]],
            )
            build_index(connection, data)
        active = connection.execute("SELECT active_snapshot_id FROM archive_state WHERE singleton = 1").fetchone()
        if active is None:
            raise StoreError("Archive state is missing.")
        if activate or active["active_snapshot_id"] is None:
            connection.execute("UPDATE archive_state SET active_snapshot_id = ? WHERE singleton = 1", (snapshot_id,))
        active_id = connection.execute("SELECT active_snapshot_id FROM archive_state WHERE singleton = 1").fetchone()[0]
        connection.commit()
        return {
            "status": "unchanged" if existing else "imported", "snapshot_id": snapshot_id,
            "active_snapshot_id": active_id, "content_hash": digest,
            "counts": {collection: len(indexes[collection]) for collection in COLLECTIONS},
            "database": str(Path(database).expanduser().resolve()),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_snapshot(connection, snapshot_id=None, apply_restrictions=True):
    if snapshot_id is None:
        active = connection.execute("SELECT active_snapshot_id FROM archive_state WHERE singleton = 1").fetchone()
        if not active or active["active_snapshot_id"] is None:
            raise StoreError("No active snapshot; import a synthetic fixture first.")
        snapshot_id = active["active_snapshot_id"]
    snapshot = connection.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if snapshot is None:
        raise SnapshotNotFound("Snapshot is unavailable; it was not replaced with the active snapshot.")
    data = json.loads(snapshot["metadata"])
    for collection in COLLECTIONS:
        rows = connection.execute("SELECT id, position, payload FROM records WHERE snapshot_id = ? AND collection = ? ORDER BY position", (snapshot_id, collection)).fetchall()
        data[collection] = []
        for position, row in enumerate(rows):
            record = json.loads(row["payload"])
            if row["position"] != position or record["id"] != row["id"]:
                raise StoreError("Stored record identity or order is inconsistent.")
            data[collection].append(record)
    validate(data)
    if data["snapshot_id"] != snapshot_id or content_hash(data) != snapshot["content_hash"]:
        raise StoreError("Stored snapshot integrity check failed.")
    if not apply_restrictions:
        return data
    all_ids = {record["id"] for collection in COLLECTIONS for record in data[collection]}
    withdrawn = {row["id"] for row in connection.execute("SELECT id FROM withdrawals")}
    data["withdrawn_ids"] = sorted(set(data["withdrawn_ids"]) | (withdrawn & all_ids))
    for source in data["sources"]:
        policy = connection.execute("SELECT rights FROM source_policies WHERE id = ?", (source["id"],)).fetchone()
        if policy is None:
            raise StoreError("Current source policy is missing.")
        source["rights"] = json.loads(policy["rights"])
    validate(data)
    return data


def load_snapshot(database=DEFAULT_DATABASE, snapshot_id=None):
    connection = None
    try:
        connection = connect(database)
        connection.execute("BEGIN")
        ensure_schema(connection)
        return read_snapshot(connection, snapshot_id)
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
        raise StoreError("Cannot read a valid stored snapshot; check the local archive database.") from error
    finally:
        if connection is not None:
            connection.rollback()
            connection.close()
