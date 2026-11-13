import json
EP="EP-032"
def c(key,scn,tt,role,lvl,pre,td,steps,st,ra,bo,exp,es,rs,em,src,match=None,br=None):
    d=dict(ep=EP,key=key,scenario=scn,test_type=tt,role=role,ownership="n/a",check_level=lvl,preconditions=pre,test_data=td,steps=steps,expected_status=st,response_assertions=ra,business_outcome=bo,expected=exp,expected_source=es,requirement_status=rs,execution_method=em,source=src)
    if match: d["match"]=match
    if br: d["blocked_reason"]=br
    return d
BC="Backend code brands.controller.ts:11"
def m(role,asserts,gen=None,method="GET",path="/brands"):
    x={"method":method,"path":path,"role":role,"inputs":{},"assertions":asserts}
    if gen:x["generation"]=gen
    return x
S=lambda *v:{"type":"status","in":list(v)}
cases=[
c("ST:anon-200","Anonymous lists brands","Schemathesis","anon","Status-only","No auth","none","GET /brands without Authorization","200","","Public list reachable","anon GET /brands -> 200",BC,"Assumed","Schemathesis","Audit scenario 1",m("anon",[S(200)])),
c("ST:user-200","Buyer/seller token lists brands","Schemathesis","user","Status-only","Valid user token","none","GET /brands with user Bearer","200","","No auth required, token harmless","user GET /brands -> 200","QA suggestion","Assumed","Schemathesis","Audit scenario 2",m("user",[S(200)])),
c("ST:admin-200","Admin token lists brands","Schemathesis","admin","Status-only","Valid admin token","none","GET /brands with admin Bearer","200","","Public for all roles","admin GET /brands -> 200","QA suggestion","Assumed","Schemathesis","Audit scenario 2",m("admin",[S(200)]),br="No admin account configured for the runner (verify with roles)"),
c("RC:array-body","Response is a JSON array","Functional","anon","Response-content","No auth","none","GET /brands","200","body is JSON array; header content-type contains application/json","List returned as array","200 with JSON array",BC,"Assumed","Schemathesis","Audit scenario 3",m("anon",[S(200),{"type":"body_json","path":"$","op":"type","value":"array"}])),
c("RC:item-shape","Each item has id,name,slug,itemCount,logo","Functional","anon","Response-content","At least one brand","none","GET /brands, inspect first item","200","item.id string; item.name string; item.slug string; item.itemCount integer >= 0; item.logo string or null","Shape as mapped by repository","Item shape correct","Backend code brands.repository.ts:22","Assumed","Manual","Audit scenario 3 (spec has no schema; body checks need element access)"),
c("BR:order-name-asc","Brands ordered by name ascending","Business Rule","anon","Business-rule","2+ brands exist","none","GET /brands; compare names order","200","names sorted ascending","Alphabetical listing","Names ascending","Documentation (qa-knowledge) BR-BRANDS-001 + brands.repository.ts:14","Assumed","Manual","KB:BR-BRANDS-001"),
c("BR:itemcount-live-only","itemCount counts only live listings","Business Rule","anon","Business-rule","Brand with approved/active, sold, rejected, soft-deleted listings","Brand with mixed-state listings","GET /brands; find brand","200","brand.itemCount == number of approved/active non-deleted listings of non-leaving sellers","Only live listings counted","itemCount excludes non-live","Documentation (qa-knowledge) BR-BRANDS-002 + brands.repository.ts:17","Assumed","Manual","KB:BR-BRANDS-002",br="No brand fixture with mixed-state listings in fixtures.json (only listing ids by state exist)"),
c("BR:zero-count-listed","Brand with zero live listings still listed","Business Rule","anon","Business-rule","Brand with no live listings","Empty brand","GET /brands; find empty brand","200","brand present; itemCount == 0","Empty brands not hidden","Present with itemCount 0","Backend code brands.repository.ts:12-22","Assumed","Manual","Audit scenario 6",br="No empty-brand fixture in fixtures.json"),
c("BR:freshness","itemCount updates immediately after status change","Business Rule","anon","Business-rule","Listing of known brand","Listing status change then refetch","1 GET /brands; 2 change listing status; 3 GET /brands","200","itemCount differs by the status change","No caching","Count recomputed per call","Documentation (qa-knowledge) gap 40","Assumed","E2E","KB gap 40 / audit scenario 11",br="Multi-step; needs mutating fixture"),
c("NEG:extra-params","Unexpected query params ignored, no 5xx","Negative","anon","Security","none","?limit=1, ?name=x, injection strings","GET /brands?limit=1","200","Same full list; never 5xx","Unknown params ignored","200, no 5xx","QA suggestion","Assumed","Schemathesis","Audit scenario 7",m("anon",[S(200,400,404)],gen="negative")),
c("NEG:post-method","POST /brands not allowed","Negative","anon","Status-only","none","none","POST /brands","404","not 5xx","Wrong method rejected","POST -> 404/405, not 5xx","QA suggestion","Assumed","Schemathesis","Audit scenario 8",m("anon",[S(404,405)],method="POST")),
c("NEG:delete-method","DELETE /brands not allowed","Negative","anon","Status-only","none","none","DELETE /brands","404","not 5xx","Wrong method rejected","DELETE -> 404/405, not 5xx","QA suggestion","Assumed","Schemathesis","Audit scenario 8",m("anon",[S(404,405)],method="DELETE")),
c("NEG:get-by-id","GET /brands/{id} has no route","Negative","anon","Status-only","none","id=abc123","GET /brands/abc123","404","not 200","No by-id route","404","Backend code (mobile comment services/brandsApi.ts:19)","Assumed","Schemathesis","Audit scenario 9",m("anon",[S(404)],path="/brands/abc123")),
c("CT:schema-200","200 conforms to spec schema","Schema/Contract","anon","Contract","none","none","GET /brands","200","","Contract","Schema conformance","Spec","Assumed","Schemathesis","Audit: spec has no response schema",m("anon",[S(200),{"type":"check","name":"response_schema_conformance"}]),br="spec has no response schema for 200"),
c("SEC:rate-limit","429 after burst","Security/Auth","anon","Security","Throttler configured","Burst of requests","Repeat GET /brands rapidly","429","","Throttling applies","429 after limit","QA suggestion (app.module.ts:104)","Assumed","Manual","Audit scenario 10",br="Throttle limit not known; needs load script"),
c("SEC:invalid-token","Invalid bearer token on public route","Security/Auth","anon","Security","none","Authorization: Bearer invalid","GET /brands with bad token","200","","Public route ignores token (no guard)","200 (no guard)","Backend code (no guards)","Assumed","Manual","QA suggestion"),
]
for x in cases:
    if x["execution_method"]=="Schemathesis" and "match" not in x: raise SystemExit(x["key"])
json.dump({"cases":cases},open("golden/_runs/20261112-210108/EP-032/design.json","w"),indent=1)
