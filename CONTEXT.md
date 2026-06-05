# PAW — Peek-A-Who: Tool Context & Direction

## Purpose

PAW (Peek-A-Who) is an open-source intelligence (OSINT) investigation tool designed to aggregate publicly available information about an individual into a structured, actionable report.

**Primary mission: help locate missing persons** by reconstructing their last known digital footprint — last active platforms, inferred locations, habits, and favourite places — from publicly accessible data sources without any account credentials.

PAW is also useful for:
- Verifying the identity of an online contact
- Journalists and researchers investigating public figures
- Families searching for lost relatives
- Licensed private investigators building an intelligence dossier

---

## Architecture

```
Browser (investigator)
  │
  ├── GET  /                          → home.html  (target form)
  ├── POST /investigate               → starts background investigation thread
  ├── GET  /investigation             → investigation.html (live terminal + report)
  ├── GET  /run                       → SSE stream (real-time log events)
  ├── POST /investigation/confirm     → unblocks Phase 2 at checkpoint
  ├── GET  /config                    → config.html (API keys, LLM backend)
  ├── GET  /history                   → history.html (past investigations)
  ├── GET  /history/<filename>        → raw JSON export
  ├── GET  /dossiers                  → dossiers.html (case files list)
  ├── GET  /dossiers/<did>            → dossier.html (investigation board)
  ├── POST /dossiers/new              → create dossier
  ├── POST /dossiers/<did>/fact       → add fact → triggers background investigation
  ├── DELETE /dossiers/<did>/fact/<fid> → remove fact + cascade link removal
  ├── POST /dossiers/<did>/investigate → full re-run
  ├── GET  /dossiers/<did>/stream/<inv_id> → SSE for dossier investigation
  └── GET  /dossiers/<did>/data       → current dossier JSON

Flask app (app.py)
  └── paw_agent/
      ├── engine/
      │   ├── runner.py         ← Investigation thread manager + SSE buffer + history saving
      │   ├── pipeline.py       ← Clean orchestrator: no MCP, imports skills directly, LLM via litellm
      │   ├── agent.py          ← Legacy engine (kept for Phase 1 helper functions; pipeline.py imports from it)
      │   ├── mcp_server.py     ← Thin MCP wrapper for external tool-calling use; logic lives in skills/
      │   └── permuter.py       ← Email permutation generator
      ├── dossier_store.py      ← Persistent case files (facts, findings, links, audit log)
      ├── dossier_runner.py     ← Reactive investigation: fact-triggered OSINT + LLM link synthesis
      └── config_manager.py     ← .env read/write, Ollama model discovery

  skills/                       ← Modular OSINT skills (standalone + importable)
      social_media/
          instagram.py          ← Instagram username detection (CLI + importable)
          platforms.py          ← Multi-platform parallel detection (CLI + importable)
          maigret.py            ← Maigret cross-platform wrapper (CLI + importable)
          ig_lookup.py          ← Instagram username lookup by USERNAME (obfuscated email/phone)
      email/
          smtp_validate.py      ← SMTP validation (run_sync, validate_batch, validate_all, async run)
          hibp.py               ← HaveIBeenPwned breach check (run_sync, async run)
          ghunt.py              ← GHunt Google account OSINT (run_sync, async run)
          permutation.py        ← Email permutation generator
      phone/
          lookup.py             ← Phone OSINT (phonenumbers + ignorant + links)
      identity/
          diplomas.py           ← Academic records (theses.fr, HAL, bac/brevet)
          etymology.py          ← French surname demographics (filae.com)
```

### Key design decisions

**SSE (Server-Sent Events) streaming** — Every investigation runs in a background thread. Results are buffered in `Investigation.log` and streamed live to the browser. Clients can reconnect at any time and replay from `start_idx=0`.

**Clean Hybrid Architecture** (as of 2026-06-05):
- **pipeline.py**: Single clean orchestrator. No MCP subprocess. Imports skills directly. Calls litellm directly for synthesis (2× per investigation: checkpoint + final summary). runner.py now imports `run_investigation` from pipeline.py.
- **agent.py**: Legacy engine kept for Phase 1 helper functions (`_search_diplomas_direct`, `_search_instagram_direct`, etc.). pipeline.py imports these transitionally. Will gradually move to skills/.
- **mcp_server.py**: Thin MCP wrapper over skills, kept for external tool-calling (LangChain, Dify, custom LLM agents). No longer used by the internal pipeline.
- **Skills**: Standalone Python modules in `skills/` — each has `run_sync()`, `async run()`, CLI interface, and no internal state.

---

## Investigation Phases

### Phase 1 — Passive intel (no login, no account queries)

Runs automatically when an investigation starts. All data sources are public APIs or HTML scraping.

