"""Reproducible synthetic HTTP baseline; no production database or real story data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import resource
import secrets
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

from ai_archive import AIArchive
from archive_store import import_snapshot
from serve_prototype import PrototypeHandler
from validate_sample import validate

ROOT = Path(__file__).resolve().parents[1]


def synthetic_sample(count):
    if count < 32:
        raise ValueError('At least 32 passages are required.')
    data = json.loads((ROOT / 'data/samples/story.json').read_text())
    snapshot = f'benchmark-synthetic-{count}-v1'
    data['snapshot_id'] = snapshot
    for collection in ('sources', 'entries', 'characters', 'passages', 'relationships'):
        for record in data[collection]:
            record['snapshot_id'] = snapshot
    data['notice'] = '原创合成性能测试数据，不是原神剧情；重复生成的负载不可用于准确性评测。'
    # Keep the original fixture's branches/rights/relationships, then add lawful
    # independent occurrences. Three query selectivities are known exactly.
    template = data['passages'][0]
    for index in range(32, count):
        data['passages'].append({**template, 'id': f'passage:bench-{index:06}',
                                 'text': f'原创性能演练 物资核对 组号{index % 100:02} 序号{index:06}',
                                 'source_locator': f'data/samples/story.json#/passages/{index}',
                                 'next_ids': []})
    # A 61-node star forces graph continuation at the existing 50-node cap.
    for index in range(60):
        identifier = f'person:bench-{index:03}'
        data['characters'].append({**data['characters'][1], 'id': identifier, 'name': f'合成负载人物{index}'})
        data['relationships'].append({**data['relationships'][1], 'id': f'relation:bench-{index:03}',
                                      'from_id': 'person:student', 'to_id': identifier})
    validate(data)
    return data


class QuietHandler(PrototypeHandler):
    def log_message(self, message, *arguments):
        pass


class BenchServer(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(rows):
    successes = [row['seconds'] for row in rows if row['ok']]
    return {'requests': len(rows), 'errors': len(rows) - len(successes),
            'p50_seconds': round(statistics.median(successes), 4) if successes else None,
            'p95_seconds': round(percentile(successes, .95), 4) if successes else None,
            'max_seconds': round(max(successes), 4) if successes else None,
            'response_bytes_max': max(row['bytes'] for row in rows), 'samples': rows}


def machine():
    result = {'os': platform.platform(), 'architecture': platform.machine(), 'python': platform.python_version(),
              'sqlite': sqlite3.sqlite_version, 'logical_cpus': os.cpu_count()}
    if sys.platform == 'darwin':
        for key, field in [('machdep.cpu.brand_string', 'cpu'), ('hw.memsize', 'memory_bytes')]:
            result[field] = subprocess.check_output(['sysctl', '-n', key], text=True).strip()
    return result


def run(count=100000, concurrency=10, requests=30):
    data = synthetic_sample(count)
    report = {'dataset_kind': 'synthetic', 'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'environment': machine(), 'network': 'HTTP over loopback; server and client in same Python process',
              'storage': 'SQLite query indexes; shared dependency checks, fused text/count/facet scan, sparse topology page merge; no FTS or result cache',
              'scope_ids': ['opening'], 'passages': count, 'concurrency': concurrency, 'requests_per_warm_scenario': requests,
              'cold_definition': 'First application request; OS disk cache is NOT flushed',
              'latency_definition': 'Client start to full body read and JSON parse; errors are recorded separately',
              'limitations': ['Short synthetic passages and small star graph; not representative real text or browser layout',
                             'Small local baseline, not a production load or availability certification']}
    with tempfile.TemporaryDirectory(prefix='yuanshen-benchmark-') as directory:
        database = Path(directory) / 'archive.sqlite3'
        started = time.perf_counter(); import_snapshot(data, database)
        report['import_seconds'] = round(time.perf_counter() - started, 4)
        report['database_bytes'] = database.stat().st_size
        server = BenchServer(('127.0.0.1', 0), QuietHandler)
        server.database = database; server.cursor_secret = secrets.token_bytes(32)
        server.ai_archive = AIArchive(database, None, ['opening'], server.cursor_secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        snapshot = data['snapshot_id']
        expected_broad = count - 32
        def request_one(kind, index):
            from urllib.parse import urlencode
            started = time.perf_counter(); size = 0
            try:
                if kind == 'ai_passage':
                    request = Request(base + '/api/ai-tools', data=json.dumps({'name': 'get_passage', 'arguments': {'id': 'passage:03', 'radius': 1}}).encode(), headers={'Content-Type': 'application/json'})
                else:
                    params = {'scope': 'opening', 'snapshot': snapshot}
                    if kind == 'search':
                        query = ['物资核对', '组号07', '不存在的负载词'][index % 3]
                        params.update(q=query, limit=8)
                        endpoint = 'search'
                    else:
                        endpoint = 'graph'; params.update(center='person:student', hops=1)
                    request = Request(base + f'/api/{endpoint}?' + urlencode(params))
                with urlopen(request, timeout=120) as response:
                    raw = response.read(); size = len(raw); result = json.loads(raw)
                assert result['snapshot_id'] == snapshot
                assert result['scope_ids'] == ['opening']
                if kind == 'search':
                    expected = [expected_broad, len(range(107, count, 100)), 0][index % 3]
                    assert result['pagination']['total'] == expected, (result['pagination']['total'], expected)
                    assert len(result['results']) <= 8
                    positions = [range(32, min(count, 40)), range(107, min(count, 907), 100), []][index % 3]
                    assert [row['id'] for row in result['results']] == [f'passage:bench-{position:06}' for position in positions]
                elif kind == 'graph':
                    assert len(result['characters']) <= 50 and len(result['relationships']) <= 100
                    assert result['truncated']
                else:
                    assert result['purpose'] == 'external_ai' and result['target_id'] == 'passage:03'
                return {'ok': True, 'seconds': round(time.perf_counter()-started, 4), 'bytes': size,
                        **({'query': query} if kind == 'search' else {})}
            except Exception as error:
                return {'ok': False, 'seconds': round(time.perf_counter()-started, 4), 'bytes': size,
                        'error': f'{type(error).__name__}: {error}',
                        **({'query': query} if kind == 'search' else {})}
        try:
            report['first_search'] = request_one('search', 0)
            print(json.dumps({'phase': 'first_search', **report['first_search']}), file=sys.stderr, flush=True)
            for kind in ('search', 'graph', 'ai_passage'):
                request_one(kind, 0)  # Warmup is deliberately excluded from reported percentiles.
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    rows = list(executor.map(lambda index: request_one(kind, index), range(requests)))
                report[kind] = summarize(rows)
                if kind == 'search':
                    report['search_by_query'] = {query: {key: value for key, value in
                        summarize([row for row in rows if row.get('query') == query]).items() if key != 'samples'}
                        for query in ('物资核对', '组号07', '不存在的负载词')
                        if any(row.get('query') == query for row in rows)}
                print(json.dumps({'phase': kind, **{key: value for key, value in report[kind].items() if key != 'samples'}}), file=sys.stderr, flush=True)
            report['service_targets'] = {kind: report[kind]['errors'] == 0 and report[kind]['p95_seconds'] <= 1 for kind in ('search', 'graph')}
            # Idempotent import under concurrent requests; no active version change.
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(request_one, 'search', 1)
                started = time.perf_counter(); imported = import_snapshot(data, database)
                report['during_idempotent_import'] = {'status': imported['status'], 'import_seconds': round(time.perf_counter()-started, 4), 'query': pending.result()}
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['peak_rss_bytes'] = peak if sys.platform == 'darwin' else peak * 1024
        finally:
            server.shutdown(); server.server_close(); thread.join()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--passages', type=int, default=100000)
    parser.add_argument('--concurrency', type=int, default=10)
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 32 <= args.passages <= 100000 or not 1 <= args.concurrency <= 10 or not 3 <= args.requests <= 100:
        parser.error('Supported bounds: passages 32–100000, concurrency 1–10, requests 3–100.')
    if args.output.exists():
        parser.error('Output exists; choose a new report path.')
    report = run(args.passages, args.concurrency, args.requests)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2); output.write('\n')
    print(args.output)


if __name__ == '__main__':
    main()
