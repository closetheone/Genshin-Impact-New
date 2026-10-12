"""Offline/local archive verification, SQLite backup, safe restore and activation."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import uuid

from archive_store import StoreError, canonical_json, connect, ensure_schema, read_snapshot
from feedback_store import feedback_payload

RANK = {'allowed': 0, 'unknown': 1, 'denied': 2}
PURPOSES = {'storage', 'display', 'export', 'external_ai'}


def check(condition, message):
    if not condition:
        raise StoreError(message)


def strictest(left, right):
    return {key: max((left[key], right[key]), key=RANK.get) for key in PURPOSES}


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(connection):
    check([row[0] for row in connection.execute('PRAGMA integrity_check')] == ['ok'], 'SQLite integrity check failed.')
    check(not connection.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign key check failed.')


def restriction_state(connection):
    policies = {row['id']: json.loads(row['rights']) for row in connection.execute('SELECT id, rights FROM source_policies ORDER BY id')}
    for rights in policies.values():
        check(isinstance(rights, dict) and set(rights) == PURPOSES and all(value in RANK for value in rights.values()), 'Invalid current source policy.')
        check(rights['storage'] == 'allowed', 'Unsupported storage policy.')
    withdrawn = [row[0] for row in connection.execute('SELECT id FROM withdrawals ORDER BY id')]
    return {'policies': policies, 'withdrawn_ids': withdrawn}


def verify_connection(connection, kind='archive'):
    integrity(connection)
    if kind == 'feedback':
        count = 0
        for row in connection.execute('SELECT id, received_at, content_hash, payload, status FROM feedback'):
            payload = feedback_payload(json.loads(row['payload']))
            check(row['id'] == payload['request_id'] and row['status'] in ('open', 'resolved'), 'Invalid feedback identity or status.')
            check(type(row['received_at']) is int and row['received_at'] >= 0, 'Invalid feedback timestamp.')
            check(hashlib.sha256(canonical_json(payload).encode()).hexdigest() == row['content_hash'], 'Feedback integrity mismatch.')
            count += 1
        return {'kind': kind, 'feedback_count': count}
    ensure_schema(connection)
    snapshots = [row[0] for row in connection.execute('SELECT id FROM snapshots ORDER BY id')]
    check(bool(snapshots), 'Empty archive.')
    active = read_snapshot(connection)['snapshot_id']
    # Verify every immutable snapshot, including inactive versions and their hashes.
    for snapshot in snapshots:
        read_snapshot(connection, snapshot)
    check(not connection.execute('SELECT 1 FROM records r JOIN identities i ON i.id=r.id WHERE r.collection != i.collection LIMIT 1').fetchone(), 'Record collection mismatch.')
    state = restriction_state(connection)
    floor = {}
    for row in connection.execute("SELECT payload FROM records WHERE collection='sources'"):
        source = json.loads(row[0])
        floor[source['id']] = strictest(floor.get(source['id'], source['rights']), source['rights'])
    check(set(state['policies']) == set(floor), 'Missing or unrelated current source policies.')
    for identifier, rights in floor.items():
        check(strictest(state['policies'][identifier], rights) == state['policies'][identifier], 'Current policy would loosen imported restrictions.')
    for row in connection.execute('SELECT metadata FROM snapshots'):
        check(set(json.loads(row[0])['withdrawn_ids']) <= set(state['withdrawn_ids']), 'Current withdrawals omit an imported restriction.')
    return {'kind': kind, 'snapshots': snapshots, 'active_snapshot_id': active,
            'record_count': connection.execute('SELECT count(*) FROM records').fetchone()[0],
            'withdrawal_count': len(state['withdrawn_ids']),
            'restriction_hash': hashlib.sha256(canonical_json(state).encode()).hexdigest()}


def verify(database, kind='archive'):
    with closing(connect(database)) as connection:
        connection.execute('BEGIN')
        return verify_connection(connection, kind)


def audit(connection, action, detail):
    connection.execute('CREATE TABLE IF NOT EXISTS maintenance_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, action TEXT NOT NULL, detail TEXT NOT NULL)')
    identifier = str(uuid.uuid4())
    connection.execute('INSERT INTO maintenance_events(id, action, detail) VALUES (?, ?, ?)', (identifier, action, canonical_json(detail)))
    return identifier


def activate(database, snapshot, expected_active, reason):
    check(isinstance(reason, str) and 0 < len(reason.strip()) <= 500, 'An audit reason of 1–500 characters is required.')
    # mode=rw: a mistaken path must not create an empty database.
    path = Path(database).expanduser().resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        try:
            before = verify_connection(connection)
            check(before['active_snapshot_id'] == expected_active, 'Active snapshot changed; inspect state before retrying.')
            read_snapshot(connection, snapshot)
            if snapshot == expected_active:
                connection.rollback()
                return {'status': 'unchanged', **before}
            connection.execute('UPDATE archive_state SET active_snapshot_id=? WHERE singleton=1', (snapshot,))
            event = audit(connection, 'activate', {'from': expected_active, 'to': snapshot, 'reason': reason.strip(), 'restriction_hash': before['restriction_hash']})
            after = verify_connection(connection)
            check(before['restriction_hash'] == after['restriction_hash'], 'Activation changed restrictions.')
            connection.commit()
            return {'status': 'activated', 'event_id': event, **after}
        except Exception:
            connection.rollback()
            raise


def sqlite_copy(source, target):
    started = time.monotonic()
    def progress(status, remaining, total):
        check(time.monotonic() - started < 60, 'Backup exceeded 60 seconds; retry when writers are idle.')
    with closing(connect(source)) as reader, closing(sqlite3.connect(target)) as writer:
        reader.backup(writer, pages=256, progress=progress, sleep=0.05)


def publish_new(source, destination):
    # Same-filesystem hard link gives exclusive publication: never replace a file,
    # symlink or racing writer's output. The staged file is already closed/verified.
    with open(source, 'rb') as stream:
        os.fsync(stream.fileno())
    os.link(source, destination)
    directory = os.open(Path(destination).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def copy_database(source, destination, kind='archive', current_database=None, expected_sha256=None):
    restoring = current_database is not None
    check(not restoring or kind == 'archive', 'Restriction merge only applies to archive databases.')
    destination = Path(destination).expanduser().absolute()
    check(not destination.exists() and not destination.is_symlink(), 'Destination already exists; refusing to overwrite.')
    check(not any(Path(str(destination) + suffix).exists() or Path(str(destination) + suffix).is_symlink()
                  for suffix in ('-wal', '-shm', '-journal')), 'Destination has SQLite sidecars.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.archive-stage-', dir=destination.parent) as directory:
        staged = Path(directory) / 'archive.sqlite3'
        staged.touch(mode=0o600)
        sqlite_copy(source, staged)
        verify(staged, kind)
        # Hash refers to the verified SQLite copy, not an unsafe raw copy of a WAL database.
        source_hash = digest_file(staged)
        if expected_sha256 is not None:
            check(source_hash == expected_sha256, 'Backup SHA-256 mismatch.')
        event = None
        if restoring:
            with closing(connect(current_database)) as current, closing(connect(staged, writable=True)) as target:
                current.execute('BEGIN')
                current_summary = verify_connection(current)
                restrictions = restriction_state(current)
                target.execute('BEGIN IMMEDIATE')
                target_hashes = dict(target.execute('SELECT id, content_hash FROM snapshots'))
                for row in current.execute('SELECT id, content_hash FROM snapshots'):
                    check(row['id'] not in target_hashes or target_hashes[row['id']] == row['content_hash'], 'Same snapshot ID has different content across recovery inputs.')
                identities = {row['id']: row['collection'] for row in target.execute('SELECT id, collection FROM identities')}
                current_ids = {row['id']: row['collection'] for row in current.execute('SELECT id, collection FROM identities')}
                for identifier in identities.keys() & current_ids.keys():
                    check(identities[identifier] == current_ids[identifier], 'Stable identity changed collection across recovery inputs.')
                check(set(restrictions['withdrawn_ids']) <= identities.keys(), 'Backup predates withdrawn identities; use a newer recovery point instead of losing restrictions.')
                for identifier, rights in restrictions['policies'].items():
                    previous = target.execute('SELECT rights FROM source_policies WHERE id=?', (identifier,)).fetchone()
                    check(previous is not None or all(value == 'allowed' for value in rights.values()), 'Backup predates restricted sources; use a newer recovery point.')
                    if previous:
                        target.execute('UPDATE source_policies SET rights=? WHERE id=?', (canonical_json(strictest(json.loads(previous[0]), rights)), identifier))
                for identifier in restrictions['withdrawn_ids']:
                    if identifier in identities:
                        # Original withdrawing batch may not exist in the old backup.
                        # Keep its provenance in the restore event; satisfy the local FK
                        # with a snapshot that actually contains this stable identity.
                        containing = target.execute('SELECT snapshot_id FROM records WHERE id=? ORDER BY snapshot_id LIMIT 1', (identifier,)).fetchone()[0]
                        target.execute('INSERT OR IGNORE INTO withdrawals(id, first_snapshot_id) VALUES (?, ?)', (identifier, containing))
                event = audit(target, 'restore', {'backup_sha256': source_hash, 'current_restriction_hash': current_summary['restriction_hash'],
                                                  'current_snapshots': current_summary['snapshots'],
                                                  'withdrawal_provenance': [dict(row) for row in current.execute('SELECT id, first_snapshot_id FROM withdrawals') if row['id'] in identities]})
                target.commit()
        after = verify(staged, kind)
        result = {'status': 'restored' if restoring else 'backed_up', **after, 'sha256': digest_file(staged), 'bytes': staged.stat().st_size}
        if restoring:
            result.update(event_id=event, backup_sha256=source_hash, restriction_state_as_of='supplied current database read transaction')
        publish_new(staged, destination)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('verify', 'backup'):
        command = sub.add_parser(name)
        command.add_argument('--database', type=Path, required=True)
        command.add_argument('--kind', choices=('archive', 'feedback'), default='archive')
        if name == 'backup':
            command.add_argument('--output', type=Path, required=True)
    command = sub.add_parser('restore')
    command.add_argument('--backup', type=Path, required=True)
    command.add_argument('--current-database', type=Path, required=True, help='Latest trustworthy archive or policy-containing recovery copy; never silently use old backup restrictions')
    command.add_argument('--output', type=Path, required=True)
    command.add_argument('--expected-sha256', required=True, help='SHA-256 returned by the backup command')
    command = sub.add_parser('activate')
    command.add_argument('--database', type=Path, required=True)
    command.add_argument('--snapshot', required=True)
    command.add_argument('--expect-active', required=True)
    command.add_argument('--reason', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            result = verify(args.database, args.kind)
        elif args.command == 'backup':
            result = copy_database(args.database, args.output, args.kind)
        elif args.command == 'restore':
            result = copy_database(args.backup, args.output, current_database=args.current_database, expected_sha256=args.expected_sha256)
        else:
            result = activate(args.database, args.snapshot, args.expect_active, args.reason)
        print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
