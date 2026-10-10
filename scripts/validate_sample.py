import argparse
import json
import sys
from pathlib import Path


class SampleError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SampleError(message)


def string_list(value, label, nonempty=False):
    require(isinstance(value, list), f"{label}: expected a list")
    require(all(isinstance(item, str) and item for item in value), f"{label}: invalid identifier")
    require(len(value) == len(set(value)), f"{label}: duplicate identifier")
    require(not nonempty or bool(value), f"{label}: cannot be empty")
    return value


def record_index(data, collection, snapshot_id):
    records = data.get(collection)
    require(isinstance(records, list) and records, f"{collection}: expected nonempty records")
    result = {}
    for record in records:
        require(isinstance(record, dict), f"{collection}: expected an object")
        identifier = record.get("id")
        require(isinstance(identifier, str) and identifier, f"{collection}: missing id")
        require(identifier not in result, f"{collection}: duplicate id {identifier}")
        require(record.get("snapshot_id") == snapshot_id, f"{identifier}: mixed snapshot")
        result[identifier] = record
    return result


def validate(data):
    require(isinstance(data, dict), "dataset: expected an object")
    require(data.get("schema_version") == "0.1", "unsupported schema_version")
    require(data.get("dataset_kind") == "synthetic", "v0.1 accepts synthetic fixtures only")
    require(data.get("language") == "zh-CN", "unsupported language")
    require(isinstance(data.get("notice"), str) and data["notice"], "missing synthetic notice")
    snapshot_id = data.get("snapshot_id")
    require(isinstance(snapshot_id, str) and snapshot_id, "missing snapshot_id")
    scopes = set(string_list(data.get("scope_ids"), "scope_ids", nonempty=True))
    branches = set(string_list(data.get("branch_ids"), "branch_ids"))
    require(branches <= scopes, "branch_ids must also be scope_ids")
    indexes = {
        collection: record_index(data, collection, snapshot_id)
        for collection in ("sources", "entries", "characters", "passages", "relationships")
    }
    all_ids = [identifier for records in indexes.values() for identifier in records]
    require(len(all_ids) == len(set(all_ids)), "identifiers must be globally unique")
    withdrawn = set(string_list(data.get("withdrawn_ids"), "withdrawn_ids"))
    require(withdrawn <= set(all_ids), "withdrawn_ids contains unknown identifiers")

    for source in indexes["sources"].values():
        require(source.get("content_type") == "synthetic", f"{source['id']}: not synthetic")
        require(isinstance(source.get("locator"), str) and source["locator"], f"{source['id']}: missing locator")
        rights = source.get("rights")
        require(isinstance(rights, dict), f"{source['id']}: missing rights")
        require(set(rights) == {"storage", "display", "export", "external_ai"}, f"{source['id']}: incomplete rights")
        require(all(value in ("allowed", "denied", "unknown") for value in rights.values()), f"{source['id']}: invalid rights")
        require(rights["storage"] == "allowed", f"{source['id']}: storage is not allowed")

    for collection in ("entries", "characters", "passages", "relationships"):
        for record in indexes[collection].values():
            required = set(string_list(record.get("required_scope_ids"), f"{record['id']}.required_scope_ids", nonempty=True))
            require(required <= scopes, f"{record['id']}: unknown scope")
            require(record.get("source_id") in indexes["sources"], f"{record['id']}: unknown source")

    for entry in indexes["entries"].values():
        require(isinstance(entry.get("title"), str) and entry["title"], f"{entry['id']}: missing title")
        require(entry.get("category") == "quest", f"{entry['id']}: unsupported category")
    for character in indexes["characters"].values():
        require(isinstance(character.get("name"), str) and character["name"], f"{character['id']}: missing name")

    positions = {passage["id"]: position for position, passage in enumerate(data["passages"])}
    for passage in indexes["passages"].values():
        identifier = passage["id"]
        require(passage.get("entry_id") in indexes["entries"], f"{identifier}: unknown entry")
        require(isinstance(passage.get("text"), str) and passage["text"], f"{identifier}: missing text")
        require(isinstance(passage.get("source_locator"), str) and passage["source_locator"], f"{identifier}: missing source locator")
        expected_locator = f"{indexes['sources'][passage['source_id']]['locator']}#/passages/{positions[identifier]}"
        require(passage["source_locator"] == expected_locator, f"{identifier}: source locator does not point to this occurrence")
        require("speaker_id" in passage, f"{identifier}: speaker_id must be explicit or null")
        require(passage["speaker_id"] is None or passage["speaker_id"] in indexes["characters"], f"{identifier}: unknown speaker")
        require("branch_id" in passage, f"{identifier}: missing branch_id")
        require(passage["branch_id"] is None or passage["branch_id"] in branches, f"{identifier}: unknown branch")
        require(passage["branch_id"] is None or passage["branch_id"] in passage["required_scope_ids"], f"{identifier}: branch scope missing")
        for next_id in string_list(passage.get("next_ids"), f"{identifier}.next_ids"):
            require(next_id in indexes["passages"], f"{identifier}: dangling next_id")
            following = indexes["passages"][next_id]
            require(following["entry_id"] == passage["entry_id"], f"{identifier}: next passage crosses entries")
            require(not (passage["branch_id"] and following.get("branch_id") and passage["branch_id"] != following["branch_id"]), f"{identifier}: next passage crosses exclusive branches")

    predicates = {"mentor_of": "directed", "parent_of": "directed", "opposes": "directed", "cooperates_with": "symmetric"}
    signatures = set()
    for relation in indexes["relationships"].values():
        identifier = relation["id"]
        source_id, target_id = relation.get("from_id"), relation.get("to_id")
        require(source_id in indexes["characters"] and target_id in indexes["characters"], f"{identifier}: unknown character")
        require(source_id != target_id, f"{identifier}: self relationship")
        require(relation.get("predicate") in predicates, f"{identifier}: unknown predicate")
        require(relation.get("direction") == predicates[relation["predicate"]], f"{identifier}: predicate/direction mismatch")
        require(relation.get("review_status") in ("approved", "pending", "rejected"), f"{identifier}: invalid review_status")
        require(relation.get("claim_kind") in ("explicit", "inference", "disputed"), f"{identifier}: invalid claim_kind")
        require(isinstance(relation.get("description"), str) and relation["description"], f"{identifier}: missing description")
        require("branch_id" in relation, f"{identifier}: missing branch_id")
        require(relation["branch_id"] is None or relation["branch_id"] in branches, f"{identifier}: unknown branch")
        require(relation["branch_id"] is None or relation["branch_id"] in relation["required_scope_ids"], f"{identifier}: branch scope missing")
        groups = relation.get("evidence_groups")
        require(isinstance(groups, list) and groups, f"{identifier}: missing evidence groups")
        for group in groups:
            string_list(group, f"{identifier}.evidence_group", nonempty=True)
            require(all(passage_id in indexes["passages"] for passage_id in group), f"{identifier}: missing evidence passage")
            evidence_branches = {indexes["passages"][passage_id]["branch_id"] for passage_id in group} - {None}
            require(not evidence_branches or evidence_branches == {relation["branch_id"]}, f"{identifier}: incompatible evidence branches")
        endpoints = tuple(sorted((source_id, target_id))) if relation["direction"] == "symmetric" else (source_id, target_id)
        signature = (endpoints, relation["predicate"], relation["branch_id"], tuple(sorted(relation["required_scope_ids"])))
        require(signature not in signatures, f"{identifier}: duplicate relationship assertion")
        signatures.add(signature)
    return indexes


