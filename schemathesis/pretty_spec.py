"""Write a human/agent-readable copy of the OpenAPI spec next to it.

The spec the backend serves is ONE line of ~160 KB, and the search/read tools used by the agents silently skip lines that long - so
audits could not see the contract at all ("OpenAPI: not verified"). spec/openapi.pretty.json has the same content, indented, one
property per line. It is regenerated whenever the spec is fetched; the original stays the file Schemathesis runs against.

Usage: python pretty_spec.py [spec/openapi.json]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "spec", "openapi.json")
dst = os.path.join(os.path.dirname(os.path.abspath(src)), "openapi.pretty.json")
with open(src, encoding="utf-8") as f: spec = json.load(f)
with open(dst, "w", encoding="utf-8") as f: json.dump(spec, f, indent=1, ensure_ascii=False)
print(f"{dst}: {len(spec.get('paths', {}))} paths, {sum(1 for p in spec['paths'].values() for m in p if m in ('get','post','put','patch','delete'))} operations")
