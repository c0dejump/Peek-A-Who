# PAW Skills

Each skill is a self-contained OSINT module. Each can be:
1. **Run standalone** from the CLI (returns JSON on stdout)
2. **Imported** and called from `paw_agent/engine/pipeline.py` or any other Python code

All skill functions expose a consistent interface:
- `run_sync(...)` — synchronous, usable anywhere
- `async run(...)` — async wrapper for pipeline use
- CLI via `python -m skills.<category>.<skill> [args]`

---

## Inventory

```
skills/
  social_media/
    instagram.py     ← Instagram username detection (og:title via facebookexternalhit UA)
    platforms.py     ← Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal (parallel)
    maigret.py       ← 500+ sites via maigret CLI subprocess
    ig_lookup.py     ← Instagram account lookup by USERNAME → obfuscated email + phone

  email/
    smtp_validate.py ← SMTP validation (custom/corporate domains); consumer domains = unverifiable
    ghunt.py         ← GHunt CLI — Gmail existence + metadata (name, Gaia ID, Maps reviews)
    hibp.py          ← HaveIBeenPwned v3 breach history (requires HIBP_API_KEY)

  phone/
    lookup.py        ← phonenumbers + ignorant + PhoneInfoga links

  identity/
    etymology.py     ← French surname rarity + geographic distribution (filae.com)
    diplomas.py      ← theses.fr + HAL + bac/brevet (linternaute.com)
```

> **Email permutation** — handled by `paw_agent/engine/permuter.py` (pure logic, no network).  
> **Business registries** — `_search_sirene_pappers_direct()` in agent.py (not a standalone skill yet).

---

## Quick examples

```bash
# Instagram scan
python -m skills.social_media.instagram --firstname Jean --lastname Dupont --keywords jd

# Multi-platform scan
python -m skills.social_media.platforms --firstname Jean --lastname Dupont

# Maigret cross-platform
python -m skills.social_media.maigret jean.dupont jdupont

# Instagram lookup by username
python -m skills.social_media.ig_lookup johndoe --phone +33612345678

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
