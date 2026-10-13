"""Deterministic HTTP drill for restrictions committed while readers are in flight."""
import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_archive import AIArchive
from archive_store import connect, import_snapshot
from benchmark_archive import BenchServer, QuietHandler, synthetic_sample
from indexed_archive import IndexedArchive
from search_archive import search_options, search_view
from validate_sample import project


def run_case(journal, change, purpose, readers=10, rollback=False):
    data = synthetic_sample(300)
    snapshot = data['snapshot_id']
    secret = secrets.token_bytes(32)
    opts = search_options({'limit': ['50']})
    before = search_view(project(data, ['opening'], purpose), opts, secret)
    revised = deepcopy(data)
    if change == 'withdrawal':
        revised['withdrawn_ids'] = ['passage:03', 'passage:31']
    else:
        revised['sources'][0]['rights'][purpose] = 'denied'
    after = before if rollback else search_view(project(revised, ['opening'], purpose), opts, secret)
    entered = threading.Event(); release = threading.Event(); writer_staged = threading.Event()
    lock = threading.Lock(); entered_count = 0
    original_search = IndexedArchive.search

    def paused_search(archive, options, cursor_secret):
        nonlocal entered_count
        with lock:
            should_wait = entered_count < readers
            if should_wait:
                entered_count += 1
                if entered_count == readers:
                    entered.set()
        # __init__ has already read snapshot/policy_revision in this transaction.
        if should_wait and not release.wait(30):
            raise RuntimeError('Reader gate timed out')
        return original_search(archive, options, cursor_secret)

    with tempfile.TemporaryDirectory(prefix='archive-live-restrictions-') as directory:
        database = Path(directory) / 'archive.sqlite3'
        import_snapshot(data, database)
        with closing(connect(database, writable=True)) as connection:
            actual_journal = connection.execute(f'PRAGMA journal_mode={journal}').fetchone()[0]
        assert actual_journal == journal.lower()
        server = BenchServer(('127.0.0.1', 0), QuietHandler)
        server.database = database; server.cursor_secret = secret
        server.ai_archive = AIArchive(database, snapshot, ['opening'], secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request(path='/api/search', **parameters):
            if purpose == 'external_ai' and path in ('/api/search', '/api/relationship') and 'purpose' not in parameters:
                tool = 'search_texts' if path == '/api/search' else 'get_relationship'
                body = {'name': tool, 'arguments': parameters}
                req = Request(base + '/api/ai-tools', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            else:
                req = Request(base + path + '?' + urlencode({'scope': 'opening', 'purpose': purpose,
                    'snapshot': snapshot, **parameters}))
            try:
                response = urlopen(req, timeout=30)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        def compare(response, expected):
            status, body = response
            assert status == 200, f'Unexpected status {status}'
            for key in ('snapshot_id', 'scope_ids', 'purpose', 'results', 'stats', 'facets', 'entries', 'characters'):
                assert body[key] == expected[key], f'Inconsistent {key}'
            for key in ('total', 'offset', 'limit', 'pages'):
                assert body['pagination'][key] == expected['pagination'][key], f'Inconsistent pagination {key}'

        def write_restriction():
            with closing(connect(database, writable=True)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                if change == 'withdrawal':
                    connection.executemany('INSERT INTO withdrawals VALUES(?,?)',
                        [(identifier, snapshot) for identifier in ('passage:03', 'passage:31')])
                else:
                    connection.execute('UPDATE source_policies SET rights=? WHERE id=?',
                        (json.dumps(revised['sources'][0]['rights']), revised['sources'][0]['id']))
                writer_staged.set()
                if rollback:
                    connection.rollback()
                else:
                    connection.commit()

        try:
            initial = request(limit=50)
            compare(initial, before)
            cursor = initial[1]['pagination']['next_cursor']
            assert cursor
            with ThreadPoolExecutor(max_workers=readers + 1) as executor:
                with patch.object(IndexedArchive, 'search', paused_search):
                    pending = [executor.submit(request, limit=50) for _ in range(readers)]
                    try:
                        assert entered.wait(15), 'Readers did not all acquire their read transactions'
                        writer = executor.submit(write_restriction)
                        assert writer_staged.wait(10), 'Writer did not stage restrictions'
                        blocked = False
                        if journal == 'DELETE' and not rollback:
                            try:
                                writer.result(timeout=.1)
                            except TimeoutError:
                                blocked = True
                            assert blocked, 'Default journal commit should wait for pinned readers'
                            release.set()
                        writer.result(timeout=10)
                        # In WAL mode this request happens after commit while all
                        # old requests are still paused. It must use the new policy.
                        fresh = request(limit=50)
                        compare(fresh, after)
                        continuation_status = request(limit=50, cursor=cursor)[0]
                        assert continuation_status == (200 if rollback else 409), 'Wrong cursor lifecycle'
                        relation_status = request('/api/relationship', id='relation:mentor')[0]
                        assert relation_status == (200 if rollback else 404), 'Incomplete or denied evidence exposed'
                        if change == 'policy':
                            other = 'export' if purpose == 'display' else 'display'
                            unaffected = request(limit=50, purpose=other)
                            assert unaffected[0] == 200
                            assert unaffected[1]['pagination']['total'] == before['pagination']['total']
                    finally:
                        release.set()
                    for future in pending:
                        compare(future.result(timeout=15), before)
            return {'journal': actual_journal, 'change': change, 'purpose': purpose, 'rollback': rollback,
                    'readers': readers, 'all_checks_passed': True, 'writer_waited_for_readers': blocked,
                    'before_count': before['pagination']['total'], 'after_count': after['pagination']['total'],
                    'old_cursor_http_status': continuation_status, 'relationship_http_status': relation_status,
                    'inflight_requests': 'consistent pre-change transaction',
                    'fresh_requests': 'post-commit restrictions; rollback preserves old state'}
        finally:
            release.set()
            server.shutdown(); server.server_close(); thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new path.')
    report = {'dataset_kind': 'synthetic', 'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'method': 'Test-only gate after read transaction initialization; real HTTP and SQLite connections',
              'contract': 'A request observes one transaction. In-flight old responses are not cancelled by a later WAL commit.',
              'cases': []}
    for journal in ('DELETE', 'WAL'):
        for change in ('withdrawal', 'policy'):
            for purpose in ('display', 'export', 'external_ai'):
                result = run_case(journal, change, purpose)
                report['cases'].append(result)
                print(json.dumps(result), flush=True)
        for change in ('withdrawal', 'policy'):
            report['cases'].append(run_case(journal, change, 'display', rollback=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2); output.write('\n')
    print(args.output)


if __name__ == '__main__':
    main()
