# Peek-A-Who

<p align="center">
  <img src="static/logo_PAW.png" height="200px" alt="Peek-A-Who" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" />
  <img src="https://img.shields.io/badge/framework-Flask-lightgrey.svg" />
  <img src="https://img.shields.io/badge/LLM-litellm%20%7C%20Ollama%20%7C%20Claude%20%7C%20Groq-green.svg" />
  <img src="https://img.shields.io/badge/use-authorised%20investigations%20only-red.svg" />
</p>

> **PAW** is an AI-augmented OSINT investigation platform. Feed it a name, phone, pseudo, or keywords — it runs a two-phase investigation and produces an intelligence report with hypotheses, geolocation estimates, and actionable pivot suggestions.
>
> Primary mission: **help locate missing persons** using only publicly accessible data.

---

## Features

- **Two-phase pipeline** — passive intel (Phase 1) → confirmation checkpoint → active OSINT (Phase 2)
- **Watson** — AI investigation partner (persistent sidebar, streaming, tool-use loop)
- **Multi-agent synthesis** — 5 specialist agents + LLM produce a structured intelligence report
- **Evidence confidence layer** — every finding tagged confirmed / probable / low / rejected
- **Username pre-validation** — maigret + sherlock on 36 targeted sites (Strava, Vinted, Steam, Reddit…)
- **Instagram lookup** — obfuscated email + phone via IG API (no auth required)
- **Email OSINT** — SMTP validation, GHunt, HIBP breaches, SERP presence
- **Phone OSINT** — carrier, region, WhatsApp/Telegram/Snapchat/Instagram registration
- **French sources** — Pappers, SIRENE, filae.com, theses.fr, Pages Blanches, bac/brevet
- **Facial recognition** — upload a reference photo; profiles with matching faces get confidence boost + green graph indicator (requires `face_recognition` library)
- **Real-time streaming** — live terminal via SSE, Watson responses stream token by token
- **Knowledge graph** — save findings to a visual case board with icons, location links
- **Intelligence report** — Phase 3 report with hypotheses, risk indicators, pivot recommendations
- **History** — all investigations auto-saved as JSON, viewable any time

---

## Quick start

```bash
git clone https://github.com/c0dejump/Peek-A-Who
cd Peek-A-Who

# Install dependencies
pip install -r requirements.txt

# Install OSINT CLI tools
pip install maigret sherlock-project ghunt ignorant

# Copy and edit config
cp .env.example .env
# → set LLM_BACKEND (see Configuration below)

# Run
python app.py
# → open http://localhost:5000
```

---

## Configuration

All settings live in `.env`. The web UI at `/config` lets you edit them without touching the file.

### LLM backends

PAW supports two separate models — one for the slow synthesis pipeline, one for Watson's fast chat:

```env
# Pipeline synthesis (quality > speed — can take minutes for large models)
LLM_BACKEND=ollama/qwen2.5:14b

# Watson chat (speed > quality — should respond in < 5s)
WATSON_LLM_BACKEND=ollama/qwen2.5:7b
```

| Provider | Setup |
|---|---|
| **Ollama** (local, free) | `ollama pull qwen2.5:7b` then `LLM_BACKEND=ollama/qwen2.5:7b` |
| **Groq** (free API, fast) | `GROQ_API_KEY=gsk_...` + `LLM_BACKEND=groq/llama-3.3-70b-versatile` |
| **Gemini** (free, 1M tok/day) | `GEMINI_API_KEY=AIza...` + `LLM_BACKEND=gemini/gemini-2.0-flash-exp` |
| **Claude** (paid, best quality) | `ANTHROPIC_API_KEY=sk-ant-...` + `LLM_BACKEND=anthropic/claude-sonnet-4-6` |
| **OpenAI** | `OPENAI_API_KEY=sk-...` + `LLM_BACKEND=openai/gpt-4o` |

> **Ollama tip:** avoid models over 14B for Watson unless you have a 24GB+ GPU. `qwen2.5:7b` or `llama3.2:3b` are the sweet spot for interactive use.

