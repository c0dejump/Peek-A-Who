# PAW — Peek-A-Who: Tool Context & Direction

## Purpose

PAW (Peek-A-Who) is an open-source intelligence (OSINT) investigation platform designed to aggregate publicly available information about an individual into a structured, actionable intelligence report.

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
  ├── GET  /investigation             → investigation.html (live terminal + Watson sidebar + report)
  ├── GET  /run                       → SSE stream (real-time log events)
  ├── POST /investigation/confirm     → unblocks Phase 2 at checkpoint
  ├── POST /api/investigation/chat    → Watson conversational AI (streaming SSE)
  ├── POST /api/validate_profile      → enrich + validate a found social profile
  ├── GET  /investigation/report      → Phase 3 intelligence report (current session)
  ├── GET  /config                    → config.html (API keys, LLM backend)
  ├── GET  /history                   → history.html (past investigations)
  ├── GET  /history/<filename>        → raw JSON export
  ├── GET  /history/<filename>/report → Phase 3 intelligence report (historical)
  ├── GET  /cases                     → cases.html (knowledge graph)
  ├── GET  /cases/<id>                → case.html (individual case board)
  └── GET  /api/llm-status            → Watson LLM health status (idle/warming/ready/unavailable)

Flask app (app.py)
  └── paw_agent/
      ├── engine/
      │   ├── runner.py         ← Investigation thread manager + SSE buffer + history saving
      │   ├── pipeline.py       ← Main orchestrator: no MCP, imports skills directly, litellm synthesis
      │   ├── agent.py          ← Legacy Phase 1 helpers (transitional; pipeline.py imports from it)
      │   ├── mcp_server.py     ← Thin MCP wrapper for external tool-calling (LangChain, Dify…)
      │   └── permuter.py       ← Email permutation generator
      ├── case_store.py         ← Knowledge graph cases (nodes, edges, facts)
      └── config_manager.py     ← .env read/write, Ollama model discovery

  skills/                       ← Modular OSINT skills (standalone + importable)
      core/
          evidence.py           ← Confidence layer: confirmed/probable/low/rejected
                                   build_context_summary() for LLM context
          agents.py             ← 5 rule-based specialist agents (no LLM, <100ms):
                                   identity, social, geo, timeline, correlation
          osint_knowledge.py    ← Watson system prompt: OSINT methodology, pivoting,
                                   French sources, platform techniques
          watson_tools.py       ← 9 Watson tools + execute_tool() dispatcher
      social_media/
          instagram.py          ← Instagram detection (facebookexternalhit UA)
          platforms.py          ← Multi-platform parallel detection
          maigret.py            ← 36-site username scan via maigret CLI
          sherlock.py           ← 36-site username scan via sherlock CLI
          ig_lookup.py          ← Instagram username → obfuscated email + phone
          tiktok.py             ← TikTok deep check (embedded JSON)
          linkedin.py           ← LinkedIn slug candidate generation
          enrich.py             ← Profile enrichment (bio, followers, links)
      email/
          smtp_validate.py      ← SMTP validation + SERP presence check
          hibp.py               ← HaveIBeenPwned breach check
          ghunt.py              ← GHunt Google account OSINT
      phone/
          lookup.py             ← phonenumbers + ignorant + PhoneInfoga
      identity/
          diplomas.py           ← theses.fr, HAL, bac/brevet
          etymology.py          ← French surname demographics (filae.com)
