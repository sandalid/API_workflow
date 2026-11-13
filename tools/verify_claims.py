"""Verify the factual claims an AI step wrote down - deterministically, no AI involved.

1. CITATIONS (audits, reports):  python tools/verify_claims.py audits/EP-038.md
   Every `path:line` / `path:start-end` / `path:12,40` (and bare `:N` that inherits the previous file) must
     * resolve to a real file (headings such as "### Backend (`...\\apps\\api\\src`)" set the base folder),
     * point inside the file,
     * contain the symbol quoted next to it - the backticked token(s) in the parenthetical right after the citation,
       or the backticked token right before it ("`NOT_DELETED` (`file.ts:60`)").
   Statuses: OK | OK_LOCATION_ONLY (nothing quoted to check) | WARN_PARTIAL (some symbols found) |
             WARN_DRIFT (symbol found within +-N lines: the line moved) | WARN_ENCLOSING (the cited lines sit inside the
             quoted function/class, not on a line naming it) | WARN_AMBIGUOUS (several files match) |
             WARN_NOFILE (a bare ':N' with no file on the same line) |
             FAIL_FILE | FAIL_LINE (beyond end of file) | FAIL_SYMBOL (quoted symbol not at the cited lines) |
             FAIL_NEGATION (the audit says a symbol is absent - 'no `x` field' - but it is at the cited lines).
2. REFERENCES (reports/coverage docs): --refs  TC ids exist in the workbook, RUN ids / run folders exist, BUG ids defined.
3. TALLY: --tally EP-038  authoritative counts (workbook results; failing checks per role/code from the run evidence)
   so agents quote numbers instead of counting by hand.

Exit code: 0 ok, 1 at least one FAIL (with --strict: any WARN too), 2 usage/config error.
Roots come from tools/verify_claims.config.json (or --root / env VERIFY_ROOTS, ';' separated).
"""
import argparse, collections, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONFIG = os.path.join(HERE, "verify_claims.config.json")
EXT = r"(?:tsx?|jsx?|mjs|cjs|prisma|sql|md|json|ya?ml|css|scss|py|ps1|csv)"
PATH_RE = r"(?:[\w.@\[\]()+~-]+[\\/])*[\w.@\[\]()+~-]+\." + EXT
LINES_RE = r"\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*"
FILE_CIT = re.compile(r"(?<![\w/\\.])(" + PATH_RE + r"):(" + LINES_RE + r")(?!\d)")
BARE_CIT = re.compile(r"(?<![\w/\\.])`:(" + LINES_RE + r")`")
TICK = re.compile(r"`([^`]+)`")
IDENT = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")
STOP = set("""where true false null undefined void this from with const let var return async await export import default class interface type
function new else case when then only none never also etc GET POST PUT PATCH DELETE HTTP HTTPS JSON NULL TRUE FALSE and the for not are
has have its any all can may line lines file files used unused field fields value values item items code note see per vs via nor""".split())
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".expo", "coverage", "uploads", "__pycache__", ".hypothesis",
             ".schemathesis", "results", "backups", ".turbo", ".cache", "ios", "android", "Pods"}
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".prisma", ".sql", ".md", ".json", ".yaml", ".yml", ".css", ".scss", ".py", ".ps1", ".csv"}


# ------------------------------------------------------------------ config / index
def load_roots(cli_roots=None):
    roots = []
    if cli_roots: roots += cli_roots
    if os.environ.get("VERIFY_ROOTS"): roots += os.environ["VERIFY_ROOTS"].split(";")
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f: cfg = json.load(f)
        if not cli_roots and not os.environ.get("VERIFY_ROOTS"): roots += cfg.get("roots", [])
    roots.append(REPO)
    seen, out = set(), []
    for r in roots:
        r = os.path.abspath(r)
        if r.lower() not in seen and os.path.isdir(r): seen.add(r.lower()); out.append(r)
    return out, int(cfg.get("drift_lines", 15))


class Index:
    def __init__(self, roots):
        self.roots, self.by_name, self._lines = roots, collections.defaultdict(list), {}
        for root in roots:
            for dp, dn, fn in os.walk(root):
                dn[:] = [d for d in dn if d not in SKIP_DIRS]
                for f in fn:
                    if os.path.splitext(f)[1].lower() in CODE_EXT: self.by_name[f.lower()].append(os.path.join(dp, f))

    def lines(self, path):
        if path not in self._lines:
            with open(path, encoding="utf-8", errors="replace") as f: self._lines[path] = f.read().split("\n")
        return self._lines[path]


