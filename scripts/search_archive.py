import base64
import binascii
import hashlib
import heapq
import hmac
import json
import re
import unicodedata

from archive_store import StoreError, canonical_json
from validate_sample import SampleError


class StaleCursor(Exception):
    pass


def normalize_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def search_options(arguments):
    defaults = {"q": "", "mode": "literal", "category": "all", "speaker": "all", "limit": "8", "cursor": ""}
    values = {}
    for name, default in defaults.items():
        supplied = arguments.get(name, [default])
        if len(supplied) != 1:
            raise SampleError("search parameters must not repeat")
        values[name] = supplied[0]
    if len(values["q"]) > 200 or len(values["speaker"]) > 160 or not values["speaker"]:
        raise SampleError("query or speaker exceeds limits")
    if values["mode"] not in ("literal", "keywords") or values["category"] not in ("all", "quest"):
        raise SampleError("unsupported search mode or category")
    if not re.fullmatch(r"[0-9]{1,2}", values["limit"]) or not 1 <= int(values["limit"]) <= 50:
        raise SampleError("page size must be between 1 and 50")
    if len(values["cursor"]) > 1024 or ("cursor" in arguments and not values["cursor"]):
        raise SampleError("invalid cursor length")
    if values["cursor"] and "snapshot" not in arguments:
        raise SampleError("pagination requires an explicit snapshot")
    values["q"] = normalize_text(values["q"])
    values["limit"] = int(values["limit"])
    return values


def ordered_passages(passages):
    positions = {passage["id"]: position for position, passage in enumerate(passages)}
    incoming = {passage["id"]: 0 for passage in passages}
    for passage in passages:
        for following in passage["next_ids"]:
            if following in incoming:
                incoming[following] += 1
    ready = [positions[identifier] for identifier, degree in incoming.items() if degree == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        passage = passages[heapq.heappop(ready)]
        ordered.append(passage)
        for following in passage["next_ids"]:
            if following not in incoming:
                continue
            incoming[following] -= 1
            if incoming[following] == 0:
                heapq.heappush(ready, positions[following])
    if len(ordered) != len(passages):
        raise StoreError("Visible dialogue contains a cycle; search ordering is unavailable.")
    return ordered


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def encode_cursor(offset, binding, revision, secret):
    payload = canonical_json({"v": 1, "offset": offset, "binding": binding, "revision": revision}).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def decode_cursor(token, binding, revision, secret):
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[0-9a-f]{64}", token):
        raise SampleError("invalid cursor format")
    body, signature = token.split(".")
    expected = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SampleError("invalid cursor signature or server restarted")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise SampleError("invalid cursor payload") from error
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("binding") != binding:
        raise SampleError("cursor does not match query and boundary")
    if type(payload.get("offset")) is not int or payload["offset"] < 0:
        raise SampleError("invalid cursor offset")
    if payload.get("revision") != revision:
        raise StaleCursor("Visible content has changed; restart search instead of skipping results.")
    return payload["offset"]


def search_view(view, options, secret):
    query = {name: value for name, value in options.items() if name != "cursor"}
    binding = fingerprint({"query": query, "snapshot": view["snapshot_id"], "scope": view["scope_ids"], "purpose": view["purpose"]})
    revision = fingerprint(view)
    offset = decode_cursor(options["cursor"], binding, revision, secret) if options["cursor"] else 0
    entries = {entry["id"]: entry for entry in view["entries"]}
    speaker_counts = {}
    category_counts = {}
    for passage in view["passages"]:
        speaker = passage["speaker_id"] or "narration"
        category = entries[passage["entry_id"]]["category"]
        speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
    terms = query["q"].split() if query["mode"] == "keywords" else [query["q"]]
    matches = [
        passage for passage in ordered_passages(view["passages"])
        if (query["category"] == "all" or entries[passage["entry_id"]]["category"] == query["category"])
        and (query["speaker"] == "all" or (passage["speaker_id"] or "narration") == query["speaker"])
        and all(term in normalize_text(passage["text"]) for term in terms)
    ]
    if offset % query["limit"] or (offset and offset >= len(matches)):
        raise SampleError("cursor offset is outside the result set")
    results = matches[offset:offset + query["limit"]]
    page_entry_ids = {passage["entry_id"] for passage in results}
    characters = [character for character in view["characters"] if character["id"] in speaker_counts]
    cursor_at = lambda position: encode_cursor(position, binding, revision, secret)
    return {
        **{key: view[key] for key in ("dataset_kind", "notice", "snapshot_id", "scope_ids", "purpose")},
        "storage": "sqlite", "query": query, "results": results,
        "entries": [entry for entry in view["entries"] if entry["id"] in page_entry_ids],
        "characters": characters,
        "stats": {"passages": len(view["passages"]), "characters": len(view["characters"]), "relationships": len(view["relationships"])},
        "facets": {
            "categories": [{"value": category, "count": count} for category, count in sorted(category_counts.items())],
            "speakers": [{"value": identifier, "count": count} for identifier, count in sorted(speaker_counts.items())],
        },
        "pagination": {
            "total": len(matches), "offset": offset, "limit": query["limit"],
            "page": offset // query["limit"] + 1, "pages": max(1, (len(matches) + query["limit"] - 1) // query["limit"]),
            "next_cursor": cursor_at(offset + query["limit"]) if offset + query["limit"] < len(matches) else None,
            "previous_cursor": cursor_at(max(0, offset - query["limit"])) if offset else None,
        },
    }
