"""Redspur API test-case workbook helper (all workbook changes go through this script).

  python workbook.py init [--force]       build a NEW workbook from All_APIs.csv (refuses to overwrite)
  python workbook.py migrate              upgrade an existing workbook in place (backup first, idempotent)
  python workbook.py upsert design.json [--dry-run]
                                          DESIGN step: add cases / flow steps. Existing rows are never
                                          overwritten: only EMPTY cells are filled, results are untouched.
                                          --dry-run validates and reports without saving anything.
  python workbook.py apply-results v.json RESULT step: apply verdicts produced by evidence.py (results, run log,
                                          result history, new evidence-backed cases). The only way a result changes.
  python workbook.py correct fixes.json [--dry-run]
                                          CORRECT step: edit labels/wording/match of EXISTING cases (never results/ids),
                                          logged in Result History + reports/EP-NNN/results-history.md.
  python workbook.py conflict c.json      record requirement/spec/code conflicts; optionally BLOCK affected cases
  python workbook.py cases EP-038 [--full]  list an endpoint's cases as JSON
  python workbook.py roles EP-038         roles needed by the endpoint's Schemathesis-executable cases
  python workbook.py flows-sync           rebuild E2E Flows tab from testcases/flows/*.json

Rules: never deletes rows; never renumbers TC IDs; results change only via apply-results (with history);
E2E results stay NOT RUN unless a real E2E execution id is supplied. The workbook must be closed in Excel.
Set WORKBOOK_PATH / FLOWS_DIR / ALL_APIS_CSV to operate on other files (tests).
"""
import csv, json, os, re, shutil, sys, datetime as dt
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.datavalidation import DataValidation

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.environ.get("ALL_APIS_CSV") or os.path.join(HERE, "..", "All_APIs.csv")
XLSX = os.environ.get("WORKBOOK_PATH") or os.path.join(HERE, "Redspur_API_TestCases.xlsx")
FLOWS_DIR = os.environ.get("FLOWS_DIR") or os.path.join(HERE, "flows")
_DEFAULT_XLSX = not os.environ.get("WORKBOOK_PATH")
REPORTS_DIR = os.environ.get("REPORTS_DIR") or (os.path.join(HERE, "..", "reports") if _DEFAULT_XLSX
                                                else os.path.join(os.path.dirname(XLSX), "reports"))
MAXROW = 3000
S_RUNLOG, S_HISTORY, S_CONFLICTS, S_E2E = "Run Log", "Result History", "Conflicts", "E2E Flows"

# ---- column model (field -> header). Existing 20 columns keep their positions; new ones are appended. -----
CASE_COLS = [("Key", 3), ("TC ID", 14), ("Endpoint ID", 11), ("Method", 8), ("Path", 28), ("Test scenario", 38),
             ("Auth state (Guest / buyer / seller)", 12), ("Request headers", 28), ("Request params / body", 40),
             ("Expected status", 11), ("Expected response", 38), ("Actual status", 11), ("Actual response", 40),
             ("Source", 24), ("Automation", 13), ("Last Result", 11), ("Last Run", 11), ("Run Evidence", 34),
             ("Bug ID", 14), ("Notes", 34), ("Check Level", 15), ("Execution Method", 13),
             # --- internal columns (hidden; used by design/evidence matching, unhide in Excel if needed) ---
             ("Endpoint Title (sheet)", 34), ("Test Type", 15), ("Preconditions / Fixtures", 30), ("Steps / Request", 40),
             ("Ownership", 11), ("Test Data", 28), ("Response Assertions", 36), ("Business Outcome", 30),
             ("Expected Source", 16), ("Requirement Status", 13), ("Unchecked / Remaining", 34), ("Run ID", 24),
             ("Match Spec (JSON)", 40)]
CASE_F = ["key", "tc_id", "ep", "method", "path", "scenario", "role", "req_headers", "req_body", "expected_status",
          "expected", "actual_status", "actual_response", "source", "automation", "result", "run_date", "evidence",
          "bug_id", "notes", "check_level", "execution_method",
          "title", "test_type", "preconditions", "steps", "ownership", "test_data", "response_assertions",
          "business_outcome", "expected_source", "requirement_status", "unchecked", "run_id", "match"]
VISIBLE_N = 22          # Key (hidden) + the 21 requested columns; everything after is internal and hidden
FLOW_COLS = [("Key", 3), ("Flow ID", 10), ("Flow Name", 30), ("Step #", 7), ("Endpoint ID(s)", 22), ("Action / Request", 40),
             ("Role", 8), ("Test Data / Fixtures", 28), ("Expected Result", 38), ("Linked TC IDs", 22), ("Automation", 13),
             ("Last Result", 11), ("Last Run", 11), ("Run Evidence", 30), ("Bug ID", 14), ("Notes", 34)]
FLOW_F = ["key", "flow", "flow_name", "step", "endpoints", "action", "role", "data", "expected", "linked_tcs",
          "automation", "result", "run_date", "evidence", "bug_id", "notes"]
HEAD = dict(zip(CASE_F, [n for n, _ in CASE_COLS]))
FHEAD = dict(zip(FLOW_F, [n for n, _ in FLOW_COLS]))
RUNLOG_COLS = ["Run ID", "Endpoint ID", "Role", "Started", "Finished", "Environment Host", "Spec Version", "Spec SHA-256",
               "Fixtures SHA-256", "Fixture States", "Schemathesis", "Seed", "Run Status", "Auth", "Execution Errors",
               "Evidence Folder", "PASS", "FAIL", "BLOCKED", "NOT RUN (partial/none)", "Cases Evaluated"]
HIST_COLS = ["Timestamp", "Case / Flow Key", "TC ID", "Endpoint ID", "From", "To", "Kind", "Run ID", "Evidence", "Note"]
CONF_COLS = ["Conflict ID", "Endpoint ID", "Topic", "Requirement / Sheet says (source)", "OpenAPI spec says",
             "Code does (file:line)", "Affected TC IDs", "Status", "Decision / Resolution", "Raised", "Resolved"]