### Optional API keys

| Variable | What | Where to get |
|---|---|---|
| `HIBP_API_KEY` | Email breach history | [haveibeenpwned.com/API/Key](https://haveibeenpwned.com/API/Key) — $3.50/month |
| `PAPPERS_API_KEY` | French business registry | [pappers.fr/api](https://www.pappers.fr/api) — free tier |
| `TRUECALLER_TOKEN` | Caller ID for French numbers | Browser session token from Truecaller |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | Telegram lookup | [my.telegram.org](https://my.telegram.org) |
| `REACHER_URL` | Enhanced SMTP validation | `docker run -p 8080:8080 reacherhq/backend` |

---

## Watson — AI Investigation Partner

Watson is a permanent AI sidebar in the investigation UI. You can:

- **Ask anything** in natural language — Watson reasons about the investigation data and can search the web, check platforms, look up emails, etc.
- **Record findings** without typing commands:
  - `"found bereal @peanaths"` → records BeReal account instantly
  - `"j'ai trouvé le tiktok c'est johndoe"` → French understood natively
  - `"add @username to case"` → adds profile to the knowledge graph
- **Use quick actions** — buttons generated automatically per found profile
- **Follow suggested pivots** — Watson proposes next investigative steps based on findings

Watson uses a lightweight model (`WATSON_LLM_BACKEND`) and streams responses token by token so you see activity immediately.

---

## Investigation flow

```
1. Fill in the form (firstname, lastname, pseudo, keywords, birth year, location)
   ↓
2. Phase 1 runs automatically
   • Surname demographics, diplomas, business registries
   • Phone OSINT (carrier, social platform registration)
   • Username pre-validation (maigret + sherlock on 36 sites)
   • Instagram, TikTok, Snapchat, BeReal, Twitter, Telegram, LinkedIn
   • ig_lookup → obfuscated email/phone per Instagram account
   ↓
3. Confirmation checkpoint
   • LLM synthesises IDENTITY / TIMELINE / LOCATIONS
   • You review and decide: continue or stop
   ↓
4. Phase 2 (after confirmation)
   • Email permutation → SMTP validation → GHunt → HIBP
   ↓
5. Phase 3 — Intelligence Report
   • 5 specialist agents → LLM synthesis
   • Hypotheses with confidence scores
   • Pivot suggestions
   • Risk indicators
   • Printable intelligence report
```

---

## Architecture

```
Flask (app.py)
  └── paw_agent/engine/
      ├── pipeline.py    ← main orchestrator (no MCP, direct skill calls)
      ├── runner.py      ← SSE stream + investigation thread
      └── permuter.py    ← email permutation

  skills/
      core/
          evidence.py        ← confidence layer
          agents.py          ← 5 specialist agents
          osint_knowledge.py ← Watson OSINT knowledge base
          watson_tools.py    ← 9 Watson OSINT tools
      social_media/          ← Instagram, TikTok, maigret, sherlock, enrich…
      email/                 ← SMTP, GHunt, HIBP
      phone/                 ← phonenumbers, ignorant
      identity/              ← etymology, diplomas
      face/                  ← face_match.py — encode + compare (dlib/face_recognition)
```

See [CONTEXT.md](CONTEXT.md) for full architecture details and [SKILLS.md](SKILLS.md) for investigation methodology.

---

## External tools required

```bash
pip install maigret          # cross-platform username scanner
pip install sherlock-project # cross-platform username scanner
pip install ghunt            # Google account OSINT
pip install ignorant         # phone → social platform registration
ghunt login                  # one-time browser OAuth (for Gmail OSINT)
```

---

## Legal & Ethical

PAW is intended for **authorised investigations only**:
- Families searching for missing relatives
- Law enforcement and licensed investigators
- Journalists covering matters of public interest

PAW does **not** and must **not** attempt authentication, credential stuffing, or scraping of private content. All sources are publicly accessible. Users are responsible for GDPR and local privacy law compliance.

