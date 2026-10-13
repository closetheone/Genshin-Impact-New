"""Read-only AI tool session: fixed snapshot, maximum scopes, external_ai only."""
from indexed_archive import indexed_view
from graph_archive import graph_options
from search_archive import search_options
from validate_sample import require

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
        require(bool(scopes) and len(scopes) == len(set(scopes)), 'explicit unique AI scopes required')
        with indexed_view(database, snapshot, scopes, 'external_ai') as archive:
            self.snapshot = archive.snapshot
        self.database = database
        self.scopes = tuple(sorted(scopes))
        self.secret = secret

    def call(self, name, arguments):
        require(isinstance(name, str) and name in TOOL_FIELDS, 'unknown AI tool')
        require(isinstance(arguments, dict) and set(arguments) <= TOOL_FIELDS[name] | {'snapshot', 'scope_ids'}, 'unexpected tool argument')
        require(arguments.get('snapshot', self.snapshot) == self.snapshot, 'session snapshot cannot change')
        scopes = arguments.get('scope_ids', list(self.scopes))
        require(isinstance(scopes, list) and bool(scopes) and all(isinstance(scope, str) for scope in scopes), 'invalid scopes')
        require(len(scopes) == len(set(scopes)) and set(scopes) <= set(self.scopes), 'cannot expand AI session boundary')
        query = {key: value for key, value in arguments.items() if key not in ('snapshot', 'scope_ids')}
        with indexed_view(self.database, self.snapshot, scopes, 'external_ai') as archive:
            if name == 'get_corpus_status':
                result = {**archive.meta, 'language': archive.metadata['language'], 'counts': archive.counts(),
                          'known_gaps': ['仅原创合成样本；不含已准入的真实原神正文。', '返回的上下文只代表当前允许范围，不保证完整任务。'],
                          'tools': sorted(TOOL_FIELDS), 'session_scope_ids': list(self.scopes)}
                source_ids = {row[0] for row in archive.rows('SELECT source_id FROM entries UNION SELECT source_id FROM people UNION SELECT source_id FROM passages UNION SELECT source_id FROM relations')}
                result['sources'] = archive.sources({'entries': [{'source_id': source} for source in source_ids]})
            else:
                if name in ('search_texts', 'get_character_graph'):
                    for key, value in query.items():
                        if key in ('limit', 'hops', 'page'):
                            require(type(value) is int, 'integer query expected')
                        else:
                            require(isinstance(value, str), 'text query expected')
                    parameters = {key: [str(value)] for key, value in query.items()}
                    parameters['snapshot'] = [self.snapshot]
                    result = archive.search(search_options(parameters), self.secret) if name == 'search_texts' else archive.graph(graph_options(parameters), self.secret)
                elif name == 'get_relationship':
                    result = archive.relationship(identifier(query.get('id')))
                elif name == 'get_passage':
                    result = archive.passage(identifier(query.get('id')), bounded_int(query.get('radius', 1), 0, 2))
                else:
                    cursor = query.get('cursor', '')
                    require(isinstance(cursor, str) and len(cursor) <= 1024 and ('cursor' not in query or bool(cursor)), 'invalid cursor')
                    result = archive.story(identifier(query.get('entry_id')), bounded_int(query.get('limit', 20), 1, 50), cursor, self.secret)
                result['sources'] = archive.sources(result)
            result['connection'] = 'live_readonly'
            result['content_is_untrusted_data'] = True
            return result