LISTS = {"test_type": "Schemathesis,Functional,Business Rule,Negative,Security/Auth,Schema/Contract,Audit-derived",
         "role": "anon,user,admin,other", "automation": "Schemathesis,Postman,Playwright,Manual",
         "result": "PASS,FAIL,BLOCKED,SKIPPED,NOT RUN",
         "check_level": "Status-only,Response-content,Business-rule,Contract,Security",
         "ownership": "owner,non-owner,n/a",
         "expected_source": "Requirement,OpenAPI spec,Backend code,Existing test,Documentation,QA suggestion,Product decision",
         "execution_method": "Schemathesis,Playwright,Postman,Manual,E2E",
         "requirement_status": "Confirmed,Assumed,Conflict,Unclear"}
RESULT_FAMILY = {"result", "run_date", "evidence", "actual_status", "actual_response", "run_id", "bug_id"}
STATIC = {"key", "tc_id", "ep", "method", "path", "title"}
FONT = "Arial"
NORM = Font(name=FONT, size=9)
GREY = Font(name=FONT, size=9, italic=True, color="808080")
HFILL = PatternFill("solid", fgColor="1F3864")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def ep_num(ep): return int(re.sub(r"\D", "", str(ep)))
def norm_ep(ep): return "EP-%03d" % ep_num(ep)
def sheet_name(module): return module.replace("/", "-")[:31]
def now(): return dt.datetime.now().isoformat(timespec="seconds")
def today(): return dt.date.today().isoformat()


def read_sheet():
    with open(CSV, encoding="utf-8-sig") as fh: rows = list(csv.DictReader(fh))
    mods = {}
    for r in rows: mods.setdefault(r["Module"], []).append(r)
    for m in mods: mods[m].sort(key=lambda r: ep_num(r["Endpoint ID"]))
    return rows, mods


# ------------------------------------------------------------------ generic sheet helpers
def hdr(ws): return {str(c.value): i + 1 for i, c in enumerate(ws[1]) if c.value}


def cc(ws, field, flow=False):
    """column index of a field, looked up by header name so column order never matters"""
    h = hdr(ws)
    name = (FHEAD if flow else HEAD)[field]
    if name not in h: raise SystemExit(f"sheet '{ws.title}' has no column '{name}' - run: python workbook.py migrate")
    return h[name]


def getv(ws, r, field, flow=False): return ws.cell(r, cc(ws, field, flow)).value
def setv(ws, r, field, val, flow=False): ws.cell(r, cc(ws, field, flow)).value = val


def row_dict(ws, r, flow=False):
    fields = FLOW_F if flow else CASE_F
    h = hdr(ws); head = FHEAD if flow else HEAD
    return {f: (ws.cell(r, h[head[f]]).value if head[f] in h else None) for f in fields}


def find_row(ws, key):
    kc = cc(ws, "key", flow=ws.title == S_E2E)
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, kc).value == key: return r
    return None


def style_row(ws, r, ncols, placeholder=False):
    for c in range(1, ncols + 1):
        cell = ws.cell(r, c); cell.font = GREY if placeholder else NORM; cell.border = BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def style_header(ws, cols, case=True):
    for i, (name, w) in enumerate(cols, 1):
        c = ws.cell(1, i, name); c.font = Font(name=FONT, size=9, bold=True, color="FFFFFF"); c.fill = HFILL
        c.alignment = Alignment(wrap_text=True, vertical="center"); c.border = BORDER
        ws.column_dimensions[L(i)].width = w
    ws.column_dimensions["A"].hidden = True
    if case:
        for i in range(VISIBLE_N + 1, len(cols) + 1): ws.column_dimensions[L(i)].hidden = True
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "E2" if case else "D2"
    ws.auto_filter.ref = f"A1:{L(len(cols))}{MAXROW}"


def add_validation(ws, fields, head, only=None):
    h = hdr(ws)
    for f, lst in LISTS.items():
        if f in fields and (only is None or f in only) and head[f] in h:
            col = L(h[head[f]])
            dv = DataValidation(type="list", formula1=f'"{lst}"', allow_blank=True)
            dv.add(f"{col}2:{col}{MAXROW}"); ws.add_data_validation(dv)


def add_result_colors(ws, head, field="result"):
    col = L(hdr(ws)[head[field]]); rng = f"{col}2:{col}{MAXROW}"
    for val, color in (("PASS", "C6EFCE"), ("FAIL", "FFC7CE"), ("BLOCKED", "FFEB9C"), ("NOT RUN", "EDEDED"), ("SKIPPED", "EDEDED")):
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{val}"'], fill=PatternFill("solid", bgColor=color)))


def put(ws, r, data, flow=False, only_empty=False, skip=()):
    """write fields; only_empty=True never overwrites a non-empty cell (human content wins).
    Returns the list of fields whose existing value differs from the supplied one (and was kept)."""
    fields = FLOW_F if flow else CASE_F
    kept = []
    for k, v in data.items():
        if k not in fields or k in skip or v is None: continue
        if k == "match" and not isinstance(v, str): v = json.dumps(v, ensure_ascii=False)
        cell = ws.cell(r, cc(ws, k, flow))
        if only_empty and cell.value not in (None, ""):
            if str(cell.value) != str(v): kept.append(k)
            continue
        cell.value = v
    return kept


def backup(tag="change"):
    if not os.path.exists(XLSX): return None
    d = os.path.join(os.path.dirname(XLSX), "backups"); os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, f"{os.path.splitext(os.path.basename(XLSX))[0]}_{dt.datetime.now():%Y%m%d-%H%M%S}_{tag}.xlsx")
    shutil.copyfile(XLSX, dst)
    old = sorted(f for f in os.listdir(d) if f.endswith(".xlsx"))
    for f in old[:-30]: os.remove(os.path.join(d, f))
    return dst


def save(wb):
    try:
        wb.save(XLSX)
    except PermissionError:
        raise SystemExit(f"PERMISSION DENIED saving {XLSX}: the workbook is open in Excel. Close it (File > Exit) and retry.")


def module_sheets(wb):
    return [ws for ws in wb.worksheets if ws.title not in ("README", "Summary", S_E2E, S_RUNLOG, S_HISTORY, S_CONFLICTS)]


