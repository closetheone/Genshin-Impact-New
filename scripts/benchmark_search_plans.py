"""Read-only synthetic search profiling and isolated FTS5 candidate experiments."""
import argparse
from collections import defaultdict
import cProfile
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from archive_store import import_snapshot
from benchmark_archive import machine
from benchmark_boundaries import workload
import indexed_archive
from indexed_archive import indexed_view
from query_index import build_candidates, install_candidates, trigrams
from search_archive import normalize_text, search_options


def timed(call):
    start = time.perf_counter()
    result = call()
    return result, round(time.perf_counter() - start, 6)


def profile_search(archive, query):
    phases = defaultdict(float)
    originals = {}
    for name in ('rows', 'passage_rows', 'candidate_plan'):
        original = getattr(archive, name)
        originals[name] = original

        def observed(*args, _method=original, _name=name, **kwargs):
            if _name == 'candidate_plan':
                phase = 'candidate_plan'
            elif 'instr(' in args[0]:
                phase = 'exact_match_sql'
            elif _name == 'passage_rows':
                phase = 'topology_sql'
            elif 'GROUP BY speaker' in args[0]:
                phase = 'facets_sql'
            else:
                phase = 'payload_and_metadata_sql'
            result, seconds = timed(lambda: _method(*args, **kwargs))
            phases[phase] += seconds
            return result

        setattr(archive, name, observed)
    profiler = cProfile.Profile()
    try:
        profiler.enable()
        result, total = timed(lambda: archive.search(search_options({'q': [query], 'limit': ['50']}), b'profile-only'))
        profiler.disable()
    finally:
        for name, original in originals.items():
            setattr(archive, name, original)
    sort = sum(entry.totaltime for entry in profiler.getstats()
               if isinstance(entry.code, str) and "'sort' of 'list'" in entry.code)
    phases['python_sort_including_keys'] = sort
    phases['other_python_and_cache'] = total - sum(phases.values())
    return {'query': query, 'matches': result['pagination']['total'], 'seconds': total,
            'phases_seconds': {k: round(v, 6) for k, v in phases.items()}}


def fts_experiment(texts):
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE TABLE text_rows(id INTEGER PRIMARY KEY, text TEXT)')
        connection.executemany('INSERT INTO text_rows(text) VALUES(?)', ((text,) for text in texts))
        connection.execute('CREATE TABLE query_snapshots(snapshot_id TEXT PRIMARY KEY, ready INTEGER)')
        install_candidates(connection)
        _, gram_build_seconds = timed(lambda: build_candidates(connection, {
            'snapshot_id': 'probe', 'passages': [{'text': text} for text in texts]}))
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='trigram case_sensitive 1')")
        except sqlite3.OperationalError as error:
            return {'available': False, 'reason': str(error)}
        _, build_seconds = timed(lambda: connection.execute(
            'INSERT INTO probe(rowid,text) SELECT id,text FROM text_rows'))
        cases = []
        for query in ('原创负', '物资核对', '组号07', '不存在的负载词', 'abcdef', 'ＡＢＣ',
                      '"_%"', 'e\u0301', '🙂🚀界', '空\x00白', '文', '🙂🚀', '',
                      '甲乙丙 丁戊己', 'AaA', 'iii', '%_"'):
            term = normalize_text(query)
            expected = [index + 1 for index, text in enumerate(texts) if term in text]
            scan, scan_seconds = timed(lambda: [row[0] for row in connection.execute(
                'SELECT id FROM text_rows WHERE instr(text,?)>0', (term,))])
            assert scan == expected
            row = {'query': query, 'exact_matches': len(expected), 'scan_seconds': scan_seconds}
            grams = trigrams(term)
            frequencies = connection.execute('''SELECT gram,passage_count,indexed FROM query_grams
                WHERE snapshot_id='probe' AND gram IN (SELECT value FROM json_each(?))''',
                (json.dumps(sorted(grams)),)).fetchall()
            indexed = [item for item in frequencies if item[2]]
            if len(frequencies) != len(grams):
                row['gram_plan'] = {'kind': 'empty', 'candidates': 0}
                assert not expected
            elif indexed:
                gram, count, _ = min(indexed, key=lambda item: (item[1], item[0]))
                exact, seconds = timed(lambda: [r[0] for r in connection.execute('''SELECT t.id
                    FROM query_postings p CROSS JOIN text_rows t ON t.id=p.position+1
                    WHERE p.snapshot_id='probe' AND p.gram=? AND instr(t.text,?)>0''', (gram, term))])
                assert sorted(exact) == expected
                row['gram_plan'] = {'kind': 'index', 'candidates': count, 'candidate_and_exact_seconds': seconds}
            else:
                row['gram_plan'] = {'kind': 'scan', 'candidates': len(texts), 'candidate_and_exact_seconds': scan_seconds}
            row['fts_requires_fallback'] = len(term) < 3 or '\x00' in term
            try:
                expression = '"' + term.replace('"', '""') + '"'
                candidates, candidate_seconds = timed(lambda: [r[0] for r in connection.execute(
                    'SELECT rowid FROM probe WHERE probe MATCH ?', (expression,))])
                exact, exact_seconds = timed(lambda: [r[0] for r in connection.execute('''
                    SELECT t.id FROM probe CROSS JOIN text_rows t ON t.id=probe.rowid
                    WHERE probe MATCH ? AND instr(t.text,?)>0''', (expression, term))])
                row.update(candidates=len(candidates), candidate_seconds=candidate_seconds,
                           candidate_and_exact_seconds=exact_seconds,
                           candidate_is_superset=set(expected) <= set(candidates),
                           exact_parity=sorted(exact) == expected)
            except sqlite3.Error as error:
                row['error'] = str(error)
            cases.append(row)
        # Keyword AND must combine independently quoted terms, never interpret
        # user input as FTS syntax. This is an experiment, not a serving path.
        keywords = []
        for query in ('甲乙丙 丁戊己', '物资核对 组号07', '甲乙丙 其', '"_%" ＡＢＣ'):
            terms = normalize_text(query).split()
            expected = [i + 1 for i, text in enumerate(texts) if all(term in text for term in terms)]
            indexable = [term for term in terms if len(term) >= 3 and '\x00' not in term]
            expression = ' AND '.join('"' + term.replace('"', '""') + '"' for term in indexable)
            candidates = [r[0] for r in connection.execute('SELECT rowid FROM probe WHERE probe MATCH ?', (expression,))]
            exact = sorted(i for i in candidates if all(term in texts[i - 1] for term in terms))
            assert exact == expected
            keywords.append({'query': query, 'candidates': len(candidates), 'matches': len(exact), 'exact_parity': True})
        return {'available': True, 'sample_passages': len(texts), 'build_seconds': build_seconds,
                'gram_build_seconds': gram_build_seconds, 'cases': cases, 'keywords': keywords}
    finally:
        connection.close()