def norm(p): return p.replace("\\", "/")


def resolve(cit_path, bases, roots, index, hint):
    """Find the file a citation points to. Tries the section base folders, the roots, then the longest path suffix
    (leading alias segments such as 'droplight\\apps\\api\\...' or 'web/lib/...' are dropped and used as hints)."""
    n = norm(cit_path).lstrip("./")
    segs = n.split("/")
    found = []
    def add(p):
        if os.path.isfile(p) and os.path.abspath(p) not in found: found.append(os.path.abspath(p))
    for b in bases: add(os.path.join(b, n))
    if not found:
        for r in roots: add(os.path.join(r, n))
    dropped = []
    if not found:
        for k in range(len(segs)):
            sub = "/".join(segs[k:])
            for p in index.by_name.get(segs[-1].lower(), []):
                if norm(p).lower().endswith("/" + sub.lower()) or ("/" not in sub and os.path.basename(p).lower() == sub.lower()): add(p)
            if found: dropped = segs[:k]; break
    hints = list(hint or [])
    for d in dropped:
        hints += hints_from(d)
    if len(found) > 1 and hints:
        pref = [p for p in found if any(h in norm(p).lower() for h in hints)]
        if pref: found = pref
    return found


# ------------------------------------------------------------------ parsing
def symbols_in(token):
    if re.search(r"[\\/]", token) or re.search(r"\." + EXT + r"\b", token): return []
    out = []
    for m in IDENT.findall(token):
        last = m.split(".")[-1]
        if m in STOP or last in STOP: continue
        if len(last) >= 4 or "_" in last or re.search(r"[a-z][A-Z]", last): out.append(m)
    return list(dict.fromkeys(out))


def heading_bases(heading, roots):
    bases = []
    for t in TICK.findall(heading):
        t = t.strip()
        if re.search(r"\.\w{1,5}$", t) or ":" in t.replace(":\\", "").replace(":/", ""): continue
        cand = [t] if os.path.isabs(t) else [os.path.join(r, t) for r in roots]
        for c in cand:
            c = os.path.normpath(c)
            if os.path.isdir(c) and c not in bases: bases.append(c)
    return bases


def hints_from(text):
    t = text.lower(); h = []
    if "mobile" in t: h.append("apps/mobile")
    if re.search(r"\b(web|admin|next)", t): h.append("apps/web")
    if re.search(r"backend|\bapi\b|nest", t): h.append("apps/api")
    return h


def parse_line(line):
    """-> list of citation dicts for one markdown line"""
    spans = []
    for m in FILE_CIT.finditer(line): spans.append({"kind": "file", "path": m.group(1), "refs": m.group(2), "start": m.start(), "end": m.end()})
    for m in BARE_CIT.finditer(line):
        if not any(s["start"] <= m.start() < s["end"] for s in spans):
            spans.append({"kind": "bare", "path": None, "refs": m.group(1), "start": m.start(), "end": m.end()})
    spans.sort(key=lambda s: s["start"])
    ticks = [(m.start(), m.end(), m.group(1)) for m in TICK.finditer(line)]
    used = set()
    def free_ticks(lo, hi):
        return [t for t in ticks if t[0] >= lo and t[1] <= hi and t[0] not in used
                and not FILE_CIT.search(t[2]) and not BARE_CIT.search("`" + t[2] + "`") and not re.fullmatch(r":" + LINES_RE, t[2].strip())]
    for i, s in enumerate(spans):
        nxt = spans[i + 1]["start"] if i + 1 < len(spans) else len(line)
        prev_end = spans[i - 1]["end"] if i else 0
        syms, neg = [], []
        # a) parenthetical right after the citation (skip the closing backtick of a bare citation)
        after = line[s["end"]:nxt]
        m = re.match(r"`?\s*\(([^)]*)\)", after)
        if m:
            lo = s["end"] + m.start(1); hi = s["end"] + m.end(1)
            prev_end, prev_neg = lo, False
            for t in free_ticks(lo, hi):
                found = symbols_in(t[2]); syms += found; used.add(t[0])
                direct = re.search(r"\b(no|not|without|missing|absent|lacks?|neither|nor)\s+(?:[\w-]+\s+){0,2}$", line[prev_end:t[0]], re.I) \
                    if "`" not in line[prev_end:t[0]] else None
                joined = prev_neg and re.fullmatch(r"[\s,/&]*(?:or|and|nor)?[\s,/&]*", line[prev_end:t[0]]) is not None
                prev_neg = bool(direct) or bool(joined)
                prev_end = t[1]
                if prev_neg: neg += found
        # b) a backticked token immediately before ("`SYMBOL` (`file:line`)")
        if not syms:
            before = line[prev_end:s["start"]]
            mb = re.search(r"`([^`]+)`[^`\w]{0,12}$", before.rstrip("`") + ("`" if before.endswith("`") else ""))
            for t in reversed([t for t in ticks if t[1] <= s["start"] and t[0] >= prev_end and t[0] not in used]):
                if s["start"] - t[1] <= 14 and not FILE_CIT.search(t[2]) and not re.fullmatch(r":" + LINES_RE, t[2].strip()):
                    found = symbols_in(t[2])
                    if found: syms += found; used.add(t[0])
                break
        s["symbols"] = list(dict.fromkeys(syms)); s["negated"] = [x for x in dict.fromkeys(neg)]
    mentions = [{"start": t[0], "path": t[2].strip()} for t in ticks if re.fullmatch(PATH_RE, t[2].strip())]
    return spans, mentions


