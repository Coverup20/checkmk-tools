# Ydea API v2 — Reference

Consolidated notes on the Ydea Cloud API as used by the Nethesis tooling
(toolkit, CheckMK notifications, Ydea Reports, ad-hoc research). Facts marked
**\[verified]** were confirmed against the live instance; everything else comes
from the vendor documentation or from the toolkit's own code.

* Vendor portal: [https://my.ydea.cloud](https://my.ydea.cloud)
* Vendor API docs: [https://my.ydea.cloud/api/doc/v2](https://my.ydea.cloud/api/doc/v2)
* Base URL: `https://my.ydea.cloud/app\_api\_v2`
* Knowledge snapshot: 2026-11-16 (API exploration 2026-10-12 → 2026-11-09)

\---

## 1\. Authentication

### 1.1 Credentials

Created in the portal: **Settings → My Company → API** → copy **ID** and
**API Key**. They are long-lived (not per-user).

Store them in an env file, never in code:

```bash
export YDEA\_ID="<company id>"
export YDEA\_API\_KEY="<api key>"
export YDEA\_BASE\_URL="https://my.ydea.cloud/app\_api\_v2"   # optional, default
export YDEA\_TOKEN\_FILE="$HOME/.ydea\_token.json"           # optional, default
```

Multiple accounts (e.g. one per operator) use separate env files and separate
token files: `.env.ag` / `.env.la` write to `\~/.ydea\_token\_ag.json` and
`\~/.ydea\_token\_la.json`. The plain `.env` file in this repo also pins
`YDEA\_TOKEN\_FILE` to `\~/.ydea\_token\_ag.json` — always secure the token file
that is actually written, not the one implied by the default name.

### 1.2 Login

```http
POST https://my.ydea.cloud/app\_api\_v2/login
Content-Type: application/json

{"id": "<YDEA\_ID>", "api\_key": "<YDEA\_API\_KEY>"}
```

Response: a JSON object carrying the JWT in one of `token`, `access\_token`,
`jwt`, `id\_token` (the toolkit accepts any of them) **\[verified]**.

**A wrong API key fails here with `401 Unauthorized`** and nothing else in the
pipeline reports it — see §9.

### 1.3 Token lifecycle

* TTL: **1 hour** from issuance. This is normal and expected; the token is not
supposed to be refreshed by a long-lived session.
* The toolkit caches it as JSON with
`{"token", "scheme": "Bearer", "obtained\_at", "expires\_at"}` (epoch seconds)
and treats it as valid until `expires\_at - 60 s` (`YDEA\_EXPIRY\_SKEW`).
* Every non-login call sends `Authorization: Bearer <token>`.
* On `401` the toolkit performs one re-login and retries the same request once
**\[verified in code]**.
* There is no refresh token: renewal = a new `POST /login`.

Renew proactively (belt and braces, e.g. every 50 minutes) when a long-running
integration cannot tolerate one failed call:

```cron
\*/50 \* \* \* \* . /opt/ydea-toolkit/.env \&\& cd /opt/ydea-toolkit \&\& \\
  python3 ydea-toolkit.py login >> /var/log/ydea-token-renewal.log 2>\&1
```

### 1.4 Web UI vs API credentials — different worlds

The portal web login is **email + password** with a CSRF token
(`GET /login` → form fields `\_csrf\_token`, `\_username`, `\_password`; success
redirects to `/dashboard/<id>`). A Bearer API token is **rejected** on web
pages (they return the login page) **\[verified 2026-11-09]**. Anything not
exposed by the API is therefore not reachable with the API key.

\---

## 2\. Endpoint catalogue

|Method|Path|Status|Notes|
|-|-|-|-|
|POST|`/login`|works|§1.2|
|GET|`/tickets`|works|Paged list. `page`, `limit`; `search`/`q` **silently ignored**|
|GET|`/ticket/{id}`|works|Singular form. Returns `{ticket, atks}`|
|GET|`/tickets/{id}`|**404**|Plural does not accept an id|
|POST|`/ticket`|works|Create a ticket|
|PATCH|`/tickets/{id}`|works|Update (plural) — see the naming quirk|
|POST|`/ticket/atk`|works|Add a note/comment to a ticket|
|GET|`/users`|works|534 users **\[verified 2026-11-09]**|
|GET|`/progetti`|works|195 projects **\[verified 2026-11-09]**, plain list|
|GET|`/tasks`|works|485 tasks **\[verified 2026-11-09]**, plain list|
|GET|`/categories`|works|Category catalogue used by ticket creation|
|GET|`/sla`|404|No SLA endpoint|
|GET|`/stati`, `/status`, `/statuses`, `/ticket/stati`|404|No state catalogue|
|GET|`/ticket/{id}/history`|404|No history|
|GET|`/ticket/{id}/<anything>`|catch-all|Returns the same `{ticket, atks}` payload or 404|

There is **no status-change / assignment / audit history** in the API
**\[verified 2026-11-09 on a 5-ticket sample and a 120-ticket note sample]**.
Subpaths like `storico`, `stati`, `logs`, `timeline`, `audit`, `changelog`
behave as the same catch-all: no error, no additional data.

\---

## 3\. Tickets — list

```http
GET /tickets?page=1\&limit=20
```

Envelope **\[verified]**:

```json
{
  "objs": \[ { ...ticket... } ],
  "currentPage": 1,
  "lastPage": 472,
  "n\_results": 9434,
  "show\_per\_page": 20
}
```

Hard facts learned the hard way:

* **Page size is fixed at 20.** `limit` is accepted but the API returns 20;
`n\_results` is the real total.
* **`search` / `q` are ignored server-side.** The endpoint always returns the
most recent listing regardless of the term. Text search must be done
client-side after pagination.
* Throughput: ≈0.9 s per page with a 0.15 s pause between pages (472 pages,
0 failures) **\[verified 2026-10-13]**.
* A full pull of \~9,758 tickets costs \~8 minutes; a full per-ticket detail
enrichment costs \~0.73 s/ticket (\~2 hours) — design around the list, not the
detail.
* Listing fields are a **slim** subset: `dataChiusura` is absent here and only
present in `/ticket/{id}`.

Ticket fields seen in the list:
`id`, `codice` (`TKyy/nnnnnn`), `titolo`, `descrizione` (HTML, avg \~23 KB, up
to 12 MB), `stato`, `priorita`, `tipo` (product category, not problem type),
`fonte`, `ragioneSociale`, `anagrafica\_id`, `dataCreazione`, `dataModifica`,
`assegnatoA` (current assignees only, id→name, no timestamp).

\---

## 4\. Tickets — detail

```http
GET /ticket/<id>
```

Returns `{"ticket": {...}, "atks": \[...]}`. The ticket object carries \~30 keys:
the list fields plus `dataChiusura`, `customAttributes`, `eventiPianificati`,
and the note collection in `atks`.

* `customAttributes` today holds only `TIPOLOGIA INTERVENTO`
(7 values: Assistenza prodotto Nethesis, Consulenza specialistica,
Installazione, Assistenza prodotto altri fornitori, Gestione allarmi,
Formazione, none).
* `eventiPianificati` is empty in normal tickets.
* Notes (`atks`): author, text, `pubblico` flag, timestamp. `tipo` is `None`
and authors are human — **no system events**, so assignment, state changes
and SLA touches are not recorded anywhere in the payload.

\---

## 5\. Tickets — create, update, comment

### 5.1 Create

```http
POST /ticket
{
  "titolo":        "…",
  "testo":         "…",              // description (plain text or markdown)
  "priorita":      20,               // 10 high/critical, 20 normal, 30 low
  "azienda":       <anagrafica id>,
  "anagrafica\_id": <same id>,
  "contatto":      773763,           // default contact
  "fonte":         "Partner portal",
  "condizioneAddebito": "C",
  "contrattoId":   <contract id>,    // optional
  "sla\_id":        <sla id>,         // optional, only meaningful without contrattoId
  "tipo":          "…",              // optional product category
  "creatoda":      <user id>         // optional author
}
```

Toolkit rules and defaults:

* Priority map: `low/bassa → 30`, `normal/normale/media → 20`,
`high/alta/urgent/critical → 10`.
* `YDEA\_AZIENDA` is **mandatory** in the env file (anagrafica id);
`YDEA\_CONTATTO` defaults to `773763`; `YDEA\_CONTRATTO\_ID` is optional.
* `sla\_id` is only sent when no contract id is configured.
* Anagrafica (customer) lookup: `GET /anagrafica` style exploration exists in
`full/explore\_anagrafica.py` / `search\_anagrafica.py`; ids come from there.

### 5.2 Update

```http
PATCH /tickets/<id>
{ "…fields…": "…" }
```

Note the plural path here versus the singular `/ticket/{id}` used for reads
and creates. This asymmetry is real **\[verified]**.

### 5.3 Comment / private note

```http
POST /ticket/atk
{
  "ticket\_id": 12345,
  "atk": {
    "descrizione": "…",
    "pubblico": false,        // false = private note, invisible to the customer
    "creatoda": 4675          // user id (YDEA\_USER\_ID\_CREATE\_NOTE)
  }
}
```

This is the mechanism behind "add a private note on every CheckMK state
change". Public replies (`pubblico: true`) are what the customer sees and are
the basis of the response-time metrics in Ydea Reports.

### 5.4 Close (legacy helper — handle with care)

The toolkit's `close` command sends
`PATCH /tickets/{id}` with `{"status": "closed", "closing\_note": "…"}`. The
real instance uses **Italian state names** (`Effettuato`, `Chiuso`) in
payloads, and this helper has not been validated against the current state
model. Prefer an explicit `PATCH` with the state value you actually mean, and
verify the result on one ticket before scripting it.

\---

## 6\. States

Census of 2026-11-09 (9,758 tickets):

|`stato`|Meaning|Count|
|-|-|-|
|Nuovo|New|1|
|In attesa da noi|Waiting on us|50|
|In attesa del cliente|Waiting on the customer|96|
|In lavorazione|In progress|30|
|Effettuato|Resolved, pending auto-close|4,657|
|Chiuso|Closed (terminal)|4,924|

Domain rule (confirmed by the customer side, 2026-11-09): a ticket in
**Effettuato** stays there for a configured number of hours and then
auto-closes to **Chiuso** unless the customer reopens it with a reply.
"You closed it" for auto-closed tickets is the system, not an operator.

Consequences for analytics:

* There is no state catalogue endpoint; the set above comes from the data.
* `Risolto` / `Completato` still appear as legacy compatibility values.
* For `Chiuso`, `dataModifica == dataChiusura` (verified on a 15-ticket
sample), so `dataModifica` is a safe closure timestamp in listings.
* For `Effettuato`, `dataChiusura` is null and `dataModifica` is the last
activity — usable only as a proxy.
* The Effettuato→Chiuso delay is **not retroactively recoverable**
(no history). Measure it forward from snapshots
(`state\_history.jsonl` in Ydea Reports) if it matters.

\---

## 7\. Projects and tasks

```http
GET /progetti        # 195 records, plain list
GET /tasks           # 485 records, plain list
```

* The `progettoPadreId` filter on `/tasks` is **ignored** — fetch everything
and group client-side.
* `effortStimato`, `effortFinire`, `durataTotale` are in **seconds**.
* Task "done" state is the numeric value **1340**.
* Project states observed: Completato 150, In progress 43, Creato 2.
* 149 of the 485 tasks have no `progettoPadreId` and cannot be attributed.
* `responsabile` is present for 160/195 projects.
* `GET /users` returns the full user list (534) with names and ids; useful to
resolve `assegnatoA`, note authors and `isCustomerPortal` flags.

\---

## 8\. What the API does *not* provide

|Need|API|Workaround|
|-|-|-|
|State-change history|none|snapshot log going forward|
|Assignment timestamp|none|first operator note as proxy|
|SLA deadline / compliance|none (`/sla` 404)|web UI SLA panel only|
|Server-side text search|params ignored|paginate + filter|
|Bulk export|none|page through `/tickets`|
|Attachment download|not explored|`atks` references only|

The web UI does show an SLA panel (Prima Risposta / Risposta Successiva /
Chiusura with deadlines) and a Timeline tab, but the Timeline is the same note
stream as `atks`, and the SLA panel is compliance-vs-deadline, not the actual
state-change timestamps. Neither is reachable with the API key.

\---

## 9\. Tooling built on this API

### 9.1 `ydea-toolkit.py` (CLI + importable module)

Locations: `srv-monitoring-sp:/opt/ydea-toolkit/` (production, `monitoring`
user) and `vm-z1-00:/opt/ydea-toolkit/` (research replica, root, same files
and `.env\*`, sha256-verified on 2026-10-12).

CLI: `login`, `list`, `get`, `search`, `create`, `update`, `close`, `comment`,
`categories`, `users`, `api <METHOD> <PATH> \[json]`, plus the tracking
commands (`track`, `update-tracking`, `cleanup-tracking`, `stats`).

Programmatic use (this is how ad-hoc research is done on vm-z1-00):

```python
import sys, importlib.util
sys.path.insert(0, "/opt/ydea-toolkit")
spec = importlib.util.spec\_from\_file\_location("ydea\_toolkit", "/opt/ydea-toolkit/ydea-toolkit.py")
yt = importlib.util.module\_from\_spec(spec); spec.loader.exec\_module(yt)
body, status = yt.api.api\_call("GET", "/tickets?page=1\&limit=20")
```

Always look up a ticket with the **singular** endpoint
(`yt.tickets.get\_ticket(id)` → `/ticket/{id}`): listing-based lookup silently
misses anything that is not among the 20 most recent records of the shared
instance.

### 9.2 CheckMK → Ydea

* `ydea\_la`, `ydea\_ag`, `ydea\_realip` notification scripts: create a ticket on
CRITICAL/DOWN, add a private note on later state changes, flap detection,
dedup cache in `/tmp/ydea\_checkmk\_tickets.json`.
* `ydea\_cache\_validator.py` (every 15 min) and the health monitor (every
10–15 min) on `srv-monitoring-sp` keep the integration in check. These two
**create tickets automatically**; do not replicate them on another host.
* `cmk\_ydea` MCP tool (`status` / `login`) is the quickest way to test auth.

### 9.3 Ydea Reports (`monitor01` = fleet node `checkmk-vps-02`)

Flask app in `/opt/ydea-reports/`. Uses `/tickets` paging + `/ticket/{id}`
enrichment into a slim local cache, then derives metrics from note authors
(first operator note, public replies, handovers) because the API has no state
history. Working hours: Mon–Fri 09:00–17:00 Europe/Rome, max 8 h/day.

\---

## 10\. Failure modes and lessons

* **A wrong API key is invisible in `notify.log`.** CheckMK logs the rule
match and dispatch, not the script outcome. On 2026-07-27 a bad key produced
`401` on every hourly login for **16 days** with zero tickets created and no
alarm. Diagnose with `cmk\_ydea status` / `login`, or
`/var/log/ydea-toolkit.log`, `/var/log/ydea\_cache\_validator.log`.
* **"Token scaduto" is usually not a token problem.** The token renews hourly
by design; a log line `Token valido (scade tra 2700 secondi)` is the normal
cycle.
* **"Ticket #N non trovato"** for older ids means the ticket was deleted or
fell out of retention — still possible in principle, but the first thing to
check is the wrong-endpoint bug: `/tickets/{id}` is 404, `/ticket/{id}` is
the working form. The toolkit's tracking code was fixed to use the singular
endpoint for exactly this reason.
* **Retry policy**: one automatic re-login + retry on 401; otherwise fail
loudly. Silent `except: pass` around ticket creation is what hid the
16-day outage in the first place.

\---

## 11\. Security notes

* Never commit `.env` with real keys. ⚠️ **In this repository the Ydea env
files (`.env`, `.env.ag`, `.env.la`, `.env.la\_testing`) are currently
tracked by git.** Treat the keys as exposed to anyone with repo access and
rotate them if the repository was ever shared, mirrored or archived.
* `chmod 600` on every `.env\*` and on the token file actually used.
* Ticket titles, descriptions and customer names are customer data: keep them
out of chat transcripts, memory files and public artifacts; aggregate
numbers only.
* Per-account token files (`\~/.ydea\_token\_ag.json`, `\~/.ydea\_token\_la.json`)
must not be copied between machines.

\---

## 12\. Quick recipes

```bash
# auth smoke test
curl -sS -X POST https://my.ydea.cloud/app\_api\_v2/login \\
  -H 'Content-Type: application/json' \\
  -d "{\\"id\\":\\"$YDEA\_ID\\",\\"api\_key\\":\\"$YDEA\_API\_KEY\\"}" | jq -r '.token' | head -c 20

# one ticket by id
curl -sS https://my.ydea.cloud/app\_api\_v2/ticket/12345 \\
  -H "Authorization: Bearer $TOKEN" | jq '.ticket | {id, codice, stato, dataCreazione, dataModifica, dataChiusura}'

# page through everything (20 per page)
for p in $(seq 1 472); do
  curl -sS "https://my.ydea.cloud/app\_api\_v2/tickets?page=$p\&limit=20" \\
    -H "Authorization: Bearer $TOKEN" | jq -c '.objs\[] | {id, codice, stato, dataCreazione, dataModifica}'
  sleep 0.15
done > tickets.ndjson
```

\---

## 13\. Open questions

1. Real Effettuato→Chiuso delay (needs a forward snapshot log).
2. Whether any endpoint exposes state history under a name not yet tried — the
vendor docs are the only way to know; everything guessed returned the
catch-all.
3. Whether the web SLA panel can be fetched programmatically with web
credentials (email/password + CSRF), and whether that is acceptable under
the customer agreement.
4. Attachments: `atks` payloads reference files; download path unexplored.

*Related docs:* [*`README.md`*](README.md) *(toolkit usage),*
[*`README-CHECKMK-INTEGRATION.md`*](README-CHECKMK-INTEGRATION.md) *(CheckMK
notification stack).*
