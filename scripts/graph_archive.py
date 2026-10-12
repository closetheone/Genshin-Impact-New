"""Bounded graph pages over the same authorized projection as reading/search."""
import re

from search_archive import decode_cursor, encode_cursor, fingerprint
from validate_sample import SampleError

MAX_NODES = 50
MAX_EDGES = 100
PREDICATES = {"mentor_of", "parent_of", "opposes", "cooperates_with"}
META = ("dataset_kind", "notice", "snapshot_id", "scope_ids", "purpose")


class GraphUnavailable(Exception):
    pass


def graph_options(arguments):
    defaults = {"center": "person:student", "hops": "1", "predicate": "all", "condition": "all", "page": "1", "cursor": ""}
    values = {}
    for name, default in defaults.items():
        supplied = arguments.get(name, [default])
        if len(supplied) != 1:
            raise SampleError("graph parameters must not repeat")
        values[name] = supplied[0]
    if not values["center"] or len(values["center"]) > 160:
        raise SampleError("invalid center")
    if values["hops"] not in ("1", "2") or values["predicate"] not in PREDICATES | {"all"}:
        raise SampleError("unsupported graph query")
    if values["condition"] not in ("all", "opening", "east", "west", "later"):
        raise SampleError("unsupported story condition")
    if not re.fullmatch(r"[0-9]{1,5}", values["page"]) or int(values["page"]) < 1:
        raise SampleError("invalid graph page")
    if len(values["cursor"]) > 1024 or ("cursor" in arguments and not values["cursor"]):
        raise SampleError("invalid graph cursor")
    if (values["cursor"] or int(values["page"]) > 1) and not arguments.get("snapshot", [""])[0]:
        raise SampleError("graph continuation requires an explicit snapshot")
    return {**values, "hops": int(values["hops"]), "page": int(values["page"])}


def conditioned(relation, condition):
    if condition == "all":
        return True
    if condition in ("east", "west"):
        return relation["branch_id"] == condition
    if condition == "later":
        return "later" in relation["required_scope_ids"]
    return relation["branch_id"] is None and set(relation["required_scope_ids"]) <= {"opening"}


def bundle(view, nodes, edges):
    evidence_ids = {identifier for relation in edges for group in relation["evidence_groups"] for identifier in group}
    passages = [{**passage, "next_ids": [identifier for identifier in passage["next_ids"] if identifier in evidence_ids]}
                for passage in view["passages"] if passage["id"] in evidence_ids]
    entry_ids = {passage["entry_id"] for passage in passages}
    return {"characters": nodes, "relationships": edges, "passages": passages,
            "entries": [entry for entry in view["entries"] if entry["id"] in entry_ids]}


def graph_view(view, options, secret):
    characters = {character["id"]: character for character in view["characters"]}
    center = options["center"]
    if center not in characters:
        raise GraphUnavailable("当前人物在此范围、用途或快照中不可用，请更换中心或手动调整范围。")
    candidates = [relation for relation in view["relationships"]
                  if (options["predicate"] == "all" or relation["predicate"] == options["predicate"])
                  and conditioned(relation, options["condition"])]
    distances = {center: 0}
    for depth in range(options["hops"]):
        frontier = set(distances)
        for relation in candidates:
            if relation["from_id"] in frontier:
                distances.setdefault(relation["to_id"], depth + 1)
            if relation["to_id"] in frontier:
                distances.setdefault(relation["from_id"], depth + 1)
    edges = [relation for relation in candidates if relation["from_id"] in distances and relation["to_id"] in distances]
    edges.sort(key=lambda relation: (max(distances[relation["from_id"]], distances[relation["to_id"]]), relation["id"]))
    # Each page is independently bounded and includes the center. Continuation replaces
    # the visible page; it never accumulates an unbounded client-side graph.
    pages = []
    page_edges, node_ids = [], {center}
    for relation in edges:
        endpoints = {relation["from_id"], relation["to_id"]}
        if len(page_edges) == MAX_EDGES or len(node_ids | endpoints) > MAX_NODES:
            pages.append((node_ids, page_edges))
            page_edges, node_ids = [], {center}
        page_edges.append(relation)
        node_ids |= endpoints
    pages.append((node_ids, page_edges))
    query = {name: value for name, value in options.items() if name not in ("cursor", "page")}
    binding = fingerprint({"kind": "graph", "query": query, "snapshot": view["snapshot_id"], "scope": view["scope_ids"], "purpose": view["purpose"]})
    revision = fingerprint(view)
    index = decode_cursor(options["cursor"], binding, revision, secret) if options["cursor"] else options["page"] - 1
    if index >= len(pages):
        raise GraphUnavailable("此局部图分页已不可用，请从第一页重新读取。")
    node_ids, page_edges = pages[index]
    nodes = sorted((characters[identifier] for identifier in node_ids), key=lambda node: (node["id"] != center, node["id"]))
    content = bundle(view, nodes, page_edges)
    cursor_at = lambda position: encode_cursor(position, binding, revision, secret)
    result = {**{key: view[key] for key in META}, **content, "query": {**query, "page": index + 1},
              "truncated": len(pages) > 1, "limits": {"nodes": MAX_NODES, "relationships": MAX_EDGES},
              "pagination": {"page": index + 1, "pages": len(pages), "total_nodes": len(distances), "total_relationships": len(edges),
                             "next_cursor": cursor_at(index + 1) if index + 1 < len(pages) else None,
                             "previous_cursor": cursor_at(index - 1) if index else None}}
    # Independent of purpose so an export projection must exactly match the currently
    # displayed content. Includes complete groups, text, labels and page metadata.
    revision_content = {key: value for key, value in result.items() if key not in ("purpose", "pagination")}
    revision_content["pagination"] = {key: value for key, value in result["pagination"].items() if not key.endswith("cursor")}
    result["content_revision"] = fingerprint(revision_content)
    return result


def relation_view(view, identifier):
    relation = next((item for item in view["relationships"] if item["id"] == identifier), None)
    if relation is None:
        raise GraphUnavailable("该关系或完整证据在当前范围、用途或快照中不可用。")
    nodes = [character for character in view["characters"] if character["id"] in (relation["from_id"], relation["to_id"])]
    return {**{key: view[key] for key in META}, **bundle(view, nodes, [relation])}


def character_view(view, query):
    if len(query) > 160:
        raise SampleError("character query too long")
    matches = [character for character in view["characters"] if query in character["name"] or query in character["id"]]
    return {**{key: view[key] for key in META}, "characters": matches[:20], "truncated": len(matches) > 20}