def line_refs(refs):
    out = []
    for part in refs.split(","):
        part = part.strip().replace("–", "-")
        a, _, b = part.partition("-")
        out.append((int(a), int(b) if b else int(a)))
    return out


# ------------------------------------------------------------------ verification
def enclosing_block(lines, sym, start, end):
    """line where `sym` is declared if the cited range [start,end] lies inside its { } block, else None"""
    last = sym.split(".")[-1]
    for i in range(min(start - 1, len(lines)) - 1, max(-1, start - 400), -1):
        if last in lines[i] and re.search(r"(function|class|interface|enum|=>|\)\s*\{|\w\s*\()", lines[i]):
            depth, seen = 0, False
            for k in range(i, min(len(lines), end + 400)):
                depth += lines[k].count("{") - lines[k].count("}")
                seen = seen or "{" in lines[k]
                if seen and depth <= 0: return i + 1 if k + 1 >= end else None
            return None
    return None


def check_citation(c, index, drift):
    path = c["file"]
    lines = index.lines(path)
    total = len(lines) - (1 if lines and lines[-1] == "" else 0)
    refs = line_refs(c["refs"])
    bad = [r for r in refs if r[0] < 1 or r[1] > total or r[0] > r[1]]
    if bad:
        return "FAIL_LINE", f"cited {c['refs']} but the file has {total} lines"
    text = "\n".join("\n".join(lines[a - 1:b]) for a, b in refs)
    ci = path.lower().endswith(".md")
    hay = text.lower() if ci else text
    neg = c.get("negated") or []
    syms = [x for x in c["symbols"] if x not in neg]
    def present_(sym, h):
        for s_ in (sym, sym.split(".")[-1]):
            if (s_.lower() if ci else s_) in h: return True
        return False
    wrongly = [x for x in neg if present_(x, hay)]
    if wrongly:
        return "FAIL_NEGATION", f"the audit says {', '.join(wrongly)} is absent/missing here, but it appears at the cited lines"
    if not syms:
        if neg: return "OK", "claimed-absent symbol(s) confirmed absent from the cited lines: " + ", ".join(neg)
        return "OK_LOCATION_ONLY", "no symbol quoted next to the citation; file and line range verified"
    def present(sym, h):
        for s in (sym, sym.split(".")[-1]):
            if (s.lower() if ci else s) in h: return True
        return False
    hit = [s for s in syms if present(s, hay)]
    miss = [s for s in syms if s not in hit]
    if not miss: return "OK", "all quoted symbols found at the cited lines: " + ", ".join(syms)
    # look around: drift or elsewhere
    near_text = "\n".join(lines[max(0, refs[0][0] - 1 - drift):min(total, refs[-1][1] + drift)])
    near = near_text.lower() if ci else near_text
    where = {}
    for s in miss:
        ln = [i + 1 for i, L in enumerate(lines) if present(s, L.lower() if ci else L)]
        if ln: where[s] = ln[:6]
    encl = {m: enclosing_block(lines, m, refs[0][0], refs[-1][1]) for m in miss}
    if all(encl.values()):
        return "WARN_ENCLOSING", "; ".join(f"cited lines are inside '{m}' (declared at line {ln}), not on a line that names it" for m, ln in encl.items())
    if hit and miss:
        return "WARN_PARTIAL", f"found: {', '.join(hit)}; NOT at the cited lines: {', '.join(miss)}" + (f" (elsewhere in file: {where})" if where else "")
    if all(present(s, near) for s in miss):
        return "WARN_DRIFT", f"symbol(s) {', '.join(miss)} are within {drift} lines of the cited range, not inside it (line numbers moved?) at {where}"
    return "FAIL_SYMBOL", f"quoted symbol(s) {', '.join(miss)} are not at the cited lines" + (f"; found elsewhere in the file at lines {where}" if where else "; not found anywhere in the file")


