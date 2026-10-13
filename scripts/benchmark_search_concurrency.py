"""Concurrent synthetic cold searches: SQL/JSON costs and bounded read mapping."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from archive_store import import_snapshot, load_snapshot
from benchmark_archive import machine, summarize
from benchmark_boundaries import workload
from benchmark_search_misses import oracle_case, queries
import indexed_archive
from search_archive import normalize_text, search_options
from validate_sample import project


def query_groups(data):
    tail = normalize_text(data['passages'][32]['text'])
    end = tail.index('物资核对') + 4
    groups = {
        'mixed_new_queries': queries(30),
        'broad_prefixes': ['原创负载正文只供检索边界测试，不代表任何游戏资料。'[:13 + i] for i in range(10)],
        # Leading whitespace normalizes away: deduplicate AFTER normalization.
        'broad_suffixes': list(dict.fromkeys(normalize_text(tail[end - 4 - i:end]) for i in range(20)))[:10],
    }
    groups = {name: [normalize_text(q) for q in terms] for name, terms in groups.items()}
    all_queries = [q for group in groups.values() for q in group]
    assert len(all_queries) == len(set(all_queries)) == 50
    return groups


def run(database, mmap_bytes=None):
    data = load_snapshot(database)
    if data['dataset_kind'] != 'synthetic':
        raise ValueError('Synthetic databases only.')
    view = project(data, ['opening'])
    normalized = {p['id']: normalize_text(p['text']) for p in view['passages']}
    cases = {name: [oracle_case(view, q, normalized) for q in terms]
             for name, terms in query_groups(data).items()}
    snapshot = data['snapshot_id']
    del data, view, normalized
    original_connect = indexed_archive.connect
    original_get = indexed_archive._search_get
    original_put = indexed_archive._search_put
    original_loads = json.loads
    local = threading.local()

    def observed_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        if mmap_bytes is not None:
            connection.execute(f'PRAGMA mmap_size={mmap_bytes}')
        return connection

    def observed_get(key):
        result = original_get(key)
        local.metrics['cache_hits' if result is not None else 'cache_misses'] += 1
        return result

    def observed_put(key, value):
        local.metrics['cached_matches'] = len(value[0])
        # Shallow size excludes separately allocated Python strings/integers.
        local.metrics['cache_sequence_shallow_bytes'] = sys.getsizeof(value[0])
        local.metrics['cache_sequence_estimated_bytes'] = sys.getsizeof(value[0]) + (
            len(value[0]) * sys.getsizeof(value[0][0]) if isinstance(value[0], list) and value[0] else 0)
        return original_put(key, value)

    def observed_loads(value, *args, **kwargs):
        if value is not getattr(local, 'match_json', None):
            return original_loads(value, *args, **kwargs)
        start = time.perf_counter(); cpu = time.thread_time()
        result = original_loads(value, *args, **kwargs)
        local.metrics['match_json_wall_seconds'] += time.perf_counter() - start
        local.metrics['match_json_cpu_seconds'] += time.thread_time() - cpu
        local.match_json = None
        return result

    def observe_method(name):
        original = getattr(indexed_archive.IndexedArchive, name)

        def observed(archive, *args, **kwargs):
            if name == 'candidate_plan':
                phase = 'candidate'
            elif name == 'order_search_positions':
                # Inclusive of topology reads; do not sum with SQL phases.
                phase = 'order_positions_inclusive'
            elif 'instr(' in args[0]:
                phase = 'match_sql'
            elif name == 'passage_rows':
                phase = 'topology_or_page_sql'
            elif 'GROUP BY speaker' in args[0]:
                phase = 'facets_sql'
            else:
                phase = 'metadata_sql'
            start = time.perf_counter(); cpu = time.thread_time()
            result = original(archive, *args, **kwargs)
            local.metrics[phase + '_wall_seconds'] += time.perf_counter() - start
            local.metrics[phase + '_cpu_seconds'] += time.thread_time() - cpu
            if phase == 'candidate':
                local.metrics['candidate_kind'] = result['kind']
            elif phase == 'match_sql' and result and 'matches' in result[0].keys():
                local.match_json = result[0]['matches']
                local.metrics['match_json_characters'] = len(local.match_json)
            return result

        return observed

    def request(case):
        local.metrics = defaultdict(float)
        local.match_json = None
        start = time.perf_counter()
        with indexed_archive.indexed_view(database, snapshot, ['opening'], 'display') as archive:
            actual_mapping = archive.connection.execute('PRAGMA mmap_size').fetchone()
            result = archive.search(search_options({'q': [case['query']], 'limit': ['50']}), b'concurrency-probe')
        assert result['results'] == case['expected']
        assert result['pagination']['total'] == case['total']
        assert result['facets'] == case['facets'] and result['stats'] == case['stats']
        return {'ok': True, 'seconds': round(time.perf_counter() - start, 6), 'bytes': 0,
                'query': case['query'], 'mmap_bytes': actual_mapping[0] if actual_mapping else 0,
                'diagnostics': {k: round(v, 6) if isinstance(v, float) else v for k, v in local.metrics.items()}}

    report = {'dataset_kind': 'synthetic', 'environment': machine(), 'snapshot': snapshot,
              'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'implementation_sha256': hashlib.sha256(Path(indexed_archive.__file__).read_bytes()).hexdigest(),
              'requested_mmap_bytes': mmap_bytes, 'concurrency': 10,
              'limitations': ['Direct indexed_view/search calls, no HTTP; timing includes oracle assertions',
                  'Wall phases include scheduling/waiting; thread CPU is not a measurement of disk IO',
                  'Groups run sequentially and share topology/facets; result queries remain distinct',
                  'OS disk cache not flushed; profiling wrappers add overhead',
                  'Cache sequence shallow bytes exclude separate Python string/integer allocations',
                  'Estimated list footprint samples the first element size; packed arrays use their exact size',
                  'mmap_bytes reports the SQLite mapping limit, not mapped/resident physical memory',
                  'order_positions_inclusive overlaps topology SQL and must not be summed with it'],
              'scenarios': {}}
    with ExitStack() as stack:
        if mmap_bytes is not None and hasattr(indexed_archive, 'READ_MMAP_BYTES'):
            stack.enter_context(patch.object(indexed_archive, 'READ_MMAP_BYTES', mmap_bytes))
        for target, name, replacement in (
            (indexed_archive, 'connect', observed_connect),
            (indexed_archive, '_search_get', observed_get),
            (indexed_archive, '_search_put', observed_put),
            (json, 'loads', observed_loads),
        ):
            stack.enter_context(patch.object(target, name, replacement))
        for name in ('rows', 'passage_rows', 'candidate_plan', 'order_search_positions'):
            if hasattr(indexed_archive.IndexedArchive, name):
                stack.enter_context(patch.object(indexed_archive.IndexedArchive, name, observe_method(name)))
        for name, group in cases.items():
            with ThreadPoolExecutor(max_workers=10) as executor:
                rows = list(executor.map(request, group))
            summary = summarize(rows)
            summary['all_missed'] = all(row['diagnostics']['cache_misses'] == 1
                                        and not row['diagnostics'].get('cache_hits', 0) for row in rows)
            assert summary['all_missed']
            report['scenarios'][name] = summary
            print(name, summary['p95_seconds'], flush=True)
    report['all_correct'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--database', type=Path)
    source.add_argument('--count', type=int, default=100000)
    parser.add_argument('--mmap-bytes', type=int, choices=(0, 1073741824))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 200 <= args.count <= 100000:
        parser.error('Choose a new output and count 200–100000.')
    if args.database is not None:
        report = run(args.database, args.mmap_bytes)
    else:
        with tempfile.TemporaryDirectory(prefix='archive-concurrency-') as directory:
            database = Path(directory) / 'archive.sqlite3'
            data, _ = workload('long', args.count)
            import_snapshot(data, database)
            del data
            report = run(database, args.mmap_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(args.output)


if __name__ == '__main__':
    main()
