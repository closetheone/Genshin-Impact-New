"""Rebuildable, transactionally published query indexes over immutable snapshots."""
from archive_store import COLLECTIONS, StoreError, connect, ensure_schema, read_snapshot
from pathlib import Path
from collections import Counter
from search_archive import normalize_text, ordered_passages

VERSION = 3
# Bound posting storage; unindexed/common grams always use the exact scan path.
MAX_POSTINGS_PER_PASSAGE = 32
MAX_CANDIDATES = 10000
DDL = (
    'CREATE TABLE query_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, policy_revision INTEGER NOT NULL)',
    f'INSERT INTO query_state VALUES(1, {VERSION}, 0)',
    'CREATE TABLE query_snapshots(snapshot_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, ready INTEGER NOT NULL DEFAULT 0, has_backlinks INTEGER NOT NULL DEFAULT 0)',
    '''CREATE TABLE query_records(snapshot_id TEXT NOT NULL, id TEXT NOT NULL, collection TEXT NOT NULL, position INTEGER NOT NULL,
       scope_mask INTEGER NOT NULL, source_id TEXT, entry_id TEXT, speaker_id TEXT, text_norm TEXT, sort_rank INTEGER,
       from_id TEXT, to_id TEXT, predicate TEXT, branch_id TEXT, approved INTEGER NOT NULL, name TEXT,
       PRIMARY KEY(snapshot_id,id))''',
    'CREATE INDEX query_collection ON query_records(snapshot_id,collection,position)',
    'CREATE INDEX query_entry ON query_records(snapshot_id,entry_id,sort_rank)',
    'CREATE INDEX query_speaker ON query_records(snapshot_id,speaker_id,sort_rank)',
    'CREATE INDEX query_from ON query_records(snapshot_id,from_id)',
    'CREATE INDEX query_to ON query_records(snapshot_id,to_id)',
    'CREATE TABLE query_links(snapshot_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, PRIMARY KEY(snapshot_id,from_id,to_id))',
    'CREATE INDEX query_reverse_link ON query_links(snapshot_id,to_id,from_id)',
    'CREATE TABLE query_evidence(snapshot_id TEXT NOT NULL, relation_id TEXT NOT NULL, group_number INTEGER NOT NULL, passage_id TEXT NOT NULL, PRIMARY KEY(snapshot_id,relation_id,group_number,passage_id))',
    'CREATE INDEX query_evidence_passage ON query_evidence(snapshot_id,passage_id)',
)


def install_visibility(connection):
    # Cover live visibility checks without visiting rows containing long text.
    connection.execute('''CREATE INDEX query_visibility ON query_records(
        snapshot_id,collection,scope_mask,source_id,id,entry_id,speaker_id)''')


def trigrams(text):
    """Unicode code-point substrings of already-normalized text, including NUL."""
    return {text[index:index + 3] for index in range(len(text) - 2)}


def install_candidates(connection):
    connection.execute('''CREATE TABLE query_grams(snapshot_id TEXT NOT NULL, gram TEXT NOT NULL,
        passage_count INTEGER NOT NULL, indexed INTEGER NOT NULL,
        PRIMARY KEY(snapshot_id,gram)) WITHOUT ROWID''')
    connection.execute('''CREATE TABLE query_postings(snapshot_id TEXT NOT NULL, gram TEXT NOT NULL,
        position INTEGER NOT NULL, PRIMARY KEY(snapshot_id,gram,position)) WITHOUT ROWID''')
    for table in ('query_grams', 'query_postings'):
        for action, alias in (('INSERT', 'NEW'), ('DELETE', 'OLD'), ('UPDATE', 'OLD')):
            extra = ' UPDATE query_snapshots SET ready=0 WHERE snapshot_id=NEW.snapshot_id;' if action == 'UPDATE' else ''
            connection.execute(f'''CREATE TRIGGER dirty_{table}_{action.lower()} AFTER {action} ON {table}
                BEGIN UPDATE query_snapshots SET ready=0 WHERE snapshot_id={alias}.snapshot_id;{extra} END''')