| Step | Module | What it does |
|---|---|---|
| 0 | demographics | Surname rarity + geographic origin (filae.com) |
| 1 | diplomas | theses.fr, HAL, bac/brevet results (linternaute) |
| 2 | demographics | SIRENE + Pappers business registry |
| 3 | phone | phonenumbers + ignorant + PhoneInfoga |
| 0.95 | social_media | Instagram username detection (title-based) |
| 0.96 | social_media | Twitter/X, TikTok, Snapchat, BeReal, LinkedIn (parallel) |
| 0.97 | social_media | maigret cross-platform scan (500+ sites) |
| 0.98 | social_media | Reddit last activity + GitHub location enrichment |
| 0.99 | — | **Confirmation checkpoint** (LLM synthesis → user confirm) |

### Confirmation checkpoint

After Phase 1, the LLM produces a three-section synthesis:
- `IDENTITY` — who this person appears to be
- `TIMELINE` — chronological last known online activities
- `LOCATIONS` — inferred cities/regions

This is displayed as a confirmation card in the browser. The investigator reviews it and decides:
- **Continue** → Phase 2 runs (email OSINT + breach data)
- **Stop** → report is generated with Phase 1 data only

This checkpoint exists to confirm the right person has been identified before running more intrusive queries.

### Phase 2 — Active OSINT (after confirmation)

| Step | Module | What it does |
|---|---|---|
| 1 | email | Email permutation generation (hundreds of candidates) |
| 2 | email | SMTP validation + GHunt Google account probe |
| 3 | email | HIBP breach history (requires API key) |
| 4 | — | LLM final report with all findings |

---

## Module Details

### `demographics`
- **filae.com** etymology: surname bearer count per birth period, top geographic departments
- **SIRENE API** (data.gouv.fr): company registration by director name
- **Pappers API**: company roles, SIREN, location
- **Pages Blanches / Pages Jaunes**: generates manual search URLs

### `diplomas`
- **theses.fr API**: PhD dissertations filtered by exact author match (both firstname + lastname, whole-word, accent-insensitive)
- **HAL.science**: publications filtered by exact author match
- **linternaute bac/brevet**: exam results filtered by both firstname AND lastname match

### `email`
- **permuter.py**: generates realistic email permutations (first.last@, flast@, lastfirst@, + keyword variants, birth year variants)
- **isitarealemail.com SMTP**: validates custom/corporate domains
- **GHunt**: Google account existence + metadata (Gaia ID, name, photo, Maps reviews)
- **HIBP v3 API**: breach history, data classes leaked

### `phone`
- **phonenumbers** (libphonenumber): parse, validate, carrier, region, line type
- **ignorant**: social platform registration (WhatsApp, Telegram, Snapchat, Instagram)
- **PhoneInfoga**: generates reverse lookup links

### `social_media`
- **Instagram** (direct, no auth): `facebookexternalhit/1.1` UA → Instagram returns `og:title` with `(@username)` to Meta link-preview crawlers even behind login walls. Pattern: `(@username)` in og:title. Also checks Wayback CDX for first-seen date.
- **Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal** (parallel, title-based): platform-specific title pattern matching. BeReal: `bere.al/@{}`, HTTP 404 = not found.
- **Facebook**: manual search URL generation only (auth required for API)
- **maigret** (CLI subprocess): 500+ sites; categorises findings into Location/Sport, Marketplace, Gaming, Social
- **Reddit** (public JSON API): last active date, frequented subreddits (location proxy)
- **GitHub** (public API): location field, last activity, bio, commit emails
- **Instagram username lookup** (`skills/social_media/ig_lookup.py`): POST to `i.instagram.com/api/v1/users/lookup/` with `q=<username>` — returns obfuscated email + phone of the account. Technique is username-based (NOT email). No auth required. Rate-limited at 429.

---

## Username Candidate Generation

Username candidates are generated in strict priority order to ensure the most likely matches are checked first:

1. **Pseudo** (user-provided, exact)
2. **Keywords** → `kw`, `fn.kw`, `kw.fn`, `ln.kw`, `fn.ln.kw`, etc.
3. **Name combos** → `fn.ln`, `ln.fn`, abbreviations
4. **Name + year** → `fn.ln90`, `fn.ln1990`
5. **Name + dept code** → `fn.ln75`

Keywords are treated as "probable username components" because users typically provide them precisely because they are known identifiers (nicknames, abbreviations). For example, keywords `mchl` → `tristan.mchl` appears at position 2 in the list.

Up to 100 candidates are generated; Instagram checks up to 80.

---

## Relevance Scoring

Profiles found on any platform are scored 0–10:

| Signal | Points |
|---|---|
| Lastname in display name | +5 |
| Firstname in display name | +4 |
| Keyword in username | +3 |
| Keyword in display name / bio | +3 |
| Maximum | 10 |

Score ≥ 7 → high confidence (green)
Score ≥ 4 → medium confidence (orange)
Score < 4 → low confidence (grey)

---

## Report & Exports

The final report is available in three formats:
- **In-browser** — live-rendered sections per module, visible as investigation progresses
- **Markdown** (`.md`) — full structured text report, suitable for documentation
- **CSV** — tabular data, one row per finding, suitable for spreadsheet analysis
- **HTML** — self-contained printable HTML version (wraps the Markdown)