def require_v2(wb):
    ws = module_sheets(wb)[0]
    if "Match Spec (JSON)" not in hdr(ws) or S_HISTORY not in wb.sheetnames:
        raise SystemExit("workbook is not on the v2 structure - run: python workbook.py migrate")


def ensure_aux_sheets(wb):
    for name, cols in ((S_RUNLOG, RUNLOG_COLS), (S_HISTORY, HIST_COLS), (S_CONFLICTS, CONF_COLS)):
        if name in wb.sheetnames: continue
        ws = wb.create_sheet(name)
        for i, h in enumerate(cols, 1):
            c = ws.cell(1, i, h); c.font = Font(name=FONT, size=9, bold=True, color="FFFFFF"); c.fill = HFILL
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.column_dimensions[L(i)].width = 30 if name != S_HISTORY or h in ("Note", "Evidence") else 18
        ws.freeze_panes = "A2"; ws.auto_filter.ref = f"A1:{L(len(cols))}{MAXROW}"


def history_md_path(ep): return os.path.join(REPORTS_DIR, norm_ep(ep), "results-history.md")


def history_md(ep, lines):
    """Previous results live ONLY here (reports/EP-NNN/results-history.md), never as workbook columns."""
    p = history_md_path(ep); os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f"# {norm_ep(ep)} - results history (previous results)\n\nAppend-only. The workbook shows only the latest result; "
                     "every change is recorded here.\n\n| When | TC | From | To | Kind | Run | Evidence / note |\n|---|---|---|---|---|---|---|\n")
    with open(p, "a", encoding="utf-8") as fh: fh.write("\n".join(lines) + "\n")


def _cell(x): return str(x if x is not None else "").replace("|", "/").replace("\n", " ")[:300]


def add_history(wb, key, tc, ep, frm, to, kind, run_id=None, evidence=None, note=None):
    ws = wb[S_HISTORY]
    ws.append([now(), key, tc, ep, frm, to, kind, run_id, evidence, note])
    for c in ws[ws.max_row]: c.font = NORM; c.alignment = Alignment(wrap_text=True, vertical="top")
    if ep and kind != "design" and re.match(r"EP-\d+$", str(ep)):
        history_md(ep, [f"| {now()} | {_cell(tc or key)} | {_cell(frm)} | {_cell(to)} | {_cell(kind)} | {_cell(run_id)} | "
                        f"{_cell(evidence)} {_cell(note)} |"])


# ------------------------------------------------------------------ build / migrate
README_V2 = [
    ("", False), ("WORKFLOW v2 (usage audit -> design cases -> run Schemathesis -> match evidence -> update)", True),
    ("Cases are DESIGNED before execution (result NOT RUN, or BLOCKED for a known prerequisite gap or an open requirement conflict). Results change ONLY through 'apply-results' from matched evidence.", False),
    ("PASS = matching scenario ran and EVERY expected assertion was checked and satisfied. FAIL = it ran and a checked expectation was violated. BLOCKED = a missing prerequisite prevented execution/verification. NOT RUN = scenario or required assertions not executed (partial coverage stays NOT RUN; see 'Unchecked / Remaining').", False),
    ("A schema/contract result applies only to Contract cases. An HTTP 200 never proves response content or business rules. E2E rows stay NOT RUN until a real E2E sequence is executed (never copied from endpoint results).", False),
    ("Run Log = one row per Schemathesis run (spec version/hash, fixtures, role, auth, errors). Result History = append-only log of every result change. Conflicts = requirement vs spec vs code disagreements (affected cases are BLOCKED until a decision).", False),
    ("Match Spec (JSON) = machine-checkable scenario definition used to match evidence; Execution Method = who executes the case. Cases without a Match Spec stay NOT RUN and are listed as needing another execution method.", False),
]


def build(force=False):
    if os.path.exists(XLSX) and not force:
        sys.exit(f"{XLSX} exists - refusing to overwrite (use --force; this DISCARDS all test cases).")
    rows, mods = read_sheet()
    wb = Workbook(); wb.remove(wb.active)
    rd = wb.create_sheet("README")
    base = [("Redspur API test-case workbook", True),
            ("Source of endpoints: All_APIs.csv. One tab per module; one row per test case; endpoints with no cases yet show a grey placeholder row.", False)]
    for i, (t, b) in enumerate(base + README_V2, 1):
        c = rd.cell(i, 1, t); c.font = Font(name=FONT, size=12 if i == 1 else 10, bold=b); c.alignment = Alignment(wrap_text=True, vertical="top")
    rd.column_dimensions["A"].width = 150
    sm = wb.create_sheet("Summary")
    for i, h in enumerate(["Module", "Endpoints", "Endpoints with cases", "Test cases", "PASS", "FAIL", "BLOCKED", "NOT RUN"], 1):
        c = sm.cell(1, i, h); c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF"); c.fill = HFILL
        sm.column_dimensions[L(i)].width = 26 if i == 1 else 18
    for n, (m, eps) in enumerate(mods.items(), 2):
        q = "'" + sheet_name(m) + "'"
        sm.cell(n, 1, m); sm.cell(n, 2, len(eps))
        sm.cell(n, 3, f'=B{n}-COUNTIF({q}!A:A,"*|placeholder")')
        sm.cell(n, 4, f'=COUNTIF({q}!B:B,"TC-*")')
        for col, val in ((5, "PASS"), (6, "FAIL"), (7, "BLOCKED"), (8, "NOT RUN")):
            sm.cell(n, col, f'=COUNTIFS({q}!B:B,"TC-*",{q}!P:P,"{val}")')
        for c in range(1, 9): sm.cell(n, c).font = Font(name=FONT, size=10, color="0000FF" if c == 2 else "000000")
    last = len(mods) + 1; t = last + 1
    sm.cell(t, 1, "TOTAL")
    for col in range(2, 9): sm.cell(t, col, f"=SUM({L(col)}2:{L(col)}{last})")
    for c in range(1, 9): sm.cell(t, c).font = Font(name=FONT, size=10, bold=True)
    sm.cell(t + 2, 1, "Endpoints (blue) = rows per module in All_APIs.csv when the workbook was created.").font = GREY
    for m, eps in mods.items():
        ws = wb.create_sheet(sheet_name(m)); style_header(ws, CASE_COLS)
        add_validation(ws, CASE_F, HEAD); add_result_colors(ws, HEAD)
        for i, r in enumerate(eps, 2):
            put(ws, i, {"key": f"{norm_ep(r['Endpoint ID'])}|placeholder", "ep": norm_ep(r["Endpoint ID"]), "method": r["Method"],
                        "path": r["Endpoint Path"], "title": r["Endpoint Title"], "scenario": "(no test cases yet)", "result": "NOT RUN"})
            style_row(ws, i, len(CASE_COLS), placeholder=True)
    fw = wb.create_sheet(S_E2E); style_header(fw, FLOW_COLS, case=False)
    add_validation(fw, FLOW_F, FHEAD); add_result_colors(fw, FHEAD)
    flows = {}
    for r in rows:
        for n in re.findall(r"Flow\s*(\d+)", r.get("Usage Note", "") or ""):
            flows.setdefault(int(n), []).append(norm_ep(r["Endpoint ID"]))
    for i, n in enumerate(sorted(flows), 2):
        put(fw, i, {"key": f"FLOW-{n:02d}|placeholder", "flow": f"FLOW-{n:02d}", "flow_name": f"Flow {n} (name TBD)",
                    "endpoints": ", ".join(sorted(set(flows[n]))), "action": "(no steps yet - endpoints above reference this flow in the sheet)",
                    "result": "NOT RUN"}, flow=True)
        style_row(fw, i, len(FLOW_COLS), placeholder=True)
    ensure_aux_sheets(wb)
    wb.calculation.fullCalcOnLoad = True
    save(wb)
    print(f"created {XLSX}: {len(mods)} module tabs, {len(rows)} endpoints, {len(flows)} flows")


