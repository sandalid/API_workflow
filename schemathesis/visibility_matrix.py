"""Build a listing-state x role visibility matrix from run folders.
Usage: python visibility_matrix.py <run_dir_user> <run_dir_admin> <run_dir_anon> -> prints + writes visibility_matrix.csv in the first dir's parent"""
import csv, json, os, sys
states = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures.json"), encoding="utf-8-sig"))["_states"]
roles = ["owner(user)", "admin", "anon"]
res = {}
for role, d in zip(roles, sys.argv[1:4]):
    for r in csv.DictReader(open(os.path.join(d, "results_detail.csv"), encoding="utf-8-sig")):
        if r["method"] == "GET" and r["check"] == "not_a_server_error":
            lid = r["url"].rsplit("/", 1)[-1]
            if lid in states: res[(states[lid], role)] = r["http_status"]
out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "visibility_matrix_EP-038.csv")
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["listing_state"] + roles)
    for s in dict.fromkeys(states.values()): w.writerow([s] + [res.get((s, r), "") for r in roles])
print(open(out, encoding="utf-8-sig").read()); print(out)
