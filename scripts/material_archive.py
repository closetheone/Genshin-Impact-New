"""Resolve a local selection against current scope AND export permissions."""
from urllib.parse import quote, urlencode

from search_archive import fingerprint
from validate_sample import project, require

LIMIT = 50


class MaterialCapacity(Exception):
    pass


def identifier(value):
    require(isinstance(value, str) and 0 < len(value) <= 160, 'invalid identifier')
    return value


def identifiers(value):
    require(isinstance(value, list) and len(value) <= LIMIT, 'invalid identifier list')
    return list(dict.fromkeys(identifier(item) for item in value))


def selection_request(payload):
    require(isinstance(payload, dict), 'expected object')
    require(set(payload) <= {'snapshot', 'scope_ids', 'purpose', 'topic', 'passage_ids', 'relationships', 'add'}, 'unknown field')
    snapshot = identifier(payload.get('snapshot'))
    scopes = payload.get('scope_ids')
    require(isinstance(scopes, list) and 0 < len(scopes) <= 4 and all(isinstance(item, str) for item in scopes), 'explicit scopes required')
    require(len(scopes) == len(set(scopes)), 'duplicate scope')
    purpose = payload.get('purpose', 'display')
    require(purpose in ('display', 'export', 'external_ai'), 'invalid purpose')
    topic = payload.get('topic', '')
    require(isinstance(topic, str) and len(topic) <= 500, 'invalid topic')
    passages = identifiers(payload.get('passage_ids', []))
    supplied = payload.get('relationships', [])
    require(isinstance(supplied, list) and len(supplied) <= LIMIT, 'invalid relationships')
    relationships = []
    for item in supplied:
        require(isinstance(item, dict) and set(item) == {'id', 'evidence_ids'}, 'invalid relationship selection')
        relation = {'id': identifier(item['id']), 'evidence_ids': identifiers(item['evidence_ids'])}
        require(bool(relation['evidence_ids']), 'complete evidence group required')
        previous = next((other for other in relationships if other['id'] == relation['id']), None)
        require(previous is None or previous == relation, 'conflicting evidence selections')
        if previous is None:
            relationships.append(relation)
    addition = payload.get('add')
    if addition is not None:
        require(isinstance(addition, dict) and set(addition) == {'kind', 'id'}, 'invalid addition')
        require(addition['kind'] in ('passage', 'relationship'), 'invalid addition kind')
        identifier(addition['id'])
    return {'snapshot': snapshot, 'scope_ids': scopes, 'purpose': purpose, 'topic': topic,
            'passage_ids': passages, 'relationships': relationships, 'add': addition}


