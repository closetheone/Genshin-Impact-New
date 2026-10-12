"""Validate an offline synthetic JSON material pack before using it with AI."""
import argparse
import json
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key.')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f'Non-finite JSON value: {value}')


def string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value) and len(value) == len(set(value))


def validate_pack(package, scopes):
    require(isinstance(package, dict), 'Expected JSON material pack.')
    require(package.get('format_version') == '1.0' and package.get('dataset_kind') == 'synthetic', 'Only version 1.0 synthetic packs are currently supported.')
    require(package.get('purpose') == 'export' and package.get('language') == 'zh-CN', 'Unsupported purpose or language.')
    snapshot = package.get('snapshot_id')
    require(isinstance(snapshot, str) and bool(snapshot), 'Missing snapshot.')
    require(string_list(scopes) and bool(scopes) and set(scopes) <= {'opening', 'east', 'west', 'later'}, 'Invalid allowed scopes.')
    require(string_list(package.get('scope_ids')) and bool(package['scope_ids']) and set(package['scope_ids']) <= set(scopes), 'Pack exceeds the explicitly allowed scope; re-export a narrower pack.')
    indexes = {}
    all_ids = set()
    for name in ('sources', 'entries', 'characters', 'passages', 'relationships'):
        records = package.get(name)
        require(isinstance(records, list), f'Missing collection: {name}')
        indexes[name] = {}
        for record in records:
            require(isinstance(record, dict), 'Invalid record.')
            identifier = record.get('id')
            require(isinstance(identifier, str) and bool(identifier) and identifier not in all_ids, 'Duplicate or invalid record ID.')
            require(record.get('snapshot_id') == snapshot, 'Mixed snapshots.')
            all_ids.add(identifier); indexes[name][identifier] = record
    require(len(indexes['passages']) <= 50 and len(indexes['relationships']) <= 50, 'Pack exceeds material capacity.')
    for source in indexes['sources'].values():
        rights = source.get('rights', {})
        require(isinstance(rights, dict), 'Invalid source rights.')
        require(source.get('content_type') == 'synthetic' and rights.get('external_ai') == 'allowed' and rights.get('export') == 'allowed' and rights.get('storage') == 'allowed', 'Source is not allowed for external AI and export.')
        require(isinstance(source.get('locator'), str) and bool(source['locator']), 'Missing source locator.')
    for name in ('entries', 'characters', 'passages', 'relationships'):
        for record in indexes[name].values():
            require(record.get('source_id') in indexes['sources'], 'Missing source record.')
            required = record.get('required_scope_ids')
            require(string_list(required) and bool(required) and set(required) <= set(package['scope_ids']), 'Record exceeds pack scope.')
    for passage in indexes['passages'].values():
        require(isinstance(passage.get('text'), str) and bool(passage['text']) and isinstance(passage.get('source_locator'), str) and bool(passage['source_locator']), 'Missing text or occurrence locator.')
        require(passage.get('entry_id') in indexes['entries'], 'Missing entry.')
        require('speaker_id' in passage and (passage['speaker_id'] is None or passage['speaker_id'] in indexes['characters']), 'Missing speaker identity.')
        require(string_list(passage.get('next_ids')) and set(passage['next_ids']) <= indexes['passages'].keys(), 'Dangling context link.')
        require('branch_id' in passage and (passage['branch_id'] is None or passage['branch_id'] in passage['required_scope_ids']), 'Invalid passage branch.')
    directions = {'mentor_of': 'directed', 'parent_of': 'directed', 'opposes': 'directed', 'cooperates_with': 'symmetric'}
    for relation in indexes['relationships'].values():
        require(relation.get('predicate') in directions and relation.get('direction') == directions[relation['predicate']], 'Invalid relation direction.')
        require(relation.get('from_id') in indexes['characters'] and relation.get('to_id') in indexes['characters'] and relation['from_id'] != relation['to_id'], 'Invalid endpoints.')
        require(relation.get('review_status') == 'approved' and relation.get('claim_kind') == 'explicit', 'Unreviewed or inferred relation.')
        require('branch_id' in relation and (relation['branch_id'] is None or relation['branch_id'] in relation['required_scope_ids']), 'Invalid relation branch.')
        groups = relation.get('evidence_groups')
        require(isinstance(groups, list) and bool(groups), 'Missing complete evidence group.')
        for group in groups:
            require(string_list(group) and bool(group) and set(group) <= indexes['passages'].keys(), 'Incomplete evidence group.')
            branches = {indexes['passages'][identifier]['branch_id'] for identifier in group} - {None}
            require(not branches or branches == {relation['branch_id']}, 'Evidence crosses incompatible branches.')
    return {'valid': True, 'mode': 'offline_unverified_current_state', 'snapshot_id': snapshot,
            'scope_ids': package['scope_ids'], 'counts': {name: len(records) for name, records in indexes.items()},
            'warning': '仅验证文件结构与声明的用途；文件可被修改，未联网核验来源真实性或最新撤下。原创样本不是原神事实。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--scope', action='append', required=True)
    args = parser.parse_args()
    try:
        with args.path.open('rb') as source:
            raw = source.read(4 * 1024 * 1024 + 1)
        require(len(raw) <= 4 * 1024 * 1024, 'Pack exceeds 4 MiB.')
        result = validate_pack(json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant), args.scope)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        print(json.dumps({'valid': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