LEGACY = {"Scenario": "scenario", "Role": "role", "Expected Result": "expected", "Actual Result": "_old_actual",
          "Previous Result": "_prev", "Previous Run ID": "_prev_run"}


def _legacy_field(name):
    if name in LEGACY: return LEGACY[name]
    for f, h in HEAD.items():
        if h == name: return f
    return None


def _auth_header(role):
    return {"anon": "(none - request sent without Authorization)", "user": "Authorization: Bearer <user token>",
            "admin": "Authorization: Bearer <admin token>", "other": "Authorization: Bearer <non-owner user token>"}.get(role or "")


def relayout(ws):
    """rewrite a module sheet into the current column layout; returns (rows_converted, history_lines_by_ep)"""
    old = hdr(ws); rows = []
    for r in range(2, ws.max_row + 1):
        d = {}
        for name, col in old.items():
            f = _legacy_field(name)
            if f: d[f] = ws.cell(r, col).value
        if any(v not in (None, "") for v in d.values()): rows.append(d)
    hist = {}
    for d in rows:
        if d.get("tc_id"):
            if d.get("_prev") or d.get("_old_actual"):
                hist.setdefault(d["ep"], []).append(
                    f"| migration {today()} | {d['tc_id']} | {_cell(d.get('_prev'))} | {_cell(d.get('result'))} | old columns | {_cell(d.get('_prev_run'))} | "
                    f"old 'Actual Result' text: {_cell(d.get('_old_actual'))} |")
            d["req_headers"] = d.get("req_headers") or _auth_header(d.get("role"))
            d["req_body"] = d.get("req_body") or d.get("steps")
    ws.delete_rows(1, ws.max_row)
    ws.data_validations.dataValidation = []
    ws.conditional_formatting = type(ws.conditional_formatting)()
    for cl in list(ws.column_dimensions): ws.column_dimensions[cl].hidden = False
    style_header(ws, CASE_COLS)
    for i, d in enumerate(rows, 2):
        for f, v in d.items():
            if f in CASE_F and v is not None: ws.cell(i, cc(ws, f)).value = v
        style_row(ws, i, len(CASE_COLS), placeholder=str(d.get("key", "")).endswith("|placeholder"))
    add_validation(ws, CASE_F, HEAD); add_result_colors(ws, HEAD)
    return len(rows), hist


def migrate():
    wb = load_workbook(XLSX)
    bk = backup("pre-migrate")
    reset_e2e = converted = 0; all_hist = {}
    ensure_aux_sheets(wb)
    for ws in module_sheets(wb):
        h = hdr(ws)
        if "Previous Result" in h or "Actual status" not in h:
            n, hist = relayout(ws); converted += n
            for ep, ls in hist.items(): all_hist.setdefault(ep, []).extend(ls)
    # E2E: results copied from endpoint cases are not E2E executions -> reset to NOT RUN, keep history
    fw = wb[S_E2E]
    for r in range(2, fw.max_row + 1):
        key = getv(fw, r, "key", True)
        if not key or str(key).endswith("|placeholder"): continue
        res = getv(fw, r, "result", True)
        if res not in (None, "", "NOT RUN") and "E2E-RUN" not in str(getv(fw, r, "evidence", True) or ""):
            add_history(wb, key, None, getv(fw, r, "endpoints", True), res, "NOT RUN", "migration-reset", None,
                        getv(fw, r, "evidence", True),
                        "Result had been derived from endpoint-case results; the E2E sequence itself was never executed.")
            setv(fw, r, "result", "NOT RUN", True)
            old = getv(fw, r, "notes", True) or ""
            setv(fw, r, "notes", (old + " | " if old else "") + f"Previous value '{res}' was derived from endpoint cases (not an E2E execution); reset {today()}.", True)
            setv(fw, r, "run_date", None, True); reset_e2e += 1
    # per-endpoint history md from the Result History tab + the removed Previous Result columns
    hs = wb[S_HISTORY]
    for i in range(2, hs.max_row + 1):
        ep = hs.cell(i, 4).value
        if ep and re.match(r"EP-\d+$", str(ep)) and hs.cell(i, 7).value != "design":
            all_hist.setdefault(ep, []).insert(0, "| " + " | ".join(_cell(hs.cell(i, c).value) for c in (1, 3, 5, 6, 7, 8)) +
                                              f" | {_cell(hs.cell(i, 9).value)} {_cell(hs.cell(i, 10).value)} |")
    for ep, ls in all_hist.items():
        if not os.path.exists(history_md_path(ep)): history_md(ep, ls)
    rd = wb["README"]
    if not any("WORKFLOW v2" in str(rd.cell(i, 1).value or "") for i in range(1, rd.max_row + 1)):
        for t, b in README_V2:
            rd.append([t]); c = rd.cell(rd.max_row, 1); c.font = Font(name=FONT, size=10, bold=b); c.alignment = Alignment(wrap_text=True, vertical="top")
    save(wb)
    if reset_e2e: _reset_flow_json()
    print(f"migrated {XLSX}: {converted} rows re-laid out, {reset_e2e} E2E results reset, history md for {len(all_hist)} endpoints, backup: {bk}")


