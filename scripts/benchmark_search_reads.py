"""Compare exact text-read strategies; optionally force middle-only body matches."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from archive_store import import_snapshot
from benchmark_boundaries import workload
import benchmark_search_concurrency as concurrency
import indexed_archive
import query_index


MIDDLE_MARKER = '中段专用检索标记用于完整正文回退'
MODES = ('baseline', 'lean', 'range', 'serial', 'pair', 'edges')


def middle_groups(data):
    terms = [MIDDLE_MARKER[:length] for length in range(3, 13)]
    for passage in data['passages'][32:]:
        text = passage['text']
        assert all(term in text and term not in text[:64] and term not in text[-64:] for term in terms)
    return {'middle_only': terms}


def run(database, mode, middle=False):
    original = indexed_archive.IndexedArchive.search_rows
    gate = threading.BoundedSemaphore(1 if mode == 'serial' else 2)

    def read(archive, sql, parameters=None):
        if mode == 'edges':
            return original(archive, sql, parameters)
        params = {**archive.params, **(parameters or {})}
        scan = 'json_group_array(v.position)' in sql
        cte = archive.cte
        if scan and mode in ('lean', 'range'):
            cte = archive.passages_cte
            if mode == 'range':
                lo, hi = archive.connection.execute('''SELECT min(rowid),max(rowid) FROM query_records
                    WHERE snapshot_id=? AND collection='passages' ''', (archive.snapshot,)).fetchone()
                params.update(scan_lo=lo, scan_hi=hi)
                cte = cte.replace("SELECT q.* FROM query_records q WHERE q.snapshot_id=:snapshot AND q.collection='passages'",
                    "SELECT q.* FROM query_records q NOT INDEXED WHERE q.rowid BETWEEN :scan_lo AND :scan_hi AND q.snapshot_id=:snapshot AND q.collection='passages'")
        if scan and mode in ('serial', 'pair'):
            with gate:
                return archive.connection.execute(cte + sql, params).fetchall()
        return archive.connection.execute(cte + sql, params).fetchall()

    with ExitStack() as stack:
        stack.enter_context(patch.object(indexed_archive.IndexedArchive, 'search_rows', new=read))
        if mode != 'edges':
            stack.enter_context(patch.object(indexed_archive, 'text_condition',
                                            side_effect=lambda p: f'instr(v.text_norm,:{p})>0'))
        if middle:
            stack.enter_context(patch.object(concurrency, 'query_groups', new=middle_groups))
        result = concurrency.run(database)
    result.update(read_strategy=mode, middle_only=middle, index_version=query_index.VERSION,
                  probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  query_index_sha256=hashlib.sha256(Path(query_index.__file__).read_bytes()).hexdigest())
    result['limitations'].append('All modes use the current schema; baseline substitutes the previous exact matching SQL only')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--count', type=int, default=100000)
    parser.add_argument('--mode', choices=MODES, default='edges')
    parser.add_argument('--middle', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 200 <= args.count <= 100000:
        parser.error('Choose a new output and count 200–100000.')
    if args.database is not None:
        report = run(args.database, args.mode, args.middle)
    else:
        with tempfile.TemporaryDirectory(prefix='archive-read-strategies-') as directory:
            database = Path(directory) / 'archive.sqlite3'
            data, _ = workload('long', args.count)
            if args.middle:
                data['snapshot_id'] = f'boundary-middle-{args.count}-v1'
                for collection in ('sources', 'entries', 'characters', 'passages', 'relationships'):
                    for record in data[collection]:
                        record['snapshot_id'] = data['snapshot_id']
                for passage in data['passages'][32:]:
                    passage['text'] = passage['text'][:480] + MIDDLE_MARKER + passage['text'][480 + len(MIDDLE_MARKER):]
            import_snapshot(data, database)
            del data
            report = run(database, args.mode, args.middle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
