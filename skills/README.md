# PAW Skills

Each skill is a self-contained OSINT module. Each can be:
1. **Run standalone** from the CLI (returns JSON on stdout)
2. **Imported** and called from `paw_agent/engine/pipeline.py` or any other Python code
3. **Called by Watson** (the AI investigation partner) via the tool-use loop in `/api/investigation/chat`

All skill functions expose a consistent interface:
- `run_sync(...)` — synchronous, usable anywhere
- `async run(...)` — async wrapper for pipeline use
- CLI via `python -m skills.<category>.<skill> [args]`

---

## Inventory

```
skills/
  core/
    evidence.py        ← Evidence confidence layer (confirmed/probable/low/rejected)
                         build_context_summary() — compact LLM context from full report
    agents.py          ← 5 deterministic specialist agents (no LLM, <100ms each):
                         run_identity_agent, run_social_agent, run_geo_agent,
                         run_timeline_agent, run_correlation_agent, run_all_agents
    osint_knowledge.py ← Watson OSINT knowledge base: full system prompt with
                         investigation methodology, pivoting strategies, French sources,
                         platform-specific techniques, identity correlation methods
    watson_tools.py    ← Watson's 9 active OSINT tools + execute_tool() dispatcher
                         (web_search, instagram_lookup, sherlock_check, enrich_profile,
                         email_osint, phone_lookup, web_archive, whois_lookup,
                         validate_email_batch)

  social_media/
    instagram.py       ← Instagram username detection (og:title via facebookexternalhit UA)
    platforms.py       ← Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal
    maigret.py         ← 36 targeted sites via maigret CLI subprocess
    sherlock.py        ← 36 targeted sites via sherlock CLI subprocess
    ig_lookup.py       ← Instagram account lookup by USERNAME → obfuscated email + phone
    tiktok.py          ← TikTok deep check (embedded JSON, uniqueId field)
    linkedin.py        ← LinkedIn slug candidate generation (automated check blocked)
    enrich.py          ← Profile enrichment: bio, followers, links (Instagram, TikTok,
                         GitHub, Reddit, generic)

  email/
    smtp_validate.py   ← SMTP validation + DDG SERP presence check
                         validate_batch(), run_sync(), async run()
    ghunt.py           ← GHunt CLI — Gmail existence + Gaia ID + Maps reviews
    hibp.py            ← HaveIBeenPwned v3 breach history (requires HIBP_API_KEY)

  phone/
    lookup.py          ← phonenumbers + ignorant + PhoneInfoga links

  identity/
    etymology.py       ← French surname rarity + geographic distribution (filae.com)
    diplomas.py        ← theses.fr + HAL + bac/brevet (linternaute.com)

  face/
    face_match.py      ← Facial recognition: encode_face(path) → 128-dim vector,
                         compare_face_url(encoding, url) → {matched, distance, confidence}
                         Uses face_recognition (dlib). Degrades gracefully if not installed.
                         Called automatically from api_validate_profile when a reference photo
                         was uploaded and the validated profile has a profile_pic URL.

  utils/               ← Shared helpers (normalisation, HTTP helpers, etc.)
```

> **Email permutation** — `paw_agent/engine/permuter.py` (pure logic, no network).
> **Business registries** — `_search_sirene_pappers_direct()` in agent.py (not yet a standalone skill).

---

## Watson tools (skills/core/watson_tools.py)

Watson calls these tools actively during conversations when it needs fresh data.

| Tool | What it does |
|---|---|
| `web_search(query, num_results)` | DuckDuckGo HTML search — supports operators (site:, inurl:, filetype:, "exact phrase") |
| `instagram_lookup(username)` | Username → obfuscated email/phone hint via IG API |
| `sherlock_check(username)` | Cross-platform username check via sherlock |
| `enrich_profile(platform, username, url)` | Bio, followers, links from Instagram/TikTok/GitHub/Reddit |
| `email_osint(email)` | SMTP + HIBP + GHunt + SERP presence |
| `phone_lookup(phone)` | Carrier, region, social platform registration |
| `web_archive(url)` | Wayback Machine first/last snapshot dates |
| `whois_lookup(domain)` | Domain registration data (registrar, dates, org) |
| `validate_email_batch(emails)` | SMTP-validate a list of email candidates |

---

## Quick examples

```bash
# Instagram scan
python -m skills.social_media.instagram --firstname Jean --lastname Dupont --keywords jd

# Multi-platform scan
python -m skills.social_media.platforms --firstname Jean --lastname Dupont

# Maigret cross-platform (36 targeted sites)
python -m skills.social_media.maigret jean.dupont jdupont

# Sherlock cross-platform (36 targeted sites)
python -m skills.social_media.sherlock jean.dupont jdupont

# Instagram lookup by username
python -m skills.social_media.ig_lookup johndoe

# TikTok deep check
python -m skills.social_media.tiktok johndoe

# Profile enrichment
python -m skills.social_media.enrich instagram johndoe

# Phone analysis
python -m skills.phone.lookup +33612345678

# Surname demographics
python -m skills.identity.etymology Dupont --birth-year 1990

# Academic records
python -m skills.identity.diplomas Jean Dupont --birth-year 1990

# SMTP validation
python -m skills.email.smtp_validate jean.dupont@example.com
python -m skills.email.smtp_validate --batch jean@a.com,paul@b.com

# GHunt
python -m skills.email.ghunt jean.dupont@gmail.com

# HIBP breach check
python -m skills.email.hibp jean.dupont@gmail.com
```

---

## Return format

All `run_sync()` / `run()` functions return a `dict`. Errors are returned as `{"error": "..."}` — exceptions are never raised to the caller. CLI output is JSON to stdout.