```

### Key design decisions

**SSE (Server-Sent Events) streaming** — Every investigation runs in a background thread. Results are buffered in `Investigation.log` and streamed live to the browser. Watson also uses SSE for token-by-token streaming of LLM responses.

**Clean Hybrid Architecture** (as of 2026-06-08):
- **pipeline.py**: Single clean orchestrator. No MCP subprocess. Imports skills directly. Calls litellm for synthesis (2× per investigation: checkpoint + final). runner.py imports `run_investigation` from pipeline.py.
- **runner.py**: Detects `[Step X]` markers in pipeline log lines and auto-emits `progress` SSE events for the UI progress bar.
- **agent.py**: Legacy helpers kept for Phase 1 functions. Will migrate to skills/ over time.
- **mcp_server.py**: Thin MCP wrapper over skills, kept for external tool-calling. Not used by the internal pipeline.
- **Skills**: Standalone Python modules — each has `run_sync()`, `async run()`, CLI interface, no internal state.

**Investigation progress bar** — Live step tracker in the investigation UI:
- `runner.py` intercepts `[Step X]` markers in pipeline log output and emits `{type: "progress", step, label, phase, status}` events
- `investigation.html` renders a compact strip above the terminal: phase label + step pills (pending/running/done) + progress bar
- Phase 1 → Phase 2 transition is detected automatically (step pill set switches)
- Strips hides automatically 1.8s after investigation completes

**Watson** — AI investigation partner, fixed right sidebar in the investigation UI:
- Powered by a dedicated `WATSON_LLM_BACKEND` (lighter, faster model than the pipeline synthesis model)
- Streams responses token-by-token via SSE — first token appears in < 1s
- Tool-use loop: runs 10 OSINT tools (web_search, sherlock_check, email_osint, **record_to_case**, …) then synthesises
- `record_to_case(platform, username)` — Watson saves found accounts directly to the case store via tool call; no regex needed
- Minimal command parser (2 patterns only: `^add @user to case`, `^investigate @user`); everything else → LLM + tools
- Pre-flight Ollama health check (4s) + model existence check — fails fast instead of waiting 120s
- Status dot in header: green (ready), amber (loading), red (offline)

**Multi-agent synthesis** (Phase 3):
- 5 deterministic rule-based agents produce structured domain briefings in < 100ms each
- Single LLM call receives all 5 briefings → produces full JSON report with hypotheses, pivots, timeline, risk indicators
- Falls back to rule-based analysis if no LLM

---

## Investigation Phases

### Phase 1 — Passive intel (no login, no account queries)

| Step | Module | What it does |
|---|---|---|
| 0 | `etymology` | Surname rarity + geographic origin (filae.com) |
| 0.5 | `diplomas` | theses.fr, HAL, bac/brevet |
| 0.7 | demographics | SIRENE + Pappers business registry |
| 0.8 | — | Pages Blanches / Pages Jaunes search URLs |
| 0.9 | `phone` | phonenumbers + ignorant + PhoneInfoga |
| 0.93 | `maigret` + `sherlock` | **Username pre-validation** — ALL candidates on 36 targeted sites, 20 parallel workers |
| 0.95 | `instagram` | Validated candidates only (≥1 maigret/sherlock hit) |
| 0.95b | `ig_lookup` | Obfuscated email + phone for each Instagram profile |
| 0.95c | `tiktok` | TikTok deep check (embedded JSON) |
| 0.95d | `linkedin` | LinkedIn slug candidates |
| 0.96 | `platforms` | Twitter/X, Snapchat, BeReal, Telegram, Facebook |
| 0.99 | LLM | **Confirmation checkpoint** — IDENTITY / TIMELINE / LOCATIONS |

### Phase 2 — Active OSINT (after confirmation)

| Step | Module | What it does |
|---|---|---|
| 1 | `permuter` | Email permutation (hundreds of candidates) |
| 2 | `smtp_validate` | SMTP validation + SERP presence |
| 2b | `ghunt` | Google account probe |
| 3 | `hibp` | HIBP breach history |
| 4 | `agents` + LLM | **Phase 3 multi-agent synthesis** → full intelligence report JSON |

### Phase 3 — Intelligence Report

After Phase 2, 5 specialist agents analyse the full report data:
- **Identity agent** — confirms name, birth year, cross-validates against sources
- **Social agent** — active/inactive platforms, username pattern, behavioral signals
- **Geo agent** — confirmed/probable locations, location evolution, cross-confirmation
- **Timeline agent** — chronological events, last known activity, activity span
- **Correlation agent** — links between findings, anomalies, coherence score

All 5 briefings feed a single LLM call producing structured JSON:
```json
{
  "executive_summary": "...",
  "global_confidence": 0.78,
  "identity": { "confirmed": [...], "probable": [...], "rejected": [...] },
  "digital_presence": { "active_platforms": [...], "username_pattern": "..." },
  "geolocation": { "confirmed": [...], "current_estimate": "Paris, 75" },
  "hypotheses": [{ "claim": "...", "confidence": 0.8, "evidence_for": [...] }],
  "pivot_suggestions": [{ "action": "...", "priority": "high" }],
  "risk_indicators": [...],
  "timeline": [...]
}
```

---

## Watson — AI Investigation Partner

Watson is a persistent AI partner in the investigation sidebar, not a chat popup.

### How Watson works

1. **Command parser** (no LLM, instant) — matches quick actions:
   - `"add @username to case"` → calls `/api/validate_profile` + case injection
   - `"investigate @username"` → enriches profile
   - `"bereal @peanaths"` / `"trouvé le bereal c'est peanaths"` → records platform finding
   - `"search [query]"` → passes to LLM

2. **Tool-use loop** (OSINT tools, no LLM for tool calls):
   - Watson calls tools like `web_search`, `sherlock_check`, `email_osint`
   - Each tool is a direct Python call into the skills layer
   - Results are injected into the LLM context for synthesis

3. **LLM synthesis** (streaming):
   - Uses `WATSON_LLM_BACKEND` (lighter model) separate from pipeline synthesis model
   - Streams tokens via SSE — response appears immediately
   - System prompt from `osint_knowledge.py` — full OSINT methodology knowledge base

### Watson configuration

```env
LLM_BACKEND=ollama/qwen3:14b          # pipeline synthesis (quality > speed)
WATSON_LLM_BACKEND=ollama/qwen3:14b   # Watson chat (speed > quality)
```

Recommended Watson models (fast, OSINT-capable):
- `ollama/qwen3:14b` — 9GB, best reasoning, handles tools well
- `ollama/qwen2.5:7b` — 4.7GB, ~3s first token on CPU, good reasoning
- `ollama/llama3.2:3b` — 2GB, ~1s first token, lighter but capable

### Watson tools (10 total)

| Tool | What |
|---|---|
| `record_to_case` | Save found social profile to case store (direct Python call, no API round-trip) |
| `web_search` | DuckDuckGo with operators (site:, inurl:, "exact phrase") |
| `instagram_lookup` | Obfuscated email/phone hint via IG API |
| `sherlock_check` | Cross-platform username presence |
| `enrich_profile` | Bio, followers, links |
| `email_osint` | SMTP + HIBP + GHunt + SERP |
| `phone_lookup` | Carrier, region, social platforms |
| `web_archive` | Wayback Machine first/last snapshot |
| `whois_lookup` | Registrar, dates, org |
| `validate_email_batch` | SMTP-validate a list of email candidates |

---

## Username Candidate Generation

Candidates generated in strict priority order:

1. **Pseudo** (user-provided, exact)
2. **Keywords** alone + combos: `kw`, `fn.kw`, `kw.fn`, `ln.kw`
3. **Name combos**: `fn.ln`, `ln.fn`, abbreviations
4. **Name + year**: `fn.ln90`, `fn.ln1990`
5. **Name + dept code**: `fn.ln75`

All candidates checked by **pre-validation** (Step 0.93) via maigret + sherlock on 36 targeted sites. Only those with ≥1 hit proceed.

---

## Relevance Scoring

| Signal | Points |
|---|---|
| Lastname in display name | +5 |
| Firstname in display name | +4 |
| Keyword in username | +3 |
| Keyword in display name / bio | +3 |

Score ≥ 7 → high (green) · Score ≥ 4 → medium (orange) · Score < 4 → low (grey)

---

## Evidence Confidence Levels

Every finding carries a confidence level:

| Level | Meaning |
|---|---|
| `confirmed` | Multiple independent sources agree, or primary source directly states it |
| `probable` | One strong source or multiple weak signals pointing the same direction |
| `low` | Single weak signal, indirect inference, or unverifiable claim |
| `rejected` | Contradicted by evidence or logic |

---

## LLM Backend Support

| Provider | Config | Notes |
|---|---|---|
| Ollama (local) | `LLM_BACKEND=ollama/model` | Free, private, offline |
| Groq | `GROQ_API_KEY=gsk_...` | Fast inference, free tier |
| Google Gemini | `GEMINI_API_KEY=AIza...` | 1M tokens/day free |
| Anthropic Claude | `ANTHROPIC_API_KEY=sk-ant-...` | Best quality |
| OpenAI | `OPENAI_API_KEY=sk-...` | GPT-4o |

Two separate models can be configured:
- `LLM_BACKEND` — pipeline synthesis (quality matters, can be slow)
- `WATSON_LLM_BACKEND` — Watson chat (speed matters, should respond in < 5s)

---

## Configuration

All secrets in `.env`. Web UI at `/config` manages all keys.

| Variable | Purpose | Required |
|---|---|---|
| `LLM_BACKEND` | Pipeline LLM synthesis | Recommended |
| `WATSON_LLM_BACKEND` | Watson chat model (lighter) | Optional (falls back to LLM_BACKEND) |
| `OLLAMA_API_BASE` | Ollama host URL | Default: `http://localhost:11434` |
| `HIBP_API_KEY` | HIBP breach data | Optional but strongly recommended |
| `PAPPERS_API_KEY` | Business registry (free tier) | Optional |
| `TRUECALLER_TOKEN` | Caller ID for French numbers | Optional |
| `FLASK_SECRET` | Session security | Auto-generated if missing |

---

## Technical Stack

- **Backend**: Python 3.12, Flask, asyncio, threading
- **LLM**: litellm (direct, no MCP subprocess) — supports Ollama, OpenAI, Anthropic, Groq, Gemini
- **HTTP**: `requests` (sync, in executors)
- **Parallelism**: `concurrent.futures.ThreadPoolExecutor` for platform checks
- **Frontend**: Vanilla JS + CSS, SSE for real-time streaming (investigation log + Watson streaming), marked.js for Markdown
- **No database**: all state is in-memory per investigation session; history auto-saved to `history/*.json`
- **External CLI tools**: `maigret`, `sherlock-project`, `ghunt`, `ignorant` (all via pip)

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
- Store or transmit personal data beyond the local session

All data collected is publicly accessible. Investigators are responsible for compliance with applicable laws (GDPR, local privacy regulations) and platform terms of service.
