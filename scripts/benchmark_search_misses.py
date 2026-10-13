"""Synthetic HTTP searches that verify result-cache misses, without clearing caches."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from archive_store import connect, import_snapshot
from benchmark_archive import BenchServer, QuietHandler, machine, summarize
from benchmark_boundaries import workload
import indexed_archive
from search_archive import normalize_text, ordered_passages
from validate_sample import project


def queries(count):
    # High/low/zero selectivity; each query string is new to the result cache.
    broad = '原创负载正文只供检索边界测试，不代表任何游戏资料。'
    return [broad[:3 + index // 3] if index % 3 == 0 else
            f'组号{index // 3:02}' if index % 3 == 1 else
            f'不存在的负载词{index:02}' for index in range(count)]


def oracle_case(view, query, normalized):
    ordered = ordered_passages(view['passages'])
    matches = [p for p in ordered if query in normalized[p['id']]]
    speakers = Counter(p['speaker_id'] or 'narration' for p in ordered)
    return {'query': query, 'expected': matches[:50], 'total': len(matches),
            'stats': {key: len(view[key]) for key in ('passages', 'characters', 'relationships')},
            'facets': {'categories': [{'value': 'quest', 'count': len(ordered)}] if ordered else [],
                       'speakers': [{'value': key, 'count': value} for key, value in sorted(speakers.items())]}}


def run(count=100000, requests=30, concurrency=10):
    data, spec = workload('long', count)
    snapshot = data['snapshot_id']
    view = project(data, ['opening'])
    normalized = {p['id']: normalize_text(p['text']) for p in view['passages']}
    fresh = [oracle_case(view, q, normalized) for q in queries(requests)]
    rotation = [oracle_case(view, f'组号{80 + index:02}', normalized) for index in range(8)]
    broad = oracle_case(view, '物资核对', normalized)
    restrictions = []
    # These appended passages have no links or relation evidence. Full projection
    # still recomputes the oracle after each cumulative withdrawal, outside timing.
    for index in range(requests):
        identifier = f'passage:bench-{32 + index:06}'
        data['withdrawn_ids'].append(identifier)
        restrictions.append((identifier, oracle_case(project(data, ['opening']), '物资核对', normalized)))
    data['withdrawn_ids'] = data['withdrawn_ids'][:-requests]
    report = {'dataset_kind': 'synthetic', 'workload': spec, 'environment': machine(),
              'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'implementation_sha256': hashlib.sha256(Path(indexed_archive.__file__).read_bytes()).hexdigest(),
              'network': 'Loopback HTTP; client and server share one Python process',
              'latency_definition': 'Full HTTP body read, JSON parse and oracle assertions; setup and writes excluded',
              'limitations': ['Synthetic data only; not production or real-story acceptance',
                  'OS disk cache is not flushed; topology caches may be warm',
                  'Only new_queries is concurrent; eviction and withdrawal are sequential to guarantee misses',
                  'Withdrawal timing excludes writer latency; concurrent policy changes have separate regression tests'],
              'scenarios': {}}
    with tempfile.TemporaryDirectory(prefix='archive-search-misses-') as directory:
        database = Path(directory) / 'archive.sqlite3'
        started = time.perf_counter(); import_snapshot(data, database)
        report['import_seconds'] = round(time.perf_counter() - started, 4)
        report['database_bytes'] = database.stat().st_size
        del data, view, normalized
        gc.collect()
        server = BenchServer(('127.0.0.1', 0), QuietHandler)
        server.database = database; server.cursor_secret = secrets.token_bytes(32)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}/api/search'
        cache_counts = Counter()
        lock = threading.Lock()
        original_get = indexed_archive._search_get

        def observed_get(key):
            value = original_get(key)
            with lock:
                cache_counts['hits' if value is not None else 'misses'] += 1
            return value

        def request_one(case):
            started = time.perf_counter(); size = 0
            try:
                url = base + '?' + urlencode({'q': case['query'], 'scope': 'opening', 'snapshot': snapshot, 'limit': 50})
                with urlopen(url, timeout=120) as response:
                    raw = response.read(); size = len(raw); result = json.loads(raw)
                assert result['snapshot_id'] == snapshot and result['scope_ids'] == ['opening']
                assert result['purpose'] == 'display'
                assert result['results'] == case['expected'], 'text/order/visible links mismatch'
                assert result['pagination']['total'] == case['total'] and result['pagination']['offset'] == 0
                assert result['stats'] == case['stats'] and result['facets'] == case['facets'], 'stats/facets mismatch'
                return {'ok': True, 'seconds': round(time.perf_counter() - started, 4), 'bytes': size, 'query': case['query']}
            except Exception as error:
                if isinstance(error, HTTPError):
                    error.close()
                return {'ok': False, 'seconds': round(time.perf_counter() - started, 4), 'bytes': size,
                        'query': case['query'], 'error': f'{type(error).__name__}: {error}'}

        def record(name, rows, concurrent):
            result = {**summarize(rows), 'concurrency': concurrent,
                      'cache_hits': cache_counts['hits'], 'cache_misses': cache_counts['misses']}
            result['all_missed'] = result['cache_hits'] == 0 and result['cache_misses'] == len(rows)
            result['within_one_second'] = result['errors'] == 0 and result['p95_seconds'] <= 1
            report['scenarios'][name] = result
            print(json.dumps({'scenario': name, **{k: v for k, v in result.items() if k != 'samples'}}), flush=True)
            cache_counts.clear()

        try:
            with patch.object(indexed_archive, '_search_get', observed_get):
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    rows = list(executor.map(request_one, fresh))
                record('new_queries', rows, concurrency)
                # At least two complete cycles exceed the six-entry result cache.
                record('rotating_eight_queries', [request_one(rotation[i % 8]) for i in range(max(16, requests))], 1)
                report['before_withdrawal'] = request_one(broad)
                cache_counts.clear()
                rows = []
                for identifier, case in restrictions:
                    with closing(connect(database, writable=True)) as connection:
                        connection.execute('INSERT INTO withdrawals VALUES (?,?)', (identifier, snapshot))
                    rows.append(request_one(case))
                record('after_withdrawal', rows, 1)
        finally:
            server.shutdown(); server.server_close(); thread.join()
    report['all_correct'] = report['before_withdrawal']['ok'] and all(
        s['errors'] == 0 and s['all_missed'] for s in report['scenarios'].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=100000)
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--concurrency', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 200 <= args.count <= 100000 or not 3 <= args.requests <= 30 or not 1 <= args.concurrency <= 10:
        parser.error('Bounds: count 200–100000, requests 3–30, concurrency 1–10.')
    if args.output.exists():
        parser.error('Output exists; choose a new path.')
    result = run(args.count, args.requests, args.concurrency)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(result, output, ensure_ascii=False, indent=2); output.write('\n')
    print(args.output)
    if not result['all_correct']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
