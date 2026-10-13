"""Synthetic long-text, linked-dialogue and deep-page HTTP boundary measurements."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
import resource
import secrets
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_archive import AIArchive
from archive_store import import_snapshot
from benchmark_archive import BenchServer, QuietHandler, machine, summarize, synthetic_sample
from graph_archive import graph_options, graph_view
from indexed_archive import indexed_view
from search_archive import encode_cursor, fingerprint, normalize_text, ordered_passages, search_options
from validate_sample import project, validate


PROFILES = {
    'long': {'passages': 100000, 'characters': 1024, 'fanout': 0},
    'linked': {'passages': 100000, 'characters': 96, 'fanout': 2},
    'deep': {'passages': 100000, 'characters': 96, 'fanout': 0},
    'combined': {'passages': 20000, 'characters': 1024, 'fanout': 2},
}


def workload(profile, count=None):
    spec = {**PROFILES[profile], **({'passages': count} if count is not None else {})}
    data = synthetic_sample(spec['passages'])
    snapshot = f"boundary-{profile}-{spec['passages']}-v1"
    data['snapshot_id'] = snapshot
    for collection in ('sources', 'entries', 'characters', 'passages', 'relationships'):
        for record in data[collection]:
            record['snapshot_id'] = snapshot
    # Search terms are at the END, forcing long-text misses and hits to scan.
    filler = '原创负载正文只供检索边界测试，不代表任何游戏资料。'
    for index in range(32, spec['passages']):
        suffix = f' 物资核对 组号{index % 100:02} 序号{index:06}'
        length = spec['characters'] - len(suffix)
        p = data['passages'][index]
        p['text'] = (filler * (length // len(filler) + 1))[:length] + suffix
        if spec['fanout'] and index % 10 == 0:
            p['required_scope_ids'] = ['opening', 'later']
    if spec['fanout']:
        # Swap adjacent source occurrences to produce backward edges. A chain
        # plus skip edges creates branching/rejoining, but never a directed cycle.
        sequence = []
        for start in range(32, spec['passages'], 2):
            sequence.extend(reversed(range(start, min(start + 2, spec['passages']))))
        for rank, index in enumerate(sequence):
            data['passages'][index]['next_ids'] = [data['passages'][sequence[next_rank]]['id']
                for next_rank in (rank + 1, rank + 4) if next_rank < len(sequence)]
    validate(data)
    return data, spec


def cases(data, secret, database):
    """Full-projection oracle, built outside timing and without indexed ordering."""
    view = project(data, ['opening'])
    ordered = ordered_passages(view['passages'])
    cases = []
    with indexed_view(database, data['snapshot_id'], ['opening'], 'display') as archive:
        for name, query, deep in [('broad_first', '物资核对', False), ('rare_tail', '组号07', False),
                                  ('missing_tail', '不存在的负载词', False), ('broad_deep', '物资核对', True)]:
            opts = search_options({'q': [query], 'limit': ['50']})
            matches = [p for p in ordered if query in normalize_text(p['text'])]
            offset = int(len(matches) * .9) // 50 * 50 if deep else 0
            query_fields = {k: v for k, v in opts.items() if k != 'cursor'}
            params = {'q': query, 'limit': 50}
            if offset:
                # A trusted benchmark seeds a valid deep-page cursor instead of
                # timing thousands of earlier pages. No client API is added.
                binding = fingerprint({'kind': 'indexed_search', 'query': query_fields, **archive.meta})
                params['cursor'] = encode_cursor(offset, binding, archive.revision, secret)
            cases.append({'name': name, 'path': '/api/search', 'params': params,
                          'collection': 'results', 'expected': matches[offset:offset + 50],
                          'total': len(matches), 'offset': offset, 'purpose': 'display'})
    target_position = int(len(ordered) * .9)
    offset = target_position // 50 * 50
    target = ordered[target_position]['id']
    cases.append({'name': 'reader_deep_target', 'path': '/api/read', 'params': {'id': target},
                  'collection': 'passages', 'expected': ordered[offset:offset + 50],
                  'target_id': target, 'total': len(ordered), 'offset': offset, 'purpose': 'display'})
    graph = graph_view(view, graph_options({'center': ['person:student']}), secret)
    cases.append({'name': 'graph', 'path': '/api/graph', 'params': {'center': 'person:student'},
                  'bundle': {k: graph[k] for k in ('characters', 'relationships', 'passages', 'entries')},
                  'purpose': 'display'})
    ai_view = project(data, ['opening'], 'external_ai')
    ai_ids = {p['id'] for p in ai_view['passages']}
    reached = {target}
    for p in ai_view['passages']:
        if p['id'] == target:
            reached.update(p['next_ids'])
        elif target in p['next_ids']:
            reached.add(p['id'])
    reached &= ai_ids
    assert len(reached) <= 20
    expected = [{**p, 'next_ids': [i for i in p['next_ids'] if i in reached]}
                for p in ai_view['passages'] if p['id'] in reached]
    cases.append({'name': 'ai_linked_neighbors', 'path': '/api/ai-tools',
                  'post': {'name': 'get_passage', 'arguments': {'id': target, 'radius': 1}},
                  'collection': 'passages', 'expected': expected, 'target_id': target,
                  'purpose': 'external_ai'})
    return cases, {'visible_passages': len(ordered), 'visible_links': sum(len(p['next_ids']) for p in ordered)}


def check_result(result, case, snapshot):
    assert result['snapshot_id'] == snapshot, 'snapshot mismatch'
    assert result['scope_ids'] == ['opening'], 'scope mismatch'
    assert result['purpose'] == case['purpose'], 'purpose mismatch'
    if 'collection' in case:
        assert result[case['collection']] == case['expected'], 'page text, order or visible connections differ from oracle'
        assert len(result[case['collection']]) <= 50, 'page exceeds limit'
    for key, expected in case.get('bundle', {}).items():
        assert result[key] == expected, f'graph {key} differs from oracle'
    if 'total' in case:
        assert result['pagination']['total'] == case['total'], 'count mismatch'
        assert result['pagination']['offset'] == case['offset'], 'offset mismatch'
    if 'target_id' in case:
        assert result['target_id'] == case['target_id'], 'wrong target'


def run(profile, concurrency=10, requests=30, count=None):
    data, spec = workload(profile, count)
    snapshot = data['snapshot_id']
    report = {'dataset_kind': 'synthetic', 'profile': profile, 'workload': spec,
              'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'environment': machine(), 'concurrency': concurrency, 'requests_per_scenario': requests,
              'network': 'Loopback HTTP, client and server share one Python process',
              'latency_definition': 'Client request start through full body read, JSON parse and oracle assertions',
              'deep_page_definition': '90% match offset; trusted harness signs cursor before timing; preceding page walk excluded',
              'limitations': ['Synthetic text, not real story accuracy or production certification',
                  'OS disk cache not flushed; first requests are not cold-disk tests',
                  'Combined profile intentionally uses 20000 passages to bound local memory; not a 100k acceptance test',
                  'Each scenario runs separately; P95 uses nearest rank; RSS includes fixture/oracle setup'],
              'scenarios': {}}
    with tempfile.TemporaryDirectory(prefix='archive-boundary-') as directory:
        database = Path(directory) / 'archive.sqlite3'
        started = time.perf_counter()
        import_snapshot(data, database)
        report['import_seconds'] = round(time.perf_counter() - started, 4)
        report['database_bytes'] = database.stat().st_size
        secret = secrets.token_bytes(32)
        plans, dimensions = cases(data, secret, database)
        report['workload'].update(dimensions)
        del data
        gc.collect()
        server = BenchServer(('127.0.0.1', 0), QuietHandler)
        server.database = database; server.cursor_secret = secret
        server.ai_archive = AIArchive(database, snapshot, ['opening'], secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request_one(case):
            started = time.perf_counter(); size = 0
            try:
                if 'post' in case:
                    request = Request(base + case['path'], data=json.dumps(case['post']).encode(),
                                      headers={'Content-Type': 'application/json'})
                else:
                    params = {'scope': 'opening', 'snapshot': snapshot, **case['params']}
                    request = Request(base + case['path'] + '?' + urlencode(params))
                with urlopen(request, timeout=120) as response:
                    raw = response.read(); size = len(raw); result = json.loads(raw)
                check_result(result, case, snapshot)
                return {'ok': True, 'seconds': round(time.perf_counter() - started, 4), 'bytes': size}
            except Exception as error:
                if isinstance(error, HTTPError):
                    error.close()
                return {'ok': False, 'seconds': round(time.perf_counter() - started, 4), 'bytes': size,
                        'error': f'{type(error).__name__}: {error}'}
        try:
            for case in plans:
                first = request_one(case)
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    rows = list(executor.map(lambda _: request_one(case), range(requests)))
                result = {'first_request': first, **summarize(rows)}
                if 'offset' in case:
                    result.update(offset=case['offset'], total=case['total'])
                result['within_one_second'] = result['errors'] == 0 and result['p95_seconds'] <= 1
                report['scenarios'][case['name']] = result
                print(json.dumps({'profile': profile, 'scenario': case['name'],
                    **{k: v for k, v in result.items() if k not in ('samples', 'first_request')}}), file=sys.stderr, flush=True)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['peak_rss_bytes'] = peak if sys.platform == 'darwin' else peak * 1024
    report['all_correct'] = all(r['errors'] == 0 and r['first_request']['ok'] for r in report['scenarios'].values())
    report['search_target_passed'] = all(report['scenarios'][n]['within_one_second']
        for n in ('broad_first', 'rare_tail', 'missing_tail', 'broad_deep'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--concurrency', type=int, default=10)
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--count', type=int, help='Override passage count for a smoke test; report records actual size')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 10 or not 3 <= args.requests <= 100 or (args.count is not None and not 200 <= args.count <= 100000):
        parser.error('Bounds: concurrency 1–10, requests 3–100, count 200–100000.')
    if args.output.exists():
        parser.error('Output exists; choose a new path.')
    report = run(args.profile, args.concurrency, args.requests, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2); output.write('\n')
    print(args.output)
    if not report['all_correct']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