def _reset_flow_json():
    if not os.path.isdir(FLOWS_DIR): return
    for fn in os.listdir(FLOWS_DIR):
        if not fn.endswith(".json"): continue
        p = os.path.join(FLOWS_DIR, fn); doc = json.load(open(p, encoding="utf-8")); ch = False
        for st in doc.get("steps", []):
            if st.get("result") not in (None, "", "NOT RUN") and not st.get("e2e_run_id"):
                st["previous_derived_result"] = st["result"]; st["result"] = "NOT RUN"; st.pop("run_date", None); ch = True
        if ch: json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


# ------------------------------------------------------------------ design upsert
REQ_NEW = ["key", "ep", "scenario", "test_type", "role", "check_level", "preconditions", "steps", "expected_source",
           "execution_method", "requirement_status"]


def validate_case(c):
    errs = [f"missing '{f}'" for f in REQ_NEW if c.get(f) in (None, "")]
    if not (c.get("expected") or c.get("expected_status") or c.get("response_assertions")):
        errs.append("needs expected / expected_status / response_assertions")
    for f in ("test_type", "role", "check_level", "ownership", "expected_source", "execution_method", "requirement_status"):
        if c.get(f) and f in LISTS and c[f] not in LISTS[f].split(","): errs.append(f"{f}='{c[f]}' not one of {LISTS[f]}")
    m = c.get("match")
    if isinstance(m, str):
        try: m = json.loads(m)
        except ValueError: errs.append("match is not valid JSON"); m = None
    if c.get("execution_method") == "Schemathesis":
        if not isinstance(m, dict) or not all(m.get(k) for k in ("method", "path", "role", "assertions")):
            errs.append("Schemathesis cases need match{method,path,role,assertions[]}")
        elif m["role"] not in ("any", c.get("role")) and c.get("role") != "other":     # 'other' = some non-owner, non-admin user
            errs.append("match.role must equal role (or be 'any' for spec/protocol cases)")
    if c.get("requirement_status") in ("Conflict", "Unclear") and not (c.get("unchecked") or c.get("blocked_reason")):
        errs.append("Conflict/Unclear cases need blocked_reason (what must be clarified)")
    if c.get("check_level") == "Status-only":
        # judged on what is actually asserted, not on words in a text column
        if isinstance(m, dict) and {a.get("type") for a in m.get("assertions", [])} & {"body_json", "header"}:
            errs.append("a Status-only case must not assert the body or headers - split it into a Response-content case")
        elif not isinstance(m, dict) and c.get("response_assertions"):
            errs.append("a Status-only case must not carry response assertions - split it into a Response-content case")
    return errs


def next_tc(ws, ep):
    n = 0; tc = cc(ws, "tc_id")
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, tc).value
        if v and str(v).startswith(f"TC-{ep_num(ep):03d}-"): n = max(n, int(str(v).rsplit("-", 1)[1]))
    return f"TC-{ep_num(ep):03d}-{n + 1:03d}"


def slot(ws, group_field, group_val, placeholder_key, flow=False):
    """row for a NEW record: reuse the group's placeholder, else insert after the group's last row"""
    r = find_row(ws, placeholder_key)
    if r: return r, True
    gc = cc(ws, group_field, flow); last = None
    for i in range(2, ws.max_row + 1):
        if ws.cell(i, gc).value == group_val: last = i
    r = (last + 1) if last else ws.max_row + 1
    if last: ws.insert_rows(r)
    return r, False


