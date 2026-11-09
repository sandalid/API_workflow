"""Export a Schemathesis run (ndjson) to CSV.  Usage: python export_csv.py <run_dir>
Writes results_detail.csv (one row per test case x check) and results_summary.csv (per phase/check)."""
import csv, glob, json, os, sys
from collections import Counter

run = sys.argv[1]
src = glob.glob(os.path.join(run, "ndjson-*.ndjson"))[0]
rows = []
for line in open(src, encoding="utf-8"):
    e = json.loads(line)
    sf = e.get("ScenarioFinished")
    if not sf:
        continue
    rec = sf.get("recorder") or {}
    if sf["status"] == "skip" or not rec.get("cases"):
        rows.append(dict(phase=sf["phase"], operation=rec.get("label", ""), result="SKIP",
                         message=sf.get("skip_reason", "")))
        continue
    for cid, case in rec["cases"].items():
        v = case["value"]
        meta = v.get("meta", {}).get("phase", {}).get("data", {})
        inter = (rec.get("interactions") or {}).get(cid) or {}
        req, resp = inter.get("request", {}), inter.get("response", {})
        for chk in (rec.get("checks") or {}).get(cid, []):
            fail = (chk.get("failure_info") or {}).get("failure", {})
            rows.append(dict(
                phase=sf["phase"], operation=rec["label"], case_id=cid, method=v["method"],
                url=req.get("uri", ""), path_params=json.dumps(v.get("path_parameters", {})),
                test_description=meta.get("description", ""),
                http_status=resp.get("status_code", ""),
                response_time_s=round(resp.get("elapsed", 0), 3) if resp else "",
                check=chk["name"], result="PASS" if chk["status"] == "success" else chk["status"].upper(),
                failure_code=fail.get("code", ""), severity=fail.get("severity", ""),
                message=" ".join(fail.get("message", "").split())))

cols = ["phase","operation","case_id","method","url","path_params","test_description",
        "http_status","response_time_s","check","result","failure_code","severity","message"]
with open(os.path.join(run, "results_detail.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)

c = Counter((r["phase"], r.get("check", ""), r["result"]) for r in rows)
with open(os.path.join(run, "results_summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["phase","check","result","count"])
    for (p, ch, res), n in sorted(c.items()): w.writerow([p, ch, res, n])
print(len(rows), "rows ->", run)