def build_candidates(connection, data):
    snapshot = data['snapshot_id']
    frequencies = Counter()
    for passage in data['passages']:
        frequencies.update(trigrams(normalize_text(passage['text'])))
    budget = len(data['passages']) * MAX_POSTINGS_PER_PASSAGE
    threshold = min(MAX_CANDIDATES, max(1, len(data['passages']) // 5))
    selected = set()
    for gram, count in sorted(frequencies.items(), key=lambda pair: (pair[1], pair[0])):
        if count > threshold or count > budget:
            break
        selected.add(gram)
        budget -= count
    connection.executemany('INSERT INTO query_grams VALUES(?,?,?,?)',
        ((snapshot, gram, count, int(gram in selected)) for gram, count in frequencies.items()))
    connection.executemany('INSERT INTO query_postings VALUES(?,?,?)',
        ((snapshot, gram, position) for position, passage in enumerate(data['passages'])
         for gram in sorted(trigrams(normalize_text(passage['text'])) & selected)))


def installed(connection):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_state'").fetchone() is not None


def ensure_indexes(connection):
    if installed(connection):
        row = connection.execute('SELECT version FROM query_state WHERE singleton=1').fetchone()
        if row and row[0] in (1, 2):
            if row[0] == 1:
                install_candidates(connection)
                connection.execute('UPDATE query_snapshots SET ready=0')
            # v2 records are already validated: adding a covering index does not
            # change content, readiness or postings. Publish with the version in
            # the caller's write transaction, rolling both back on any failure.
            install_visibility(connection)
            connection.execute('UPDATE query_state SET version=?,policy_revision=policy_revision+1', (VERSION,))
        elif not row or row[0] != VERSION:
            raise StoreError('Unsupported query index version; explicit migration required.')
        return
    for statement in DDL:
        connection.execute(statement)
    install_candidates(connection)
    install_visibility(connection)
    # Detect ordinary SQL edits, including maintenance/restore. No authorization
    # result is cached. A DBA able to remove triggers is outside this local boundary.
    for table in ('records', 'query_records', 'query_links', 'query_evidence'):
        for action, alias in (('INSERT', 'NEW'), ('DELETE', 'OLD'), ('UPDATE', 'OLD')):
            extra = " UPDATE query_snapshots SET ready=0 WHERE snapshot_id=NEW.snapshot_id;" if action == 'UPDATE' else ''
            connection.execute(f'''CREATE TRIGGER dirty_{table}_{action.lower()} AFTER {action} ON {table}
                BEGIN UPDATE query_snapshots SET ready=0 WHERE snapshot_id={alias}.snapshot_id;{extra} END''')
    for action, alias in (('INSERT', 'NEW'), ('DELETE', 'OLD'), ('UPDATE', 'OLD')):
        connection.execute(f'''CREATE TRIGGER dirty_snapshot_{action.lower()} AFTER {action} ON snapshots
            BEGIN UPDATE query_snapshots SET ready=0 WHERE snapshot_id={alias}.id; END''')
    for table in ('source_policies', 'withdrawals'):
        for action in ('INSERT', 'DELETE', 'UPDATE'):
            when = 'WHEN OLD.rights != NEW.rights OR OLD.id != NEW.id' if action == 'UPDATE' and table == 'source_policies' else ''
            connection.execute(f'''CREATE TRIGGER revision_{table}_{action.lower()} AFTER {action} ON {table} {when}
                BEGIN UPDATE query_state SET policy_revision=policy_revision+1 WHERE singleton=1; END''')
    # This archive only supports tightening. Reject raw SQL attempts to undo the
    # same floor that normal import enforces (deletions otherwise unhide data).
    connection.execute("CREATE TRIGGER no_withdrawal_delete BEFORE DELETE ON withdrawals BEGIN SELECT RAISE(ABORT,'withdrawals cannot be removed'); END")
    connection.execute("CREATE TRIGGER no_withdrawal_update BEFORE UPDATE ON withdrawals BEGIN SELECT RAISE(ABORT,'withdrawals are immutable'); END")
    connection.execute("CREATE TRIGGER no_policy_delete BEFORE DELETE ON source_policies BEGIN SELECT RAISE(ABORT,'source policies cannot be removed'); END")
    connection.execute('''CREATE TRIGGER no_policy_loosen BEFORE UPDATE ON source_policies
        WHEN NEW.id != OLD.id OR EXISTS(SELECT 1 FROM json_each(OLD.rights) old
        WHERE CASE old.value WHEN 'denied' THEN 2 WHEN 'unknown' THEN 1 ELSE 0 END >
              CASE json_extract(NEW.rights, '$.' || old.key) WHEN 'denied' THEN 2 WHEN 'unknown' THEN 1 ELSE 0 END)
        BEGIN SELECT RAISE(ABORT,'source policies cannot be loosened'); END''')
    for action in ('INSERT', 'UPDATE'):
        connection.execute(f'''CREATE TRIGGER validate_policy_{action.lower()} BEFORE {action} ON source_policies
          WHEN NOT json_valid(NEW.rights) OR json_type(NEW.rights) != 'object'
          OR (SELECT count(*) FROM json_each(NEW.rights)) != 4
          OR coalesce(json_extract(NEW.rights,'$.storage'),'') != 'allowed'
          OR EXISTS(SELECT 1 FROM json_each(NEW.rights) WHERE key NOT IN ('storage','display','export','external_ai')
             OR value NOT IN ('allowed','unknown','denied') OR type != 'text')
          BEGIN SELECT RAISE(ABORT,'invalid source policy'); END''')


def build_index(connection, data):
    snapshot = data['snapshot_id']
    scopes = data['scope_ids']
    if len(scopes) > 60:
        raise StoreError('Query index supports at most 60 named scopes.')
    bits = {name: 1 << index for index, name in enumerate(scopes)}
    ranks = {p['id']: rank for rank, p in enumerate(ordered_passages(data['passages']))}
    content_hash = connection.execute('SELECT content_hash FROM snapshots WHERE id=?', (snapshot,)).fetchone()[0]
    positions = {p['id']: index for index, p in enumerate(data['passages'])}
    backlinks = any(positions[following] < positions[p['id']] for p in data['passages'] for following in p['next_ids'])
    connection.execute('INSERT INTO query_snapshots VALUES(?,?,0,?) ON CONFLICT(snapshot_id) DO UPDATE SET ready=0,content_hash=excluded.content_hash,has_backlinks=excluded.has_backlinks', (snapshot, content_hash, int(backlinks)))
    for table in ('query_records', 'query_links', 'query_evidence', 'query_grams', 'query_postings'):
        connection.execute(f'DELETE FROM {table} WHERE snapshot_id=?', (snapshot,))
    for collection in COLLECTIONS:
        rows = []
        for position, record in enumerate(data[collection]):
            rows.append((snapshot, record['id'], collection, position,
                         sum(bits[name] for name in record.get('required_scope_ids', [])), record.get('source_id'),
                         record.get('entry_id'), record.get('speaker_id'), normalize_text(record.get('text', '')),
                         ranks.get(record['id']), record.get('from_id'), record.get('to_id'), record.get('predicate'),
                         record.get('branch_id'), int(record.get('review_status') == 'approved' and record.get('claim_kind') == 'explicit'), record.get('name')))
        connection.executemany('INSERT INTO query_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    connection.executemany('INSERT INTO query_links VALUES(?,?,?)', [(snapshot, p['id'], following) for p in data['passages'] for following in p['next_ids']])
    connection.executemany('INSERT INTO query_evidence VALUES(?,?,?,?)', [(snapshot, r['id'], number, identifier) for r in data['relationships'] for number, group in enumerate(r['evidence_groups']) for identifier in group])
    build_candidates(connection, data)
    connection.execute('UPDATE query_snapshots SET ready=1 WHERE snapshot_id=?', (snapshot,))


def prepare_indexes(database, rebuild=False):
    """Explicit startup/maintenance migration, never a reader's hidden write."""
    if not Path(database).expanduser().is_file():
        raise StoreError('Existing imported database required for index preparation.')
    connection = connect(database, writable=True)
    try:
        connection.execute('BEGIN IMMEDIATE')
        ensure_schema(connection)
        ensure_indexes(connection)
        rebuilt = []
        for row in connection.execute('SELECT id,content_hash FROM snapshots').fetchall():
            ready = connection.execute('SELECT ready,content_hash FROM query_snapshots WHERE snapshot_id=?', (row['id'],)).fetchone()
            if rebuild or ready is None or not ready['ready'] or ready['content_hash'] != row['content_hash']:
                data = read_snapshot(connection, row['id'], apply_restrictions=False)
                build_index(connection, data)
                rebuilt.append(row['id'])
        connection.commit()
        return {'index_version': VERSION, 'rebuilt_snapshots': rebuilt}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