def apply_design(data, dry_run=False):
    """dry_run: validate and report exactly what WOULD happen; nothing is saved, backed up or written to flows/*.json"""
    wb = load_workbook(XLSX); require_v2(wb); bk = None if dry_run else backup("pre-design")
    rows, _ = read_sheet(); info = {norm_ep(r["Endpoint ID"]): r for r in rows}
    rep = {"added": [], "existing_kept": [], "rejected": [], "blocked_at_design": [], "flows_added": 0, "flows_updated": 0}
    for c in data.get("cases", []):
        c = dict(c); ep = norm_ep(c.get("ep", "0")); r0 = info.get(ep)
        if not r0: rep["rejected"].append({"key": c.get("key"), "errors": [f"unknown endpoint {c.get('ep')}"]}); continue
        ws = wb[sheet_name(r0["Module"])]; key = f"{ep}|{c.get('key')}"; r = find_row(ws, key)
        c.update(ep=ep, method=r0["Method"], path=r0["Endpoint Path"], title=r0["Endpoint Title"])
        c.pop("result", None)                       # results are never accepted from design input
        if r:                                       # exists: fill empty cells only, never touch results/history
            kept = put(ws, r, {k: v for k, v in c.items() if k not in STATIC}, only_empty=True, skip=RESULT_FAMILY)
            rep["existing_kept"].append({"tc_id": getv(ws, r, "tc_id"), "key": c.get("key"), "differs_from_input": kept})
            continue
        errs = validate_case(c)
        if errs: rep["rejected"].append({"key": c.get("key"), "errors": errs}); continue
        r, was_ph = slot(ws, "ep", ep, f"{ep}|placeholder")
        c["tc_id"] = c.get("tc_id") or next_tc(ws, ep)
        ws.cell(r, cc(ws, "key")).value = key
        if was_ph:
            for col in range(2, ws.max_column + 1): ws.cell(r, col).value = None
        style_row(ws, r, ws.max_column)
        blocked = c.get("requirement_status") in ("Conflict", "Unclear") or c.get("blocked_reason")
        c["result"] = "BLOCKED" if blocked else "NOT RUN"
        if blocked:
            c["unchecked"] = c.get("unchecked") or c.get("blocked_reason")
            rep["blocked_at_design"].append(c["tc_id"])
        c.setdefault("automation", c["execution_method"] if c["execution_method"] in LISTS["automation"].split(",") else "Manual")
        put(ws, r, {k: v for k, v in c.items() if k not in ("key", "blocked_reason")})
        add_history(wb, key, c["tc_id"], ep, None, c["result"], "design", None, None,
                    c.get("unchecked") or "case designed; not executed")
        rep["added"].append(c["tc_id"])
    fw = wb[S_E2E]
    for f in data.get("flows", []):
        fid = "FLOW-%02d" % ep_num(f["flow"]); key = f"{fid}|{f['key']}"; r = find_row(fw, key); f = dict(f, flow=fid)
        if not f.get("e2e_run_id"): f["result"] = "NOT RUN"; f.pop("run_date", None)
        if r: rep["flows_updated"] += 1
        else:
            r, _ = slot(fw, "flow", fid, "__none__", flow=True); rep["flows_added"] += 1
            fw.cell(r, cc(fw, "key", True)).value = key
            setv(fw, r, "flow_name", next((getv(fw, i, "flow_name", True) for i in range(2, fw.max_row + 1)
                                           if getv(fw, i, "flow", True) == fid), None), True)
            style_row(fw, r, fw.max_column)
        setv(fw, r, "flow", fid, True)
        cur = getv(fw, r, "result", True)
        put(fw, r, {k: v for k, v in f.items() if k != "key" and not (k in ("result", "run_date") and cur not in (None, "", "NOT RUN"))}, flow=True)
        if not dry_run: persist_flow_step(fid, f)
    if not dry_run: save(wb)
    rep["backup"] = bk; rep["dry_run"] = dry_run
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if rep["rejected"]: sys.exit(2)