def run(database):
    report = {'dataset_kind': 'synthetic', 'environment': machine(), 'sqlite_version': sqlite3.sqlite_version,
              'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'implementation_sha256': hashlib.sha256(Path(indexed_archive.__file__).read_bytes()).hexdigest(),
              'limitations': ['Read-only synthetic database; no HTTP or concurrent requests in this profile',
                  'Sequential new queries share topology/facet caches; OS disk cache is not flushed',
                  'cProfile adds overhead; SQL phase includes execute and fetch, not just instr',
                  'FTS5 uses up to 10000 visible texts plus edge cases in a separate in-memory database',
                  'FTS microbenchmark excludes visibility, sorting, payloads and HTTP; not an API latency'],
              'searches': [], 'sql_variants': []}
    queries = ('原创负', '物资核对', '组号07', '不存在的负载词')
    for query in queries:
        with indexed_view(database, None, ['opening'], 'display') as archive:
            if archive.metadata['dataset_kind'] != 'synthetic':
                raise ValueError('Only synthetic databases may be profiled.')
            report['searches'].append(profile_search(archive, query))
    with indexed_view(database, None, ['opening'], 'display') as archive:
        for query in queries:
            params = {'term': query}
            grouped, old_seconds = timed(lambda: archive.rows(''', search_hits AS MATERIALIZED (
                SELECT v.id,v.position,coalesce(v.speaker_id,'narration') AS speaker,
                  instr(v.text_norm,:term)>0 AS matched FROM passages v
                ) SELECT speaker,count(*) AS n,
                    json_group_array(json_array(id,position)) FILTER (WHERE matched) AS matches
                  FROM search_hits GROUP BY speaker ORDER BY speaker''', params))
            flat, flat_seconds = timed(lambda: archive.rows('''SELECT
                json_group_array(json_array(v.id,v.position)) AS matches
                FROM passages v WHERE instr(v.text_norm,:term)>0''', params))
            expected = sorted(match for row in grouped for match in json.loads(row['matches']))
            assert sorted(json.loads(flat[0]['matches'])) == expected
            report['sql_variants'].append({'query': query, 'matches': len(expected),
                'materialized_group_seconds': old_seconds, 'flat_aggregate_seconds': flat_seconds,
                'note': 'Flat aggregate excludes facets; measured separately below.'})
        facets, seconds = timed(lambda: archive.rows('''SELECT coalesce(speaker_id,'narration') AS speaker,
            count(*) AS n FROM passages GROUP BY speaker ORDER BY speaker'''))
        report['uncached_facets_seconds'] = seconds
        report['visible_passages'] = sum(row['n'] for row in facets)
        texts = [r[0] for r in archive.rows('SELECT text_norm FROM passages ORDER BY position LIMIT 10000')]
    texts.extend(normalize_text(text) for text in ('abcdef', 'abc bcd cde def',
        'ＡＢＣ "_%" e\u0301 🙂🚀界 空\x00白', 'ab\x00abcdef', '甲乙丙 丁戊己', '甲乙丙 其他',
        '中文短词', 'AaA aaa', 'İİİ iii', '%_"', '🚀🙂🎉'))
    report['fts5'] = fts_experiment(texts)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--database', type=Path, help='Existing synthetic database; opened read-only')
    source.add_argument('--count', type=int, default=100000, help='Build a temporary synthetic database (default: 100000)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new path.')
    if not 200 <= args.count <= 100000:
        parser.error('Bounds: count 200–100000.')
    if args.database is not None:
        report = run(args.database)
    else:
        with tempfile.TemporaryDirectory(prefix='archive-search-plans-') as directory:
            database = Path(directory) / 'archive.sqlite3'
            data, _ = workload('long', args.count)
            import_snapshot(data, database)
            del data
            report = run(database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(args.output)


if __name__ == '__main__':
    main()
