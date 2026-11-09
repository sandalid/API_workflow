"""Inject fixtures.json values as OpenAPI examples so Schemathesis's examples phase
(and explicit-example generation) hits real resources.
Usage: python apply_fixtures.py <spec.json> <fixtures.json> <out.json>"""
import json, sys

spec_f, fx_f, out_f = sys.argv[1:4]
spec = json.load(open(spec_f, encoding="utf-8"))
fx = {k: v for k, v in json.load(open(fx_f, encoding="utf-8-sig")).items() if not k.startswith("_")}
applied = 0
for key, cfg in fx.items():
    method, path = key.split(" ", 1)
    op = spec.get("paths", {}).get(path, {}).get(method.lower())
    if not op:
        print(f"WARN fixture target not in spec: {key}"); continue
    for where in ("path", "query", "header"):
        for name, values in (cfg.get(where) or {}).items():
            values = values if isinstance(values, list) else [values]
            for p in op.setdefault("parameters", []) + spec["paths"][path].get("parameters", []):
                if p.get("in") == where and p.get("name") == name:
                    p["examples"] = {f"fixture{i}": {"value": v} for i, v in enumerate(values)}
                    applied += 1
json.dump(spec, open(out_f, "w", encoding="utf-8"))
print(f"fixtures applied to {applied} parameter(s)")