def persist_flow_step(fid, f):
    """Every flow step is also kept in testcases/flows/FLOW-NN.json (long-term reference for future automation)."""
    os.makedirs(FLOWS_DIR, exist_ok=True)
    path = os.path.join(FLOWS_DIR, f"{fid}.json")
    doc = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"flow_id": fid, "name": "", "steps": []}
    step = {k: v for k, v in f.items() if k != "flow" and v not in (None, "")}
    if f.get("flow_name"): doc["name"] = f["flow_name"]
    for i, old in enumerate(doc["steps"]):
        if old.get("key") == f["key"]:
            merged = {**old, **step}
            if old.get("result") not in (None, "", "NOT RUN") and not f.get("e2e_run_id"): merged["result"] = old["result"]
            doc["steps"][i] = merged; break
    else:
        doc["steps"].append(step)
    doc["updated"] = today()
    json.dump(doc, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def flows_sync():
    flows = []
    for fn in sorted(os.listdir(FLOWS_DIR)) if os.path.isdir(FLOWS_DIR) else []:
        if not fn.endswith(".json"): continue
        doc = json.load(open(os.path.join(FLOWS_DIR, fn), encoding="utf-8"))
        for st in doc.get("steps", []): flows.append(dict(st, flow=doc["flow_id"], flow_name=doc.get("name") or None))
    apply_design({"flows": flows})


# ------------------------------------------------------------------ results
def set_actual(ws, r, v):
    """Actual status / Actual response = what the API really returned (from the evidence), not assertion text"""
    setv(ws, r, "actual_status", v.get("actual_status")); setv(ws, r, "actual_response", v.get("actual_response"))


def apply_results(data):
    wb = load_workbook(XLSX); require_v2(wb); bk = backup("pre-results")
    rows, _ = read_sheet(); info = {norm_ep(r["Endpoint ID"]): r for r in rows}
    log = wb[S_RUNLOG]; per_run = {}
    summary = {"changed": [], "reconfirmed": [], "blocked": [], "partial": [], "unchanged_not_retested": 0, "new_cases": [],
               "skipped": [], "backup": bk}

    def bump(run_id, res):
        per_run.setdefault(run_id, {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT RUN": 0, "n": 0})
        per_run[run_id][res] += 1; per_run[run_id]["n"] += 1

    for v in data.get("verdicts", []):
        ep = norm_ep(v["ep"]); r0 = info.get(ep)
        if not r0: summary["skipped"].append({"tc_id": v.get("tc_id"), "why": "unknown endpoint"}); continue
        ws = wb[sheet_name(r0["Module"])]
        r = next((i for i in range(2, ws.max_row + 1) if getv(ws, i, "tc_id") == v["tc_id"]), None)
        if r is None: summary["skipped"].append({"tc_id": v["tc_id"], "why": "case row not found"}); continue
        if (getv(ws, r, "execution_method") or "") != "Schemathesis":
            summary["skipped"].append({"tc_id": v["tc_id"], "why": "execution method is not Schemathesis"}); continue
        key = getv(ws, r, "key"); cur = getv(ws, r, "result") or "NOT RUN"; kind = v["kind"]; run = v["run_id"]
        note = json.dumps(v.get("assertions") or [], ensure_ascii=False)[:900]
        reqs = getv(ws, r, "requirement_status")
        if kind == "executed" and reqs in ("Conflict", "Unclear"):
            # the evidence is real, but the expected behaviour is unresolved: record what was observed, keep the case BLOCKED
            observed = v["result"]; bump(run, "BLOCKED")
            setv(ws, r, "result", "BLOCKED"); setv(ws, r, "run_date", today()); setv(ws, r, "run_id", run)
            setv(ws, r, "evidence", v.get("evidence")); set_actual(ws, r, v)
            setv(ws, r, "unchecked", f"Observed {observed} in {run}; expected behaviour unresolved ({reqs}) - clarify before this can PASS or FAIL")
            add_history(wb, key, v["tc_id"], ep, cur, "BLOCKED", "executed-unresolved", run, v.get("evidence"), f"observed {observed}; requirement {reqs} | " + note)
            summary["blocked"].append({"tc_id": v["tc_id"], "reason": f"observed {observed}; requirement {reqs}", "kept": None, "observed": observed})
        elif kind == "executed":
            new = v["result"]; bump(run, new)
            if new != cur:
                summary["changed"].append({"tc_id": v["tc_id"], "from": cur, "to": new, "run_id": run})
            else:
                summary["reconfirmed"].append({"tc_id": v["tc_id"], "result": new, "run_id": run})
            setv(ws, r, "result", new); setv(ws, r, "run_date", today()); setv(ws, r, "run_id", run)
            setv(ws, r, "evidence", v.get("evidence")); set_actual(ws, r, v)
            setv(ws, r, "unchecked", v.get("unchecked") or None)
            add_history(wb, key, v["tc_id"], ep, cur, new, "execution" if new != cur else "re-executed", run, v.get("evidence"), note)
        elif kind == "blocked":
            bump(run, "BLOCKED")
            if cur in ("NOT RUN", "BLOCKED", "", None):
                setv(ws, r, "result", "BLOCKED")
            setv(ws, r, "unchecked", v.get("reason") or v.get("unchecked"))
            add_history(wb, key, v["tc_id"], ep, cur, getv(ws, r, "result"), "blocked-attempt", run, v.get("evidence"),
                        (v.get("reason") or "") + (" | prior result kept" if cur in ("PASS", "FAIL") else ""))
            summary["blocked"].append({"tc_id": v["tc_id"], "reason": v.get("reason"), "kept": cur if cur in ("PASS", "FAIL") else None})
        elif kind == "partial":
            bump(run, "NOT RUN")
            setv(ws, r, "unchecked", v.get("unchecked")); setv(ws, r, "evidence", v.get("evidence") or getv(ws, r, "evidence"))
            add_history(wb, key, v["tc_id"], ep, cur, cur, "partial", run, v.get("evidence"), (v.get("unchecked") or "") + " | " + note)
            summary["partial"].append({"tc_id": v["tc_id"], "kept": cur, "unchecked": v.get("unchecked")})
        else:
            bump(run, "NOT RUN"); summary["unchanged_not_retested"] += 1
    # new evidence-backed cases for findings no existing case covers (deduplicated by key)
    for c in data.get("new_cases", []):
        c = dict(c); ep = norm_ep(c["ep"]); r0 = info.get(ep)
        if not r0: continue
        ws = wb[sheet_name(r0["Module"])]; key = f"{ep}|{c['key']}"
        if find_row(ws, key): summary["skipped"].append({"key": c["key"], "why": "finding already has a case"}); continue
        res, run = c.pop("result", "FAIL"), c.get("run_id")
        errs = validate_case(dict(c, requirement_status=c.get("requirement_status", "Confirmed")))
        if errs: summary["skipped"].append({"key": c["key"], "why": errs}); continue
        r, was_ph = slot(ws, "ep", ep, f"{ep}|placeholder")
        c.update(ep=ep, method=r0["Method"], path=r0["Endpoint Path"], title=r0["Endpoint Title"], tc_id=next_tc(ws, ep))
        ws.cell(r, cc(ws, "key")).value = key
        if was_ph:
            for col in range(2, ws.max_column + 1): ws.cell(r, col).value = None
        style_row(ws, r, ws.max_column)
        c.update(result=res, run_date=today())
        put(ws, r, {k: v for k, v in c.items() if k != "key"})
        add_history(wb, key, c["tc_id"], ep, None, res, "execution-new-finding", run, c.get("evidence"), "case created from an unmatched failing check")
        bump(run, res); summary["new_cases"].append({"tc_id": c["tc_id"], "key": c["key"], "result": res})
    for m in data.get("runs", []):
        rid = m["run_id"]; row = next((i for i in range(2, log.max_row + 1) if log.cell(i, 1).value == rid), None)
        cnt = per_run.get(rid, {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT RUN": 0, "n": 0})
        vals = [rid, m.get("ep"), m.get("role"), m.get("started"), m.get("finished"), m.get("environment_host"),
                (m.get("spec") or {}).get("info_version") or (m.get("spec") or {}).get("openapi_version"),
                (m.get("spec") or {}).get("sha256"), (m.get("fixtures") or {}).get("sha256"),
                ", ".join((m.get("fixtures") or {}).get("states") or []), m.get("schemathesis_version"), str(m.get("seed"))[:20],
                m.get("status"), (m.get("auth") or {}).get("status"), len(m.get("execution_errors") or []),
                m.get("evidence_dir"), cnt["PASS"], cnt["FAIL"], cnt["BLOCKED"], cnt["NOT RUN"], cnt["n"]]
        if row is None: log.append(vals); row = log.max_row
        else:
            for i, val in enumerate(vals, 1): log.cell(row, i).value = val
        for c in log[row]: c.font = NORM; c.alignment = Alignment(wrap_text=True, vertical="top")
    save(wb)
    print(json.dumps(summary, indent=1, ensure_ascii=False))


def apply_corrections(data, dry_run=False):
    """CORRECT step: human-approved edits to EXISTING case rows (labels, wording, match spec, preconditions...).
    Never touches results / run data / ids; every change is logged (Result History tab + reports/EP-NNN/results-history.md)."""
    wb = load_workbook(XLSX); require_v2(wb); bk = None if dry_run else backup("pre-correct")
    rows, _ = read_sheet(); info = {norm_ep(r["Endpoint ID"]): r for r in rows}
    rep = {"changed": [], "unchanged": [], "rejected": [], "dry_run": dry_run, "backup": bk}
    for c in data.get("corrections", []):
        tc = c.get("tc_id"); ep = norm_ep(c.get("ep", "0")); r0 = info.get(ep)
        if not r0: rep["rejected"].append({"tc_id": tc, "why": f"unknown endpoint {c.get('ep')}"}); continue
        ws = wb[sheet_name(r0["Module"])]
        r = next((i for i in range(2, ws.max_row + 1) if getv(ws, i, "tc_id") == tc), None)
        if r is None: rep["rejected"].append({"tc_id": tc, "why": "case row not found"}); continue
        sets = c.get("set") or {}; bad = [f for f in sets if f not in CASE_F or f in RESULT_FAMILY or f in STATIC]
        if bad: rep["rejected"].append({"tc_id": tc, "why": f"fields not correctable: {bad} (results change only via evidence apply)"}); continue
        errs = []
        for f, v in sets.items():
            if f in LISTS and v not in (None, "") and v not in LISTS[f].split(","): errs.append(f"{f}='{v}' not one of {LISTS[f]}")
            if f == "match" and v not in (None, ""):
                try: json.loads(v) if isinstance(v, str) else json.dumps(v)
                except ValueError: errs.append("match is not valid JSON")
        if errs: rep["rejected"].append({"tc_id": tc, "why": errs}); continue
        diffs = []
        for f, v in sets.items():
            old = getv(ws, r, f); new = json.dumps(v, ensure_ascii=False) if f == "match" and not isinstance(v, str) else v
            if str(old if old is not None else "") == str(new if new is not None else ""): continue
            diffs.append(f"{f}: {_cell(old)[:80]} -> {_cell(new)[:80]}")
            if not dry_run: setv(ws, r, f, new)
        if not diffs: rep["unchanged"].append(tc); continue
        if not dry_run:
            add_history(wb, getv(ws, r, "key"), tc, ep, getv(ws, r, "result"), getv(ws, r, "result"), "correction", None, None,
                        "; ".join(diffs) + (f" | reason: {c['reason']}" if c.get("reason") else ""))
        rep["changed"].append({"tc_id": tc, "changes": diffs})
    if not dry_run: save(wb)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if rep["rejected"]: sys.exit(2)


# ------------------------------------------------------------------ conflicts / listings
def apply_conflicts(data):
    wb = load_workbook(XLSX); require_v2(wb); backup("pre-conflict")
    ws = wb[S_CONFLICTS]; rows, _ = read_sheet(); info = {norm_ep(r["Endpoint ID"]): r for r in rows}; out = []
    for c in data.get("conflicts", []):
        ep = norm_ep(c["ep"]); cid = c.get("id")
        if not cid:
            n = sum(1 for i in range(2, ws.max_row + 1) if str(ws.cell(i, 1).value or "").startswith(f"CF-{ep_num(ep):03d}-")) + 1
            cid = f"CF-{ep_num(ep):03d}-{n:02d}"
        row = next((i for i in range(2, ws.max_row + 1) if ws.cell(i, 1).value == cid), None)
        vals = [cid, ep, c.get("topic"), c.get("requirement"), c.get("spec"), c.get("code"), ", ".join(c.get("affected_tcs") or []),
                c.get("status", "Open"), c.get("decision"), today(), today() if c.get("status") == "Resolved" else None]
        if row is None: ws.append(vals); row = ws.max_row
        else:
            for i, v in enumerate(vals, 1):
                if v is not None and not (i == 10 and ws.cell(row, 10).value): ws.cell(row, i).value = v
        for cell in ws[row]: cell.font = NORM; cell.alignment = Alignment(wrap_text=True, vertical="top")
        res = {"conflict": cid, "blocked": [], "left_unchanged": []}
        if c.get("block") and c.get("status", "Open") == "Open":
            wsm = wb[sheet_name(info[ep]["Module"])]
            for tc in c.get("affected_tcs") or []:
                r = next((i for i in range(2, wsm.max_row + 1) if getv(wsm, i, "tc_id") == tc), None)
                if r is None: continue
                cur = getv(wsm, r, "result") or "NOT RUN"
                if cur in ("NOT RUN", "BLOCKED") or c.get("force_block"):
                    setv(wsm, r, "result", "BLOCKED"); setv(wsm, r, "requirement_status", "Conflict")
                    setv(wsm, r, "unchecked", f"{cid}: expected behaviour not clarified - {c.get('topic')}")
                    add_history(wb, getv(wsm, r, "key"), tc, ep, cur, "BLOCKED", "conflict", None, None, f"{cid} {c.get('topic')}")
                    res["blocked"].append(tc)
                else:
                    res["left_unchanged"].append({"tc_id": tc, "result": cur, "why": "already executed; use force_block to override"})
        out.append(res)
    save(wb); print(json.dumps(out, indent=1, ensure_ascii=False))


def list_cases(ep, full=False):
    rows, _ = read_sheet(); info = {norm_ep(r["Endpoint ID"]): r for r in rows}; ep = norm_ep(ep)
    ws = load_workbook(XLSX)[sheet_name(info[ep]["Module"])]; out = []
    for r in range(2, ws.max_row + 1):
        d = row_dict(ws, r)
        if d["ep"] == ep and d["tc_id"]:
            d["key"] = str(d["key"]).split("|", 1)[1]
            out.append(d if full else {k: d.get(k) for k in ("tc_id", "key", "test_type", "scenario", "role", "source", "result", "bug_id", "execution_method")})
    return out


def roles_needed(ep):
    roles = []
    for c in list_cases(ep, full=True):
        if c.get("execution_method") == "Schemathesis" and c.get("match"):
            try: role = json.loads(c["match"]).get("role")
            except ValueError: continue
            if role and role not in roles: roles.append(role)
    return roles


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "init": build("--force" in a)
    elif cmd == "migrate": migrate()
    elif cmd == "upsert":
        with open(a[1], encoding="utf-8") as fh: apply_design(json.load(fh), dry_run="--dry-run" in a)
    elif cmd == "apply-results": apply_results(json.load(open(a[1], encoding="utf-8")))
    elif cmd == "correct":
        with open(a[1], encoding="utf-8") as fh: apply_corrections(json.load(fh), dry_run="--dry-run" in a)
    elif cmd == "conflict": apply_conflicts(json.load(open(a[1], encoding="utf-8")))
    elif cmd == "cases": print(json.dumps(list_cases(a[1], "--full" in a), indent=1, ensure_ascii=False))
    elif cmd == "roles": print(json.dumps(roles_needed(a[1])))
    elif cmd == "flows-sync": flows_sync()
    else: print(__doc__)