Report sections: Demographics, Phone, Emails, Breach details, Academic records, Business registries, Social platforms, Instagram, Cross-platform (maigret), Activity timeline, Annuaires, LLM summary.

---

## LLM Backend Support

PAW supports any OpenAI-compatible API:

| Provider | Config key | Notes |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | GPT-4o recommended |
| Anthropic | `ANTHROPIC_API_KEY` | Claude 3.5+ |
| Ollama | `OLLAMA_URL` | Local, free, offline |
| Groq | `GROQ_API_KEY` | Fast inference |
| OpenRouter | `OPENROUTER_API_KEY` | Multi-model routing |
| LM Studio | custom URL | Local OpenAI-compat |

If no LLM is configured, PAW falls back to the **direct pipeline** (no LLM, all modules run sequentially).

---

## Configuration

All secrets are stored in `.env` at the project root. The web UI at `/config` provides a form to manage all keys without editing the file manually.

| Variable | Module | Required |
|---|---|---|
| `HIBP_API_KEY` | email (breaches) | Optional but strongly recommended |
| `OPENAI_API_KEY` | LLM orchestration | One LLM key is recommended |
| `ANTHROPIC_API_KEY` | LLM orchestration | Alternative to OpenAI |
| `OLLAMA_URL` | LLM orchestration | Default: `http://localhost:11434` |
| `FLASK_SECRET` | session security | Auto-generated if missing |

GHunt authentication is managed separately via `ghunt login` (browser OAuth flow, persists to `~/.ghunt`).

---

## Technical Stack

- **Backend**: Python 3.12, Flask, asyncio, threading
- **LLM integration**: MCP (Model Context Protocol) client/server via `mcp` library
- **HTTP**: `requests` (sync, in executors), `aiohttp` not used (simplicity)
- **Parallelism**: `concurrent.futures.ThreadPoolExecutor` for platform checks
- **Frontend**: Vanilla JS + CSS, SSE for real-time streaming, marked.js for Markdown rendering
- **No database**: all state is in-memory per investigation session
- **External CLI tools**: `maigret` (pip), `ghunt` (pip), `phoneinfoga` (binary, bundled)

---

## Current Direction & Roadmap

### Done
- [x] Full two-phase investigation pipeline (passive → confirmation → active)
- [x] Instagram username detection — `facebookexternalhit/1.1` UA to bypass login wall; og:title contains `(@username)` for real profiles
- [x] Multi-platform detection (Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal) in parallel
- [x] BeReal added back: `bere.al/@{}`, HTTP 404 = not found
- [x] Telegram detection (personal accounts + channels/bots)
- [x] maigret cross-platform scan with categorisation
- [x] Reddit + GitHub activity signal enrichment
- [x] LLM timeline synthesis at confirmation checkpoint (IDENTITY / TIMELINE / LOCATIONS)
- [x] Keyword-first username generation (e.g. `mchl` → `tristan.mchl` at position 2)
- [x] Keyword relevance scoring in username/bio detection
- [x] Strict firstname + lastname matching for academic records
- [x] Report export (Markdown, CSV, HTML)
- [x] Live SSE streaming terminal with reconnect support
- [x] Investigation history (auto-save JSON + `/history` page)
- [x] Dossier system — persistent case files, reactive OSINT per fact, LLM link synthesis
- [x] **Skills system** — modular OSINT skills in `skills/` (standalone CLI + importable)
- [x] **Instagram username lookup** (`skills/social_media/ig_lookup.py`) — Phase 2: obfuscated email/phone from `i.instagram.com/api/v1/users/lookup/` using username as query

### Next priorities
- [ ] **Steam profile enrichment** — last online timestamp from public Steam profiles
- [ ] **Image analysis module** — facial recognition / reverse image search integration
- [ ] **PDF report export** — printable formatted report for law enforcement / families
- [ ] **Batch mode** — investigate multiple targets in sequence
- [ ] **More skills** — add `skills/identity/etymology.py`, `skills/identity/demographics.py`, `skills/email/hibp.py`, `skills/email/smtp.py`, `skills/email/ghunt.py`
- [ ] **Refactor agent.py** — migrate inline functions to `skills/` modules (agent.py imports from skills)

---

## Ethical & Legal Framework

PAW is intended for **authorised use only**:
- Families searching for a missing relative
- Law enforcement or licensed investigators
- Journalists investigating matters of public interest
- Security researchers with explicit scope

**PAW does not and must not:**
- Attempt authentication on any platform
- Perform credential stuffing or brute-force
- Scrape private or login-gated content
- Circumvent CAPTCHA or anti-bot measures
- Store or transmit personal data beyond the local session

All data collected is publicly accessible. Investigators are responsible for compliance with applicable laws (GDPR, CCPA, local privacy regulations) and platform terms of service.