def material_view(data, request):
    require(request['snapshot'] == data['snapshot_id'], 'snapshot mismatch')
    # Tighten the export policy without mutating the immutable loaded snapshot.
    sources = [{**source, 'rights': {**source['rights'], 'export': 'allowed' if source['rights']['export'] == 'allowed' and source['rights'][request['purpose']] == 'allowed' else 'denied'}} for source in data['sources']]
    view = project({**data, 'sources': sources}, request['scope_ids'], 'export')
    by_passage = {item['id']: item for item in view['passages']}
    by_relation = {item['id']: item for item in view['relationships']}
    selected = {'snapshot': request['snapshot'], 'topic': request['topic'], 'passage_ids': list(request['passage_ids']),
                'relationships': [{**item, 'evidence_ids': list(item['evidence_ids'])} for item in request['relationships']]}
    errors = []
    addition = request['add']
    if addition:
        identifier = addition['id']
        if addition['kind'] == 'passage':
            if identifier not in by_passage:
                errors.append({'kind': 'passage', 'id': identifier, 'code': 'unavailable'})
            elif identifier not in selected['passage_ids']:
                selected['passage_ids'].append(identifier)
        elif identifier not in by_relation:
            errors.append({'kind': 'relationship', 'id': identifier, 'code': 'unavailable'})
        elif not any(item['id'] == identifier for item in selected['relationships']):
            selected['relationships'].append({'id': identifier, 'evidence_ids': by_relation[identifier]['evidence_groups'][0]})
    passage_ids = set(selected['passage_ids'])
    for item in selected['relationships']:
        passage_ids.update(item['evidence_ids'])
    if len(passage_ids) > LIMIT or len(selected['relationships']) > LIMIT:
        raise MaterialCapacity('清单最多 50 个独立片段及 50 条关系；完整证据组不能拆开。请移除素材或另建清单。')
    for identifier in selected['passage_ids']:
        if identifier not in by_passage:
            errors.append({'kind': 'passage', 'id': identifier, 'code': 'unavailable'})
    relations = []
    for item in selected['relationships']:
        relation = by_relation.get(item['id'])
        if relation is None or item['evidence_ids'] not in relation['evidence_groups']:
            errors.append({'kind': 'relationship', 'id': item['id'], 'code': 'evidence_unavailable'})
        else:
            relations.append({**relation, 'evidence_groups': [item['evidence_ids']]})
    # Never return fragments of a failed relationship group as a usable selection.
    usable_ids = set(selected['passage_ids']) & by_passage.keys()
    for relation in relations:
        usable_ids.update(relation['evidence_groups'][0])
    passages = [{**by_passage[identifier], 'next_ids': [next_id for next_id in by_passage[identifier]['next_ids'] if next_id in usable_ids]} for identifier in sorted(usable_ids)]
    character_ids = {passage['speaker_id'] for passage in passages}
    character_ids.update(identifier for relation in relations for identifier in (relation['from_id'], relation['to_id']))
    entry_ids = {passage['entry_id'] for passage in passages}
    characters = [item for item in view['characters'] if item['id'] in character_ids]
    entries = [item for item in view['entries'] if item['id'] in entry_ids]
    source_ids = {item['source_id'] for item in passages + relations + characters + entries}
    package = {
        'format_version': '1.0', 'dataset_kind': data['dataset_kind'], 'notice': data['notice'],
        'language': data['language'], 'topic': request['topic'], 'snapshot_id': data['snapshot_id'],
        'scope_ids': view['scope_ids'], 'purpose': 'export', 'checked_purpose': request['purpose'],
        'selection': selected, 'passages': passages, 'relationships': relations, 'characters': characters, 'entries': entries,
        'sources': [source for source in data['sources'] if source['id'] in source_ids],
    }
    return {'dataset_kind': data['dataset_kind'], 'snapshot_id': data['snapshot_id'], 'selection': selected,
            'valid': not errors, 'errors': errors, 'count': len(passage_ids), 'limit': LIMIT,
            'preview': {'passages': passages, 'relationships': relations},
            'package': package if not errors else None,
            'revision': fingerprint(package) if not errors else None,
            'markdown': material_markdown(package) if not errors else None}


def literal(value):
    """Keep arbitrary source/topic text literal even in a Markdown renderer."""
    return ''.join(f'&#{ord(character)};' if character in '&<>`*_[]()#!|\\' else character for character in value)


def material_markdown(package):
    lines = ['# 创作素材包', '', literal(package['notice']), '', f"主题：{literal(package['topic'])}",
             f"语言：{package['language']} · 格式：{package['format_version']}",
             f"快照：{literal(package['snapshot_id'])}", f"内容范围：{', '.join(package['scope_ids'])}",
             f"用途：export；同时核验 {package['checked_purpose']}。外部 AI 使用须遵守每项来源用途。", '', '## 原文片段', '']
    speakers = {character['id']: character['name'] for character in package['characters']}
    for passage in package['passages']:
        link = '#/read?' + urlencode({'passage': passage['id'], 'snapshot': package['snapshot_id']}, quote_via=quote)
        lines.extend([f"### {literal(passage['id'])}", '', literal(speakers.get(passage['speaker_id'], passage['speaker_id'] or '叙述')),
                      '', *['> ' + literal(line) for line in passage['text'].splitlines()], '',
                      f"出处：{literal(passage['source_id'])} · {literal(passage['source_locator'])}",
                      f"条件：{', '.join(passage['required_scope_ids'])}；分支：{passage['branch_id'] or '公共'}",
                      f'[在同一档案服务定位（不自动扩大范围）]({link})', ''])
    lines.extend(['## 人物关系', ''])
    for relation in package['relationships']:
        lines.extend([f"### {literal(relation['id'])}", '',
                      f"{literal(relation['from_id'])} {'→' if relation['direction'] == 'directed' else '—'} {literal(relation['to_id'])} · {relation['predicate']}",
                      literal(relation['description']), f"条件：{', '.join(relation['required_scope_ids'])}；分支：{relation['branch_id'] or '公共'}",
                      '完整证据组：' + ', '.join(literal(identifier) for identifier in relation['evidence_groups'][0]), ''])
    lines.extend(['## 来源记录', ''])
    for source in package['sources']:
        lines.extend([f"- {literal(source['id'])} · {literal(source['locator'])} · {source['content_type']} · 快照 {literal(source['snapshot_id'])}",
                      '  用途：' + ', '.join(f'{key}={value}' for key, value in source['rights'].items())])
    return '\n'.join(lines) + '\n'