def verify_markdown(md_path, roots, index, drift):
    with open(md_path, encoding="utf-8") as f: text = f.read().split("\n")
    results, bases, head_text, in_fence = [], [], "", False
    for ln, line in enumerate(text, 1):
        if line.strip().startswith("```"): in_fence = not in_fence; continue
        if in_fence: continue
        if re.match(r"^#{1,6}\s", line):
            head_text = line
            nb = heading_bases(line, roots)
            bases = nb if nb else ([] if re.match(r"^#{1,3}\s", line) else bases)
        spans, mentions = parse_line(line)
        last_file = None                      # a bare ':N' may only inherit a file named on the SAME line
        events = sorted([dict(m, ev="mention") for m in mentions] + [dict(sp, ev="cit") for sp in spans], key=lambda e: e["start"])
        for c in events:
            hint = hints_from(head_text + " " + line)
            if c["ev"] == "mention":
                f_ = resolve(c["path"], bases, roots, index, hint)
                last_file = (c["path"], f_[0]) if len(f_) == 1 else last_file
                continue
            c = dict(c, line=ln, context=line.strip()[:160])
            if c["kind"] == "bare":
                if not last_file:
                    results.append(dict(c, status="WARN_NOFILE", path=None, file=None,
                                        detail="line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number")); continue
                c["path"] = last_file[0]; c["resolved"] = last_file[1]
            else:
                found = resolve(c["path"], bases, roots, index, hint)
                if not found:
                    results.append(dict(c, status="FAIL_FILE", detail=f"file '{c['path']}' not found under the verification roots (abbreviated names are not accepted)", file=None)); last_file = None; continue
                if len(found) > 1:
                    ok = [p for p in found if check_citation(dict(c, file=p), index, drift)[0] == "OK"]
                    if len(ok) == 1: found = ok
                    else:
                        results.append(dict(c, status="WARN_AMBIGUOUS", file=None,
                                            detail=f"{len(found)} files match '{c['path']}': " + "; ".join(rel(p, roots) for p in found[:4])))
                        last_file = (c["path"], found[0]); continue
                c["resolved"] = found[0]; last_file = (c["path"], found[0])
            c["file"] = c["resolved"]
            st, det = check_citation(c, index, drift)
            results.append(dict(c, status=st, detail=det))
    return results


def safe_rel(path, start):
    try: return os.path.relpath(path, start)
    except ValueError: return path          # different drive (Windows): show the absolute path


def rel(p, roots):
    for r in roots:
        if p and os.path.abspath(p).lower().startswith(r.lower()): return os.path.relpath(p, r)
    return p


