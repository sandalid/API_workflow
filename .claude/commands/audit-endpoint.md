---
description: Audit one endpoint from the Redspur API sheet by its Endpoint ID (usage audit + test-design inputs)
argument-hint: <endpoint-id, e.g. 38 or EP-038>
---

Audit endpoint "$ARGUMENTS". READ-ONLY: never create, edit or delete anything in
D:\Redspur_Backend\redspur-droplight.

1. Normalise the input to EP-NNN (zero-padded to 3 digits): "38", "038", "ep38",
   "EP-038" all mean EP-038.
2. Open All_APIs.csv in the current directory and find that Endpoint ID.
   IDs have gaps. If it is not there, stop and tell me. Never pick a nearby ID.
3. From the row take: Module, Method, Endpoint Path, Endpoint Title, Used in App?, Usage Note.
4. Hand the row to the endpoint-usage-auditor subagent.
   Backend repo: D:\Redspur_Backend\redspur-droplight
   Backend API:  D:\Redspur_Backend\redspur-droplight\apps\api
   Mobile app:   D:\Redspur_Backend\redspur-droplight\apps\mobile  (buyer, seller, guest)
   Admin/seller web: D:\Redspur_Backend\redspur-droplight\apps\web (admin + seller back-office)
   OpenAPI spec snapshot: schemathesis\spec\openapi.json (in the current directory)
   Docs/tests: the repo's full-spec.md, docs\, messaging.md and the related *.spec.ts / e2e tests.
   Also search any other directory added to this session.
   Scope: the ENTIRE app and all roles (guest, buyer, seller, admin), checked against BOTH
   the mobile app and the admin web, plus everything else in the redspur backend repo.
   Never limit the search to guest flows or to one app.
   - Used in App? = YES: full param/field/file audit.
   - Used in App? = NO: first verify the sheet's claim (no caller in mobile or admin web),
     then do the full audit anyway.
   - Report any call site found in a flow the Usage Note does not list.
   The report must include the "Test design inputs", "Source agreement matrix" and "Suggested test scenarios"
   sections. Current code is evidence of actual behaviour, not of expected behaviour; requirement/spec/code
   conflicts are recorded, not resolved.
5. Show me the report, then save it to audits\EP-NNN.md in the current directory.
   Write nothing else anywhere.