def project(data, allowed_scopes, purpose="display"):
    indexes = validate(data)
    require(purpose in ("display", "export", "external_ai"), "unsupported purpose")
    allowed_scopes = set(allowed_scopes)
    require(allowed_scopes <= set(data["scope_ids"]), "unknown requested scope")
    withdrawn = set(data["withdrawn_ids"])

    def visible(record):
        source = indexes["sources"][record["source_id"]]
        return (
            record["id"] not in withdrawn
            and source["id"] not in withdrawn
            and set(record["required_scope_ids"]) <= allowed_scopes
            and source["rights"][purpose] == "allowed"
        )

    entries = {identifier: entry for identifier, entry in indexes["entries"].items() if visible(entry)}
    characters = {identifier: character for identifier, character in indexes["characters"].items() if visible(character)}
    passages = {
        identifier: passage for identifier, passage in indexes["passages"].items()
        if visible(passage) and passage["entry_id"] in entries
        and (passage["speaker_id"] is None or passage["speaker_id"] in characters)
    }
    projected_passages = [
        {**passage, "next_ids": [identifier for identifier in passage["next_ids"] if identifier in passages]}
        for passage in passages.values()
    ]
    relationships = []
    for relation in indexes["relationships"].values():
        if not visible(relation) or relation["review_status"] != "approved" or relation["claim_kind"] != "explicit":
            continue
        if relation["from_id"] not in characters or relation["to_id"] not in characters:
            continue
        groups = [group for group in relation["evidence_groups"] if all(identifier in passages for identifier in group)]
        if groups:
            relationships.append({**relation, "evidence_groups": groups})
    return {
        "dataset_kind": data["dataset_kind"], "notice": data["notice"],
        "snapshot_id": data["snapshot_id"], "scope_ids": sorted(allowed_scopes), "purpose": purpose,
        "entries": list(entries.values()), "characters": list(characters.values()),
        "passages": projected_passages, "relationships": relationships,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate synthetic narrative fixtures; never certifies real game facts or rights.")
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).resolve().parents[1] / "data/samples/story.json")
    parser.add_argument("--scope", action="append", help="Allowed scope; repeat as needed, or use all for this synthetic fixture")
    parser.add_argument("--purpose", choices=("display", "export", "external_ai"), default="display")
    parser.add_argument("--view", action="store_true", help="Print the filtered sample, including its graph records")
    parser.add_argument("--query", help="Normalized literal substring search within the filtered sample")
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
        indexes = validate(data)
        result = {"valid": True, "dataset_kind": data["dataset_kind"], "snapshot_id": data["snapshot_id"], "counts": {name: len(records) for name, records in indexes.items()}}
        if args.view or args.query is not None:
            require(bool(args.scope), "--view/--query requires explicit --scope")
            require("all" not in args.scope or args.scope == ["all"], "do not mix all with named scopes")
            scopes = data["scope_ids"] if args.scope == ["all"] else args.scope
            view = project(data, scopes, args.purpose)
            if args.query is not None:
                query = " ".join(args.query.split())
                require(bool(query), "query cannot be empty")
                result = {"dataset_kind": data["dataset_kind"], "snapshot_id": data["snapshot_id"], "scope_ids": view["scope_ids"], "purpose": args.purpose, "matches": [passage for passage in view["passages"] if query in " ".join(passage["text"].split())]}
            else:
                result = view
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
