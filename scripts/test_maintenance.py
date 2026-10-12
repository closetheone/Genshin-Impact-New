from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
from http.server import ThreadingHTTPServer
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from urllib.request import urlopen

from archive_store import StoreError, connect, import_snapshot, load_snapshot
from feedback_store import submit_feedback, read_feedback
from maintain_archive import activate, copy_database, digest_file, verify
from material_archive import material_view, selection_request
from serve_prototype import PrototypeHandler
from test_graph_archive import SAMPLE, next_snapshot
from validate_sample import project

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.database = self.directory / 'archive.sqlite3'
        import_snapshot(SAMPLE, self.database)
        self.backup = self.directory / 'backup.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def backup_now(self):
        return copy_database(self.database, self.backup)

    def restricted(self):
        data = next_snapshot(SAMPLE, 'restricted-v2')
        data['withdrawn_ids'] = ['passage:03', 'passage:31']
        data['sources'][0]['rights']['external_ai'] = 'denied'
        import_snapshot(data, self.database, activate=True)
        return data

    def test_online_wal_backup_contains_committed_state(self):
        with closing(connect(self.database, writable=True)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            self.restricted()
            writer.execute('UPDATE archive_state SET active_snapshot_id=active_snapshot_id')
            # Keep the WAL-owning connection open during backup.
            self.assertTrue(Path(str(self.database) + '-wal').exists())
            result = self.backup_now()
            self.assertEqual(result['active_snapshot_id'], 'restricted-v2')
            self.assertEqual(load_snapshot(self.backup), load_snapshot(self.database))
            self.assertEqual(result['sha256'], digest_file(self.backup))
            self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
            restored = self.directory / 'wal-restored.sqlite3'
            copy_database(self.backup, restored, current_database=self.database, expected_sha256=result['sha256'])
            self.assertEqual(load_snapshot(restored), load_snapshot(self.database))

    def test_restore_preserves_newer_withdrawals_and_policies(self):
        backup = self.backup_now(); self.restricted()
        current_hash = digest_file(self.database)
        restored = self.directory / 'restored.sqlite3'
        result = copy_database(self.backup, restored, current_database=self.database, expected_sha256=backup['sha256'])
        self.assertEqual(result['status'], 'restored')
        self.assertEqual(result['active_snapshot_id'], SAMPLE['snapshot_id'])
        restored_data = load_snapshot(restored)
        self.assertEqual(restored_data['withdrawn_ids'], ['passage:03', 'passage:31'])
        self.assertEqual(project(restored_data, ['opening'], 'external_ai')['passages'], [])
        self.assertNotIn('relation:mentor', [r['id'] for r in project(restored_data, ['opening'])['relationships']])
        self.assertEqual(digest_file(self.database), current_hash)
        self.assertEqual(digest_file(self.backup), backup['sha256'])
        # Restoring original content must not resurrect pinned evidence exports.
        result = material_view(restored_data, selection_request({'snapshot': SAMPLE['snapshot_id'], 'scope_ids': ['opening'],
                               'relationships': [{'id': 'relation:mentor', 'evidence_ids': ['passage:03', 'passage:04']}]}))
        self.assertFalse(result['valid'])
        with closing(connect(restored)) as connection:
            event = json.loads(connection.execute("SELECT detail FROM maintenance_events WHERE action='restore'").fetchone()[0])
            self.assertEqual(event['withdrawal_provenance'][0]['first_snapshot_id'], 'restricted-v2')
        import_snapshot(SAMPLE, restored, activate=True)
        self.assertEqual(load_snapshot(restored)['withdrawn_ids'], ['passage:03', 'passage:31'])

    def test_restore_union_keeps_backup_stricter_restrictions(self):
        self.restricted(); backup = self.backup_now()
        older = self.directory / 'older.sqlite3'; import_snapshot(SAMPLE, older)
        output = self.directory / 'restored.sqlite3'
        copy_database(self.backup, output, current_database=older, expected_sha256=backup['sha256'])
        self.assertEqual(load_snapshot(output)['withdrawn_ids'], ['passage:03', 'passage:31'])
        self.assertEqual(load_snapshot(output)['sources'][0]['rights']['external_ai'], 'denied')

    def test_damaged_primary_recovery_from_known_good_copy_and_http_restart(self):
        backup = self.backup_now(); self.restricted()
        policies = self.directory / 'latest-trustworthy.sqlite3'
        copy_database(self.database, policies)
        self.database.write_bytes(b'broken primary database')
        restored = self.directory / 'recovered.sqlite3'
        copy_database(self.backup, restored, current_database=policies, expected_sha256=backup['sha256'])
        server = ThreadingHTTPServer(('127.0.0.1', 0), PrototypeHandler)
        server.database = restored; server.cursor_secret = b'restart-for-recovery'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/api/view?scope=opening&snapshot={SAMPLE["snapshot_id"]}') as response:
                view = json.load(response)
            self.assertEqual(view['snapshot_id'], SAMPLE['snapshot_id'])
            self.assertIn('passage:04', [p['id'] for p in view['passages']])
            self.assertNotIn('passage:03', [p['id'] for p in view['passages']])
            self.assertNotIn('relation:mentor', [r['id'] for r in view['relationships']])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_restore_hash_and_current_corruption_fail_without_output(self):
        backup = self.backup_now(); target = self.directory / 'failed.sqlite3'
        with self.assertRaisesRegex(StoreError, 'SHA-256'):
            copy_database(self.backup, target, current_database=self.database, expected_sha256='0' * 64)
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute("UPDATE records SET payload='{}' WHERE id='passage:03'")
        with self.assertRaises((StoreError, ValueError, KeyError)):
            copy_database(self.backup, target, current_database=self.database, expected_sha256=backup['sha256'])
        self.assertFalse(target.exists())
        self.assertFalse(list(self.directory.glob('.archive-stage-*')))

    def test_recovery_rejects_withdrawn_identity_newer_than_backup(self):
        backup = self.backup_now(); data = next_snapshot(SAMPLE, 'new-identity-v2')
        data['passages'].append({**data['passages'][0], 'id': 'passage:new', 'source_locator': 'data/samples/story.json#/passages/32', 'next_ids': []})
        data['withdrawn_ids'] = ['passage:new']; import_snapshot(data, self.database)
        target = self.directory / 'failed.sqlite3'
        with self.assertRaisesRegex(StoreError, 'predates withdrawn identities'):
            copy_database(self.backup, target, current_database=self.database, expected_sha256=backup['sha256'])
        self.assertFalse(target.exists())

    def test_recovery_rejects_restricted_source_newer_than_backup(self):
        backup = self.backup_now(); data = next_snapshot(SAMPLE, 'new-source-v2')
        source = deepcopy(data['sources'][0]); source['id'] = 'source:new'; source['rights']['external_ai'] = 'denied'
        data['sources'].append(source); import_snapshot(data, self.database)
        with self.assertRaisesRegex(StoreError, 'predates restricted sources'):
            copy_database(self.backup, self.directory / 'failed.sqlite3', current_database=self.database, expected_sha256=backup['sha256'])

    def test_recovery_rejects_same_snapshot_with_different_content(self):
        backup = self.backup_now()
        divergent = self.directory / 'divergent.sqlite3'
        data = deepcopy(SAMPLE); data['passages'][0]['text'] = '另一份原创样例'
        import_snapshot(data, divergent)
        with self.assertRaisesRegex(StoreError, 'different content'):
            copy_database(self.backup, self.directory / 'failed.sqlite3', current_database=divergent, expected_sha256=backup['sha256'])

    def test_activation_rollback_preserves_restrictions_and_records_audit(self):
        self.restricted(); before = verify(self.database)
        result = activate(self.database, SAMPLE['snapshot_id'], 'restricted-v2', '合成回滚演练')
        self.assertEqual(result['active_snapshot_id'], SAMPLE['snapshot_id'])
        self.assertEqual(result['restriction_hash'], before['restriction_hash'])
        self.assertEqual(result['record_count'], before['record_count'])
        self.assertEqual(activate(self.database, SAMPLE['snapshot_id'], SAMPLE['snapshot_id'], 'noop')['status'], 'unchanged')
        with closing(connect(self.database)) as connection:
            events = connection.execute('SELECT * FROM maintenance_events').fetchall()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0]['detail'])['reason'], '合成回滚演练')

    def test_activation_stale_expectation_and_failure_are_atomic(self):
        self.restricted(); before = verify(self.database)
        for snapshot, expectation in [(SAMPLE['snapshot_id'], 'stale'), ('missing', 'restricted-v2')]:
            with self.assertRaises(StoreError):
                activate(self.database, snapshot, expectation, 'should reject')
            self.assertEqual(verify(self.database), before)
        with patch('maintain_archive.audit', side_effect=sqlite3.OperationalError('simulated disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                activate(self.database, SAMPLE['snapshot_id'], 'restricted-v2', 'atomic failure')
        self.assertEqual(verify(self.database), before)

    def test_fault_import_rolls_back_partial_rows_and_activation(self):
        before = verify(self.database)
        data = next_snapshot(SAMPLE, 'fault-v2')
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute("CREATE TRIGGER simulated_full BEFORE INSERT ON records WHEN NEW.snapshot_id='fault-v2' AND NEW.id='passage:03' BEGIN SELECT RAISE(ABORT, 'simulated disk full'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            import_snapshot(data, self.database, activate=True)
        self.assertEqual(verify(self.database), before)
        self.assertEqual(import_snapshot(SAMPLE, self.database)['status'], 'unchanged')

    def test_active_reader_keeps_snapshot_during_activation(self):
        self.restricted()
        with closing(connect(self.database, writable=True)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            with closing(connect(self.database)) as reader:
                reader.execute('BEGIN')
                self.assertEqual(reader.execute('SELECT active_snapshot_id FROM archive_state').fetchone()[0], 'restricted-v2')
                activate(self.database, SAMPLE['snapshot_id'], 'restricted-v2', 'reader consistency')
                self.assertEqual(reader.execute('SELECT active_snapshot_id FROM archive_state').fetchone()[0], 'restricted-v2')
                reader.rollback()
                self.assertEqual(load_snapshot(self.database)['snapshot_id'], SAMPLE['snapshot_id'])

    def test_verify_rejects_inactive_corruption_and_loosened_policies(self):
        self.restricted()
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute("UPDATE source_policies SET rights=? WHERE id='source:fixture'", (json.dumps(SAMPLE['sources'][0]['rights']),))
        with self.assertRaisesRegex(StoreError, 'loosen'):
            verify(self.database)
        # Separate database for inactive payload corruption.
        other = self.directory / 'other.sqlite3'
        import_snapshot(SAMPLE, other); import_snapshot(next_snapshot(SAMPLE, 'clean-v2'), other, activate=True)
        with closing(connect(other, writable=True)) as connection:
            row = connection.execute("SELECT payload FROM records WHERE id='passage:03' AND snapshot_id=?", (SAMPLE['snapshot_id'],)).fetchone()
            payload = json.loads(row[0]); payload['text'] = 'tampered'
            connection.execute("UPDATE records SET payload=? WHERE id='passage:03' AND snapshot_id=?", (json.dumps(payload), SAMPLE['snapshot_id']))
        with self.assertRaisesRegex(StoreError, 'integrity'):
            verify(other)

    def test_existing_destination_symlink_and_partial_copy_preserve_data(self):
        self.backup.write_text('do not overwrite')
        with self.assertRaises(StoreError): self.backup_now()
        self.assertEqual(self.backup.read_text(), 'do not overwrite')
        link = self.directory / 'link.sqlite3'; link.symlink_to(self.backup)
        with self.assertRaises(StoreError): copy_database(self.database, link)
        target = self.directory / 'failed.sqlite3'; source_hash = digest_file(self.database)
        def fail(source, staged):
            Path(staged).write_bytes(b'partial'); raise OSError('disk full')
        with patch('maintain_archive.sqlite_copy', side_effect=fail), self.assertRaises(OSError):
            copy_database(self.database, target)
        self.assertFalse(target.exists()); self.assertEqual(digest_file(self.database), source_hash)
        self.assertFalse(list(self.directory.glob('.archive-stage-*')))

    def test_feedback_backup_is_private_and_restorable(self):
        inbox = self.directory / 'feedback.sqlite3'
        payload = {'request_id': str(uuid.uuid4()), 'kind': 'text', 'snapshot': SAMPLE['snapshot_id'], 'reference': 'passage:03',
                   'description': 'synthetic test', 'contact': 'synthetic@example.invalid'}
        submit_feedback(payload, inbox)
        result = copy_database(inbox, self.backup, kind='feedback')
        self.assertEqual(result['feedback_count'], 1)
        self.assertNotIn(payload['contact'], json.dumps(result))
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        restored = self.directory / 'restored-feedback.sqlite3'
        copy_database(self.backup, restored, kind='feedback')
        self.assertEqual(read_feedback(restored, True), read_feedback(inbox, True))
        with closing(connect(inbox, writable=True)) as connection:
            connection.execute("UPDATE feedback SET content_hash='invalid'")
        with self.assertRaises(StoreError): verify(inbox, 'feedback')

    def test_cli_failure_and_no_creation_of_wrong_path(self):
        missing = self.directory / 'missing.sqlite3'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/maintain_archive.py'), 'verify', '--database', str(missing)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stderr)['ok'])
        self.assertFalse(missing.exists())
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/maintain_archive.py'), 'backup', '--database', str(self.database), '--output', str(self.backup)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['sha256'], digest_file(self.backup))


if __name__ == '__main__':
    unittest.main()
