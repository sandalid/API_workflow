"""Normalise a Schemathesis run folder into structured, secret-free evidence.

Writes into the run folder:
  evidence.json   one record per executed request: role, method, path template, inputs, response status/
                  headers/body (bounded), every check outcome, execution errors, auth bootstrap result
  run.json        run manifest: run id, EP, role, times, environment host, spec version + SHA-256,
                  fixtures SHA-256 + references, tool version, seed, auth status, execution errors
  spec.snapshot.json / fixtures.snapshot.json   exact inputs used by this run

Credentials/tokens are never stored: Authorization values are already filtered by Schemathesis; this script
additionally masks token-like keys and JWT/Bearer strings in every saved artefact.

Usage:
  python evidence_export.py <run_dir> --run-id RUN-... --ep EP-038 --role user --spec spec.json
         --fixtures fixtures.json --base-url https://... --exit-code 1 --started ISO --finished ISO
"""
import argparse, base64, copy, glob, hashlib, json, os, re, shutil, sys
from urllib.parse import urlparse

BODY_LIMIT = 65536
SENSITIVE_KEYS = {"token", "accesstoken", "refreshtoken", "idtoken", "access_token", "refresh_token", "id_token",
                  "password", "secret", "authorization", "apikey", "api_key", "otp", "code"}
JWT_RE = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}")
BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}", re.I)
MASK = "[REDACTED]"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def mask_text(s):
    return BEARER_RE.sub(r"\1" + MASK, JWT_RE.sub(MASK, s))


def mask_obj(o, top_level_code_ok=False):
    """Recursively mask sensitive keys and token-like strings. 'code' is only masked inside objects that
    also carry a token/otp-like sibling (login/otp responses), to avoid hiding unrelated 'code' fields."""
    if isinstance(o, dict):
        sibling_secret = any(k.lower() in SENSITIVE_KEYS - {"code"} for k in o)
        out = {}
        for k, v in o.items():
            kl = k.lower()
            if kl in SENSITIVE_KEYS and (kl != "code" or sibling_secret or top_level_code_ok):
                out[k] = MASK
            else:
                out[k] = mask_obj(v)
        return out
    if isinstance(o, list):
        return [mask_obj(v) for v in o]
    if isinstance(o, str):
        return mask_text(o)
    return o


def decode_content(content):
    """Schemathesis stores bodies as {"$base64": "..."} (or plain). Returns (text|None, bytes_len)."""
    if content is None:
        return None, 0
    if isinstance(content, dict) and "$base64" in content:
        raw = base64.b64decode(content["$base64"])
        return raw.decode("utf-8", errors="replace"), len(raw)
    if isinstance(content, str):
        return content, len(content.encode("utf-8"))
    return json.dumps(content), 0


