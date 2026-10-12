"""Portable standard-library client for the bounded, read-only AI endpoint."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

TOOLS = ('get_corpus_status', 'search_texts', 'get_passage', 'get_story_context', 'get_character_graph', 'get_relationship')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        return None


def call_tool(base_url, name, arguments):
    parsed = urlsplit(base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or not parsed.port:
        raise ValueError('Use an explicit local HTTP host and port; remote URLs and credentials are unsupported.')
    if name not in TOOLS or not isinstance(arguments, dict):
        raise ValueError('Unknown tool or invalid arguments.')
    body = json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(body) > 65536:
        raise ValueError('Request exceeds 64 KiB.')
    origin = f'http://{parsed.netloc}'
    request = Request(origin + '/api/ai-tools', data=body, headers={'Content-Type': 'application/json', 'Origin': origin})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Tool response exceeds 4 MiB; narrow the query.')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Expected a tool response object.')
        if response.status != 200:
            raise ValueError(f"Tool request failed ({response.status}): {value.get('error', 'unavailable')}")
    if not isinstance(value, dict) or value.get('purpose') != 'external_ai' or value.get('connection') != 'live_readonly':
        raise ValueError('Not a verified read-only AI tool response; no fallback to the website view.')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Explicit local archive origin, e.g. http://127.0.0.1:4173')
    parser.add_argument('--tool', required=True, choices=TOOLS)
    parser.add_argument('--arguments', default='{}', help='JSON object; scope_ids may only narrow the server session')
    args = parser.parse_args()
    try:
        print(json.dumps(call_tool(args.url, args.tool, json.loads(args.arguments)), ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, OSError, URLError, RecursionError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
