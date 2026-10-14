"""Cold application-cache visibility statistics on a synthetic diagnostic database."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

from archive_store import load_snapshot
from benchmark_archive import machine, summarize
import indexed_archive
import query_index
from search_archive import search_options, search_view
from validate_sample import project


def clear_caches():
    # Standalone benchmark only; never clear a running server's caches.
    with indexed_archive._TOPOLOGY_CACHE_LOCK:
        for name in ('_TOPOLOGY_CACHE', '_SEARCH_CACHE', '_PAGE_CACHE', '_TOTAL_CACHE'):
            getattr(indexed_archive, name).clear()


def run(database, repetitions=5):
    data = load_snapshot(database)
    assert data['dataset_kind'] == 'synthetic', 'Synthetic diagnostic databases only'
    view = project(data, ['opening'])
    expected_facets = [{'speaker': k, 'n': v} for k, v in sorted(
        Counter(p['speaker_id'] or 'narration' for p in view['passages']).items())]
    opts = search_options({'q': ['物资核对'], 'limit': ['50']})
    expected = search_view(view, opts, b'visibility-probe')
    report = {'dataset_kind': 'synthetic', 'snapshot': data['snapshot_id'],
              'passages': len(data['passages']), 'environment': machine(),
              'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'implementation_sha256': hashlib.sha256(Path(indexed_archive.__file__).read_bytes()).hexdigest(),
              'query_index_sha256': hashlib.sha256(Path(query_index.__file__).read_bytes()).hexdigest(),
              'limitations': ['Direct calls, no HTTP; oracle validation is outside timing',
                  'Application caches cleared before each round; OS disk cache is not flushed',
                  'Sequential rounds share OS caches; SQL plans captured outside timing',
                  'Concurrency exercises ten readers of the same visibility boundary'],
              'scenarios': {}}
    for name in ('facets', 'search', 'concurrent_facets'):
        samples = []
        for _ in range(repetitions):
            clear_caches()
            barrier = threading.Barrier(10) if name == 'concurrent_facets' else None

            def request(_=None):
                if barrier:
                    barrier.wait(timeout=30)
                start = time.perf_counter()
                with indexed_archive.indexed_view(database, data['snapshot_id'], ['opening'], 'display') as archive:
                    actual = archive.search(opts, b'visibility-probe') if name == 'search' else archive.search_facets()
                seconds = time.perf_counter() - start
                if name == 'search':
                    for key in ('results', 'facets', 'stats', 'characters', 'entries'):
                        assert actual[key] == expected[key], key
                    assert actual['pagination']['total'] == expected['pagination']['total']
                else:
                    assert actual == expected_facets
                return {'ok': True, 'seconds': round(seconds, 6), 'bytes': 0}

            if barrier:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    samples.extend(executor.map(request, range(10)))
            else:
                samples.append(request())
        report['scenarios'][name] = summarize(samples)
        print(name, report['scenarios'][name]['p95_seconds'], flush=True)

    clear_caches()
    with indexed_archive.indexed_view(database, data['snapshot_id'], ['opening'], 'display') as archive:
        def observe(original, cte):
            def read(sql, parameters=None):
                report['facets_query_plan'] = [row[3] for row in archive.connection.execute(
                    'EXPLAIN QUERY PLAN ' + cte + sql, {**archive.params, **(parameters or {})})]
                return original(sql, parameters)
            return read
        with patch.object(archive, 'rows', observe(archive.rows, archive.cte)), \
                patch.object(archive, 'passage_rows', observe(archive.passage_rows, archive.passages_cte)), \
                patch.object(archive, 'visibility_rows', observe(archive.visibility_rows, archive.visibility_cte)):
            assert archive.search_facets() == expected_facets
    report['all_correct'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=5)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.repetitions <= 30:
        parser.error('Choose a new output and 1–30 repetitions.')
    report = run(args.database, args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
