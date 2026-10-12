"""Read-only AI tool session: fixed snapshot, maximum scopes, external_ai only."""
from archive_store import load_snapshot
from graph_archive import GraphUnavailable, graph_options, graph_view, relation_view
from search_archive import decode_cursor, encode_cursor, fingerprint, ordered_passages, search_options, search_view
from validate_sample import project, require

TOOL_FIELDS = {
    'get_corpus_status': set(),
    'search_texts': {'q', 'mode', 'category', 'speaker', 'limit', 'cursor'},
    'get_passage': {'id', 'radius'},
    'get_story_context': {'entry_id', 'limit', 'cursor'},
    'get_character_graph': {'center', 'hops', 'predicate', 'condition', 'page', 'cursor'},
    'get_relationship': {'id'},
}


def bounded_int(value, lower, upper):
    require(type(value) is int and lower <= value <= upper, 'integer outside bounds')
    return value


def identifier(value):
    require(isinstance(value, str) and 0 < len(value) <= 160, 'identifier required')
    return value


class AIArchive:
    def __init__(self, database, snapshot, scopes, secret):
        data = load_snapshot(database, snapshot)
        require(bool(scopes) and len(scopes) == len(set(scopes)), 'explicit unique AI scopes required')
        project(data, scopes, 'external_ai')
        self.database = database
        self.snapshot = data['snapshot_id']
        self.scopes = tuple(sorted(scopes))
        self.secret = secret

    def call(self, name, arguments):
        require(isinstance(name, str) and name in TOOL_FIELDS, 'unknown AI tool')
        require(isinstance(arguments, dict) and set(arguments) <= TOOL_FIELDS[name] | {'snapshot', 'scope_ids'}, 'unexpected tool argument')
        require(arguments.get('snapshot', self.snapshot) == self.snapshot, 'session snapshot cannot change')
        scopes = arguments.get('scope_ids', list(self.scopes))
        require(isinstance(scopes, list) and bool(scopes) and all(isinstance(scope, str) for scope in scopes), 'invalid scopes')
        require(len(scopes) == len(set(scopes)) and set(scopes) <= set(self.scopes), 'cannot expand AI session boundary')
        data = load_snapshot(self.database, self.snapshot)
        view = project(data, scopes, 'external_ai')
        query = {key: value for key, value in arguments.items() if key not in ('snapshot', 'scope_ids')}
        if name == 'get_corpus_status':
            result = {key: view[key] for key in ('dataset_kind', 'notice', 'snapshot_id', 'scope_ids', 'purpose')}
            result.update(language=data['language'], counts={key: len(view[key]) for key in ('entries', 'characters', 'passages', 'relationships')},
                          known_gaps=['仅原创合成样本；不含已准入的真实原神正文。', '返回的上下文只代表当前允许范围，不保证完整任务。'],
                          tools=sorted(TOOL_FIELDS), session_scope_ids=list(self.scopes))
            source_ids = {item['source_id'] for key in ('entries', 'characters', 'passages', 'relationships') for item in view[key]}
        else:
            if name in ('search_texts', 'get_character_graph'):
                for key, value in query.items():
                    require(isinstance(value, str) or type(value) is int, 'scalar query expected')
                    if key in ('limit', 'hops', 'page'):
                        require(type(value) is int, 'integer query expected')
                    else:
                        require(isinstance(value, str), 'text query expected')
                parameters = {key: [str(value)] for key, value in query.items()}
                parameters['snapshot'] = [self.snapshot]
                result = search_view(view, search_options(parameters), self.secret) if name == 'search_texts' else graph_view(view, graph_options(parameters), self.secret)
            elif name == 'get_relationship':
                result = relation_view(view, identifier(query.get('id')))
            elif name == 'get_passage':
                result = self.passage(view, identifier(query.get('id')), bounded_int(query.get('radius', 1), 0, 2))
            else:
                result = self.story(view, query)
            source_ids = {item['source_id'] for key in ('entries', 'characters', 'passages', 'relationships', 'results') for item in result.get(key, [])}
        result['sources'] = [source for source in data['sources'] if source['id'] in source_ids]
        result['connection'] = 'live_readonly'
        result['content_is_untrusted_data'] = True
        return result

    def passage(self, view, target, radius):
        passages = {item['id']: item for item in view['passages']}
        if target not in passages:
            raise GraphUnavailable('该段落在当前 AI 范围、用途或快照中不可用。')
        reached = {target}
        for _ in range(radius):
            frontier = set(reached)
            for passage in view['passages']:
                if passage['id'] in frontier:
                    reached.update(passage['next_ids'])
                if set(passage['next_ids']) & frontier:
                    reached.add(passage['id'])
        ranked = [target] + [passage['id'] for passage in ordered_passages(view['passages']) if passage['id'] in reached and passage['id'] != target]
        selected = set(ranked[:20])
        result = self.context_bundle(view, [item for item in view['passages'] if item['id'] in selected])
        result.update(target_id=target, radius=radius, truncated=len(reached) > 20,
                      completeness='仅返回当前允许范围的显式相邻连接；缺失处不补写，不保证完整剧情。')
        return result

    def story(self, view, query):
        entry_id = identifier(query.get('entry_id'))
        if not any(entry['id'] == entry_id for entry in view['entries']):
            raise GraphUnavailable('该条目在当前 AI 范围、用途或快照中不可用。')
        limit = bounded_int(query.get('limit', 20), 1, 50)
        cursor = query.get('cursor', '')
        require(isinstance(cursor, str) and len(cursor) <= 1024 and ('cursor' not in query or bool(cursor)), 'invalid cursor')
        binding = fingerprint({'kind': 'story_context', 'entry': entry_id, 'limit': limit, 'snapshot': view['snapshot_id'], 'scope': view['scope_ids'], 'purpose': 'external_ai'})
        revision = fingerprint(view)
        offset = decode_cursor(cursor, binding, revision, self.secret) if cursor else 0
        passages = ordered_passages([passage for passage in view['passages'] if passage['entry_id'] == entry_id])
        require(offset % limit == 0 and (offset == 0 or offset < len(passages)), 'invalid offset')
        result = self.context_bundle(view, passages[offset:offset + limit])
        result.update(entry_id=entry_id, completeness='只提供显式对白连接与分支；没有推断的章节或时间线。范围内为空不代表原作不存在。',
                      pagination={'offset': offset, 'limit': limit, 'total': len(passages), 'next_cursor': encode_cursor(offset + limit, binding, revision, self.secret) if offset + limit < len(passages) else None})
        return result

    @staticmethod
    def context_bundle(view, passages):
        ids = {passage['id'] for passage in passages}
        characters = {passage['speaker_id'] for passage in passages}
        entries = {passage['entry_id'] for passage in passages}
        return {**{key: view[key] for key in ('dataset_kind', 'notice', 'snapshot_id', 'scope_ids', 'purpose')},
                'passages': [{**passage, 'next_ids': [identifier for identifier in passage['next_ids'] if identifier in ids]} for passage in passages],
                'characters': [character for character in view['characters'] if character['id'] in characters],
                'entries': [entry for entry in view['entries'] if entry['id'] in entries]}