def render(md_path, results, roots):
    order = ["FAIL_FILE", "FAIL_LINE", "FAIL_SYMBOL", "FAIL_NEGATION", "WARN_AMBIGUOUS", "WARN_NOFILE", "WARN_PARTIAL", "WARN_DRIFT", "WARN_ENCLOSING", "OK_LOCATION_ONLY", "OK"]
    cnt = collections.Counter(r["status"] for r in results)
    L = [f"# Claim verification - {os.path.basename(md_path)}", "",
         f"{len(results)} citations: " + ", ".join(f"{k} {cnt[k]}" for k in order if cnt[k]),
         "", "FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. "
         "OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.", "",
         "| Audit line | Citation | Status | Detail |", "|---|---|---|---|"]
    for r in sorted(results, key=lambda r: (order.index(r["status"]), r["line"])):
        if r["status"] in ("OK", "OK_LOCATION_ONLY") and len(results) > 60: continue
        cit = (r.get("path") or ":") + ":" + r["refs"]
        L.append(f"| {r['line']} | `{cit}` | {r['status']} | {r['detail'][:220].replace('|', '/')} |")
    if len(results) > 60: L += ["", f"(OK rows omitted from this table; full list in the JSON)"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ references
def workbook_ids():
    sys.path.insert(0, os.path.join(REPO, "testcases"))
    import workbook as W
    from openpyxl import load_workbook
    wb = load_workbook(W.XLSX, read_only=False)
    tcs, bugs = set(), set()
    for ws in W.module_sheets(wb):
        for r in range(2, ws.max_row + 1):
            t = W.getv(ws, r, "tc_id")
            if t: tcs.add(str(t))
            b = W.getv(ws, r, "bug_id")
            if b: bugs.update(re.findall(r"BUG-EP\d{3}-\d{2}", str(b)))
    return tcs, bugs


def verify_refs(md_path):
    with open(md_path, encoding="utf-8") as f: text = f.read()
    tcs, wb_bugs = workbook_ids()
    results = []
    res_dir = os.path.join(REPO, "schemathesis", "results")
    ep = re.search(r"EP-?(\d{3})", md_path.replace("\\", "/"))
    bug_defs = set()
    if ep:
        bp = os.path.join(REPO, "reports", f"EP-{ep.group(1)}", "bugs.md")
        if os.path.exists(bp):
            with open(bp, encoding="utf-8") as f: bug_defs = set(re.findall(r"(BUG-EP\d{3}-\d{2})", f.read()))
    for ln, line in enumerate(text.split("\n"), 1):
        for m in re.finditer(r"TC-\d{3}-\d{3}", line):
            results.append({"line": ln, "ref": m.group(0), "kind": "TC", "status": "OK" if m.group(0) in tcs else "FAIL_REF",
                            "detail": "exists in the workbook" if m.group(0) in tcs else "no such test case in the workbook"})
        for m in re.finditer(r"RUN-\d{8}-\d{6}-[A-Za-z0-9-]+|\d{4}-\d{2}-\d{2}_\d{4}_EP-\d{3}_\w+", line):
            ok = os.path.isdir(os.path.join(res_dir, m.group(0)))
            results.append({"line": ln, "ref": m.group(0), "kind": "RUN", "status": "OK" if ok else "FAIL_REF",
                            "detail": "run folder exists" if ok else "no such run folder under schemathesis/results"})
        for m in re.finditer(r"BUG-EP\d{3}-\d{2}", line):
            ok = m.group(0) in bug_defs or m.group(0) in wb_bugs
            results.append({"line": ln, "ref": m.group(0), "kind": "BUG", "status": "OK" if ok else "WARN_REF",
                            "detail": "defined in bugs.md / used in the workbook" if ok else "not defined in this endpoint's bugs.md nor referenced by a workbook case"})
    return results


# ------------------------------------------------------------------ tally
def evidence_for(run_dir):
    ev = os.path.join(run_dir, "evidence.json")
    role = None
    rj = os.path.join(run_dir, "run.json")
    if os.path.exists(rj):
        with open(rj, encoding="utf-8") as f: role = json.load(f).get("role")
    if os.path.exists(ev):
        with open(ev, encoding="utf-8") as f: return json.load(f)["interactions"], role
    nd = glob.glob(os.path.join(run_dir, "ndjson-*.ndjson"))
    if not nd: return [], role
    sys.path.insert(0, os.path.join(REPO, "schemathesis"))
    import evidence_export as X
    return X.normalize_ndjson(nd[0])[0], role or os.path.basename(run_dir).rsplit("_", 1)[-1].split("-")[-1]


def tally(ep, runs=None):
    ep = "EP-%03d" % int(re.sub(r"\D", "", ep))
    sys.path.insert(0, os.path.join(REPO, "testcases"))
    import workbook as W
    out = {"ep": ep, "workbook": {}, "runs": []}
    cs = W.list_cases(ep, full=True)
    out["workbook"] = {"cases": len(cs), "by_result": dict(collections.Counter(c["result"] for c in cs)),
                       "by_type": {t: dict(collections.Counter(c["result"] for c in cs if c["test_type"] == t)) for t in sorted({c["test_type"] for c in cs})},
                       "with_match_spec": sum(1 for c in cs if c.get("match"))}
    dirs = runs or sorted(d for d in glob.glob(os.path.join(REPO, "schemathesis", "results", "*")) if f"_{ep}_" in d or f"-{ep}-" in d)
    out["unreadable"] = []
    for d in dirs:
        try:
            inter, role = evidence_for(d)
        except (ValueError, OSError, KeyError) as e:       # a damaged/partial old run must not break the tally
            out["unreadable"].append({"run": os.path.basename(d), "why": f"{type(e).__name__}: {str(e)[:80]}"}); continue
        if not inter: continue
        fails = collections.Counter(); ids = collections.defaultdict(set)
        for it in inter:
            for ch in it["checks"]:
                if ch["status"] == "failure":
                    k = f"{ch.get('code') or ch['name']} ({ch['name']})"; fails[k] += 1; ids[k].add(it["id"])
        gets = collections.Counter(str((it.get("response") or {}).get("status")) for it in inter if it["method"] == "GET")
        out["runs"].append({"run": os.path.basename(d), "role": role, "requests": len(inter), "GET_status": dict(gets),
                            "failing_checks": {k: v for k, v in fails.items()}})
    return out


def print_tally(t, all_runs=False):
    w = t["workbook"]
    print(f"{t['ep']} workbook: {w['cases']} cases | " + " | ".join(f"{k} {v}" for k, v in sorted(w["by_result"].items())) + f" | {w['with_match_spec']} with a match spec")
    for tp, c in w["by_type"].items(): print(f"   {tp:16} " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    runs = t["runs"]
    if not all_runs:                                   # latest run per role (folders sort by time within each naming style)
        latest = {}
        for r in runs: latest[r["role"]] = r
        runs = list(latest.values())
        print(f"latest run per role ({len(t['runs'])} runs found; --all-runs lists them all):")
    else:
        print("all runs:")
    for r in runs:
        rl = r["GET_status"].get("429", 0)
        flag = f"   !! {rl} request(s) were rate-limited (HTTP 429): unreliable evidence" if rl else ""
        print(f"   {r['run']}  role={r['role']}  requests={r['requests']}  GET statuses={r['GET_status']}{flag}")
        for k, v in r["failing_checks"].items(): print(f"      {k}: {v} failing request(s)")
    for u in t.get("unreadable", []): print(f"   (skipped unreadable run {u['run']}: {u['why']})")
    per = collections.defaultdict(dict)
    for r in runs:
        for k, v in r["failing_checks"].items(): per[k.split(" ")[0]][r["role"]] = v
    if per: print("failing requests per role and code (from the runs above):")
    for code, roles in per.items(): print(f"   {code}: " + ", ".join(f"{role} {v}" for role, v in sorted(roles.items())))


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*"); ap.add_argument("--root", action="append"); ap.add_argument("--out")
    ap.add_argument("--strict", action="store_true"); ap.add_argument("--refs", action="store_true")
    ap.add_argument("--tally"); ap.add_argument("--all-runs", action="store_true"); ap.add_argument("--all-audits", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.tally:
        t = tally(a.tally)
        print(json.dumps(t, indent=1) if a.json else "", end="")
        if not a.json: print_tally(t, a.all_runs)
        return 0
    files = list(a.files)
    if a.all_audits: files += sorted(glob.glob(os.path.join(REPO, "audits", "EP-*.md")))
    if not files: ap.print_usage(); return 2
    roots, drift = load_roots(a.root)
    worst = 0
    if a.refs:
        for f in files:
            res = verify_refs(f); bad = [r for r in res if r["status"].startswith("FAIL")]; warn = [r for r in res if r["status"].startswith("WARN")]
            print(f"{f}: {len(res)} references, {len(bad)} FAIL, {len(warn)} WARN")
            for r in bad + warn: print(f"   line {r['line']}: {r['ref']} {r['status']} - {r['detail']}")
            worst = max(worst, 1 if bad or (a.strict and warn) else 0)
        return worst
    index = Index(roots)
    for f in files:
        res = verify_markdown(f, roots, index, drift)
        cnt = collections.Counter(r["status"] for r in res)
        fail = sum(v for k, v in cnt.items() if k.startswith("FAIL")); warn = sum(v for k, v in cnt.items() if k.startswith("WARN"))
        m = re.search(r"EP-\d{3}", os.path.basename(f))
        out_dir = a.out or (os.path.join(REPO, "reports", m.group(0)) if m else os.path.dirname(os.path.abspath(f)))
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, "claims_" + os.path.splitext(os.path.basename(f))[0])
        with open(base + ".md", "w", encoding="utf-8") as fh: fh.write(render(f, res, roots))
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump([{k: (rel(v, roots) if k in ("file", "resolved") else v) for k, v in r.items()} for r in res], fh, indent=1, ensure_ascii=False)
        print(f"{os.path.basename(f)}: {len(res)} citations | " + " ".join(f"{k}={v}" for k, v in sorted(cnt.items())) + f" -> {safe_rel(base + '.md', REPO)}")
        worst = max(worst, 1 if fail or (a.strict and warn) else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