def redact_ndjson(path):
    """Rewrite an ndjson event log with secrets masked (including inside base64 JSON bodies)."""
    out, n = [], 0
    with open(path, encoding="utf-8") as fh: lines = fh.readlines()
    for line in lines:
        if not line.strip():
            continue
        e = json.loads(line)
        s = json.dumps(e, ensure_ascii=False)
        e2 = _redact_event(e)
        if json.dumps(e2, ensure_ascii=False) != s:
            n += 1
        out.append(json.dumps(e2, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return n


def _redact_event(o):
    if isinstance(o, dict):
        if set(o) == {"$base64"}:
            text, _ = decode_content(o)
            try:
                orig = json.loads(text)
                masked = mask_obj(orig)
                if masked == orig:
                    return o                      # nothing secret in this body: keep bytes untouched
                red = json.dumps(masked, ensure_ascii=False)
            except ValueError:
                red = mask_text(text)
                if red == text:
                    return o
            return {"$base64": base64.b64encode(red.encode("utf-8")).decode("ascii")}
        return {k: (MASK if k.lower() in SENSITIVE_KEYS - {"code"} and not isinstance(v, (dict, list)) else _redact_event(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [_redact_event(v) for v in o]
    if isinstance(o, str):
        return mask_text(o)
    return o


def redact_text_files(run_dir):
    n = 0
    for p in glob.glob(os.path.join(run_dir, "**", "*"), recursive=True):
        if os.path.isfile(p) and p.lower().endswith((".xml", ".html", ".json", ".txt", ".csv", ".har", ".yaml", ".yml")) \
                and os.path.basename(p) not in ("evidence.json", "run.json"):
            try:
                with open(p, encoding="utf-8") as f: t = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            t2 = mask_text(t)
            if t2 != t:
                with open(p, "w", encoding="utf-8") as f: f.write(t2)
                n += 1
    return n


def _body(content, ctype):
    text, size = decode_content(content)
    if text is None:
        return {"text": None, "json": None, "truncated": False, "size": 0}
    truncated = size > BODY_LIMIT
    js = None
    if not truncated:
        try:
            js = mask_obj(json.loads(text))
        except ValueError:
            js = None
    return {"text": mask_text(text[:BODY_LIMIT]), "json": js, "truncated": truncated, "size": size}


def normalize_ndjson(path):
    """-> (interactions, run_facts). Pure function over the saved ndjson; no network."""
    facts = {"schemathesis_version": None, "seed": None, "stop_reason": None, "spec_kind": None,
             "spec_openapi_version": None, "auth_bootstrap": None, "phases": {}, "errors": []}
    inter = []
    with open(path, encoding="utf-8") as fh: lines = fh.readlines()
    for line in lines:
        if not line.strip():
            continue
        ev = json.loads(line)
        k = next(iter(ev))
        v = ev[k]
        if k == "Initialize":
            facts["schemathesis_version"], facts["seed"] = v.get("schemathesis_version"), v.get("seed")
        elif k == "LoadingFinished":
            sp = v.get("specification") or {}
            facts["spec_kind"], facts["spec_openapi_version"] = sp.get("kind"), sp.get("version")
        elif k == "EngineFinished":
            facts["stop_reason"] = v.get("stop_reason")
        elif k == "PhaseFinished":
            ph = (v.get("phase") or {}).get("name")
            facts["phases"][ph] = v.get("status")
            if ph == "auth_bootstrap":
                facts["auth_bootstrap"] = (v.get("payload") or {}).get("status") or v.get("status")
            if v.get("status") in ("error", "interrupted"):
                facts["errors"].append({"kind": f"phase_{v.get('status')}", "phase": ph,
                                        "message": mask_text(str(v.get("payload") or v.get("error") or ""))[:300]})
        elif k == "ScenarioFinished":
            rec = v.get("recorder") or {}
            if v.get("status") in ("error", "interrupted"):
                facts["errors"].append({"kind": "scenario_" + v["status"], "phase": v.get("phase"),
                                        "operation": rec.get("label"),
                                        "message": mask_text(str(v.get("error") or v.get("errors") or rec.get("errors") or ""))[:300]})
            for cid, c in (rec.get("cases") or {}).items():
                val = c.get("value") or {}
                meta = val.get("meta") or {}
                it = (rec.get("interactions") or {}).get(cid) or {}
                req, resp = it.get("request") or {}, it.get("response")
                hdr_names = {h.lower() for h in (req.get("headers") or {})} | {h.lower() for h in (val.get("headers") or {})}
                checks = []
                for ch in (rec.get("checks") or {}).get(cid, []):
                    fi = (ch.get("failure_info") or {}).get("failure") or {}
                    checks.append({"name": ch.get("name"), "status": ch.get("status"), "code": fi.get("code"),
                                   "message": mask_text(" ".join((fi.get("message") or "").split()))[:400] or None})
                rec_i = {"id": cid, "phase": v.get("phase"), "operation": rec.get("label"),
                         "method": (val.get("method") or req.get("method") or "").upper(),
                         "path_template": val.get("path"), "path_params": val.get("path_parameters") or {},
                         "query": val.get("query") or {}, "uri": req.get("uri"),
                         "request_header_names": sorted(hdr_names), "has_auth": "authorization" in hdr_names,
                         "request_body": mask_obj(val.get("body")) if val.get("body") is not None else None,
                         "generation_mode": (meta.get("generation") or {}).get("mode"),
                         "scenario": ((meta.get("phase") or {}).get("data") or {}).get("description"),
                         "response": None, "checks": checks, "error": None}
                if resp:
                    ct = ((resp.get("headers") or {}).get("content-type") or [""])[0]
                    rec_i["response"] = {"status": resp.get("status_code"),
                                         "headers": {h: (vals[0] if isinstance(vals, list) and vals else vals)
                                                     for h, vals in (resp.get("headers") or {}).items()
                                                     if h.lower() not in ("set-cookie", "authorization")},
                                         "elapsed": resp.get("elapsed"), "body": _body(resp.get("content"), ct)}
                else:
                    rec_i["error"] = {"kind": "no_response", "message": "request produced no recorded response"}
                    facts["errors"].append({"kind": "no_response", "phase": v.get("phase"), "case_id": cid,
                                            "operation": rec.get("label"), "message": "request produced no recorded response"})
                if any(ch["status"] == "error" for ch in checks):
                    rec_i["error"] = rec_i["error"] or {"kind": "check_error", "message": "a check raised an error"}
                    facts["errors"].append({"kind": "check_error", "phase": v.get("phase"), "case_id": cid,
                                            "message": "a check raised an error"})
                inter.append(rec_i)
    return inter, facts


def build(run_dir, run_id, ep, role, spec=None, fixtures=None, base_url=None, exit_code=None,
          started=None, finished=None, flags=None):
    nd = glob.glob(os.path.join(run_dir, "ndjson-*.ndjson"))
    if not nd:
        raise SystemExit(f"no ndjson in {run_dir}")
    redacted = redact_ndjson(nd[0])
    interactions, facts = normalize_ndjson(nd[0])
    for e in interactions:
        e["role"] = role
    auth = {"role": role, "status": "unknown", "bootstrap_phase": facts["auth_bootstrap"]}
    ap = os.path.join(run_dir, "auth_status.json")
    if os.path.exists(ap):
        with open(ap, encoding="utf-8") as f: a = json.load(f)
        auth.update(status=a.get("status"), method=a.get("method"), error=a.get("error"))
    elif role == "anon":
        auth["status"] = "anonymous-explicit"
    manifest = {"run_id": run_id, "ep": ep, "role": role, "started": started, "finished": finished,
                "exit_code": exit_code, "schemathesis_version": facts["schemathesis_version"], "seed": facts["seed"],
                "environment_host": urlparse(base_url).netloc if base_url else None, "flags": flags,
                "stop_reason": facts["stop_reason"], "phases": facts["phases"], "auth": auth,
                "execution_errors": facts["errors"], "interactions": len(interactions),
                "spec": None, "fixtures": None, "evidence_file": "evidence.json"}
    if spec and os.path.exists(spec):
        snap = os.path.join(run_dir, "spec.snapshot.json")
        shutil.copyfile(spec, snap)
        with open(spec, encoding="utf-8") as f: sd = json.load(f)
        manifest["spec"] = {"snapshot": "spec.snapshot.json", "sha256": sha256_file(spec),
                            "openapi_version": sd.get("openapi"), "info_version": (sd.get("info") or {}).get("version"),
                            "source_url_host": None}
    if fixtures and os.path.exists(fixtures):
        shutil.copyfile(fixtures, os.path.join(run_dir, "fixtures.snapshot.json"))
        with open(fixtures, encoding="utf-8-sig") as f: fd = json.load(f)
        manifest["fixtures"] = {"snapshot": "fixtures.snapshot.json", "sha256": sha256_file(fixtures),
                                "states": sorted(set((fd.get("_states") or {}).values())),
                                "operations": [k for k in fd if not k.startswith("_")]}
    complete = facts["stop_reason"] in ("completed", None) and not facts["errors"]
    manifest["status"] = ("auth_failed" if auth["status"] == "failed" or facts["auth_bootstrap"] in ("failure", "error")
                          else "completed" if complete else "completed_with_errors")
    manifest["redaction"] = {"ndjson_events_masked": redacted, "text_files_masked": redact_text_files(run_dir)}
    with open(os.path.join(run_dir, "evidence.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "schema_version": 1, "interactions": interactions,
                   "execution_errors": facts["errors"]}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    for a in ("run-id", "ep", "role", "spec", "fixtures", "base-url", "exit-code", "started", "finished", "flags"):
        ap.add_argument("--" + a)
    a = ap.parse_args()
    m = build(a.run_dir, a.run_id or os.path.basename(a.run_dir), a.ep, a.role or "user", a.spec, a.fixtures, a.base_url,
              int(a.exit_code) if a.exit_code is not None else None, a.started, a.finished, a.flags)
    print(f"{m['run_id']}: status={m['status']} interactions={m['interactions']} errors={len(m['execution_errors'])} "
          f"auth={m['auth']['status']}")
