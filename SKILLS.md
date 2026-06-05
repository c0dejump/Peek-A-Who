# PAW — OSINT Agent: Investigation Guide

This document describes the investigation workflow, data sources, and interpretation guidance for the PAW OSINT tool.

---

## Architecture overview

PAW uses a **Clean Hybrid Architecture**:

| Component | Role |
|---|---|
| `pipeline.py` | Main orchestrator — deterministic, no MCP subprocess, imports skills directly |
| `agent.py` | Phase 1 helper functions (transitional — will migrate to skills over time) |
| `mcp_server.py` | Thin MCP wrapper over skills — kept for external tool-calling integrations only |
| `skills/` | Standalone OSINT modules — each has `run_sync()`, `async run()`, CLI interface |
| litellm | Called directly by pipeline.py for synthesis (2 times per investigation) |

The LLM is **not** an orchestrator. It synthesises data at two fixed points:
1. **Confirmation checkpoint** — IDENTITY / TIMELINE / LOCATIONS from Phase 1 findings
2. **Final report** — structured summary after Phase 2

---

## 1. Investigation Workflow

### Two-phase pipeline

**Phase 1 — Passive intel (no account queries)**

| Step | What | Source |
|---|---|---|
| 0 | Surname demographics | filae.com (`etymology` skill) |
| 0.5 | Academic records | theses.fr, HAL, linternaute bac/brevet |
| 0.7 | Business registries | SIRENE (data.gouv.fr), Pappers |
| 0.8 | Annuaires links | Pages Blanches, Pages Jaunes (search URLs only — Cloudflare protected) |
| 0.9 | Phone OSINT | phonenumbers, ignorant, PhoneInfoga |
| 0.95 | Instagram username search | `instagram` skill |
| 0.96 | Multi-platform | `platforms` skill (Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal) |
| 0.97 | Cross-platform maigret | `maigret` skill (500+ sites) |
| 0.98 | Activity signal enrichment | Reddit, GitHub (inline in pipeline.py) |
| 0.99 | **LLM checkpoint synthesis** | litellm direct — IDENTITY / TIMELINE / LOCATIONS |

**Confirmation checkpoint** — the LLM synthesises Phase 1 into:
- `IDENTITY` — 2–3 sentences on who this person appears to be
- `TIMELINE` — chronological last known activities (format: `• date: platform — finding`)
- `LOCATIONS` — comma-separated cities/regions

The investigator reviews and either **continues** (→ Phase 2) or **stops** (report from Phase 1 only).

**Phase 2 — Active OSINT (account-level queries, after confirmation)**

| Step | What | Tool |
|---|---|---|
| 1 | Email permutation | `paw_agent/engine/permuter.py` |
| 2 | SMTP validation | `smtp_validate` skill |
| 2b | GHunt Google account probe | `ghunt` skill |
| 3 | HIBP breach history | `hibp` skill |
| 4 | **LLM final summary** | litellm direct |

---

## 2. Username Generation Priority

Keywords take **highest priority** after the pseudo — they often are the actual username component.

### Priority order
1. **Pseudo** (exact)
2. **Keywords** alone + keyword+name combos: `kw`, `fn.kw`, `kw.fn`, `ln.kw`, `fn.ln.kw`
3. **Name combos**: `fn.ln`, `ln.fn`, `fnln`, abbreviations
4. **Name + year**: `fn.ln90`, `fn.ln1990`
5. **Name + dept code**: `fn.ln75`

### Example: firstname=tristan, lastname=michel, keywords=["mchl", "manny"]
```
1:  mchl           ← keyword alone
2:  tristan.mchl   ← fn.kw  (probable real username)
3:  tristan_mchl
4:  tristanmchl
5:  mchl.tristan
...
16: manny
17: tristan.manny
...
(name-only combos come after all keyword variants)
```

---

## 3. Surname Rarity Interpretation

From `etymology` skill (filae.com):

| Bearers in birth period | Confidence in a match |
|---|---|
| < 5 | Near-certain — extremely rare name |
| 5–30 | High — few candidates in France |
| 30–200 | Good — cross-reference city |
| 200–2000 | Medium — need extra corroboration |
| > 2000 | Low — common surname |

Top departments → historical family origin → prioritise those cities in searches.

---

## 4. Email Strategy

### Permutation priority (Jean Dupont, born 1990, keyword "jd")
```
jean.dupont@    j.dupont@    jean.d@    dupont.jean@
jean.dupont90@  jean.dupont1990@
jd@  jean.jd@  jd.jean@
```

### Validation by domain type

| Domain type | Method | Skill |
|---|---|---|
| Custom / corporate | SMTP (isitarealemail.com) | `smtp_validate` |
| Gmail / Googlemail | GHunt CLI | `ghunt` |
| Outlook / Hotmail / Yahoo / ProtonMail / Orange / SFR / iCloud | Unverifiable — use HIBP | `hibp` |

### HIBP breach data
- `breached: true` = email was real and active at breach time
- Key breaches for French targets: LinkedIn 2016, Facebook 2021, Deezer 2022, Ledger 2020
- `DataClasses` with `Passwords` + `Phone numbers` = high-value for pivoting

---

## 5. GHunt — Google Account OSINT

Requires: `pip install ghunt` + `ghunt login` (one-time browser OAuth).

Pivoting from GHunt results:
- `gaia_id` → Maps profile: `g.co/maps/person/{gaia_id}` (reviewed locations)
- `photo_url` → reverse image search (Yandex, PimEyes, Google Lens)
- `name` → cross-reference with Phase 1 social profiles

---

## 6. Social Media Platform Detection

### Instagram
- URL: `instagram.com/{username}`
- Detect: `(@{username})` in `og:title` (using `facebookexternalhit/1.1` UA — Meta whitelists this)
- First-seen date: Wayback Machine CDX API

### Twitter/X
- URL: `x.com/{username}` — title: `"Name (@username) / X"`

### TikTok
- URL: `tiktok.com/@{username}` — title: `"Name (@username) | TikTok"`

### Snapchat
- URL: `snapchat.com/add/{username}` — title: `"@username | Snapchat"`

### Telegram
- URL: `t.me/{username}` — title: `"Telegram: Contact @username"`

### BeReal
- URL: `bere.al/@{username}` — HTTP 404 = not found; 200 + username in title = found

### LinkedIn
- URL: `linkedin.com/in/{username}/` — name before ` - ` in title (not sign-in page)

### Facebook
- Direct check unreliable without auth → manual search URL generated automatically

### Instagram username lookup (`ig_lookup` skill)
After finding an Instagram username, the `ig_lookup` skill can retrieve the obfuscated email and phone associated with the account:
- Endpoint: `POST i.instagram.com/api/v1/users/lookup/` with `q=<username>`
- Returns `obfuscated_email` + `obfuscated_phone`
- No authentication required; rate-limited at 429

### Maigret categories (missing persons prioritisation)
| Category | Key platforms | Why it matters |
|---|---|---|
| Location/Sport | Strava, Komoot, Garmin, AllTrails, Wikiloc, Foursquare | GPS routes, last location |
| Marketplace | Leboncoin, Vinted, Airbnb, BlaBlaCar | City in listing, last active date |
| Gaming | Steam, Xbox, PSN, Twitch | Last online timestamp |
| Social | Reddit, Mastodon, Pinterest | Last post date, location clues |

---

## 7. Activity Signals for Missing Persons

### Reddit (public API)
- Endpoint: `reddit.com/user/{username}/overview.json?limit=10&sort=new`
- `created_utc` → last post/comment date
- Subreddits → geographic clues (r/paris → Paris, r/lyon → Lyon area)

### GitHub (public API)
- Endpoint: `api.github.com/users/{username}`
- `location` field (self-declared), `updated_at` (last activity)
- Commit emails may reveal real address if repos are public

---

## 8. Academic Records Matching

**Strict rule:** both firstname AND lastname required, whole-word, accent-insensitive.
- "Michel Eloise" does NOT match "Tristan Michel" (michel is the lastname, not firstname)
- "Tristane Dupont" does NOT match "Tristan Dupont" (whole-word boundary)
- "Éloïse Michel" DOES match "Eloise Michel" (accent normalisation)

Sources: theses.fr · HAL.science · linternaute bac · linternaute brevet

---

## 9. Phone Number Investigation

1. Parse + validate (phonenumbers library) → carrier, region, line type
2. **ignorant**: WhatsApp / Telegram / Snapchat / Instagram registration
3. **PhoneInfoga**: reverse lookup links
4. Google dork: `"+33 6 XX XX XX XX"` in quotes

---

## 10. French-Specific Sources

| Source | What |
|---|---|
| pagesblanches.fr | Residential directory (search URL generated, Cloudflare-protected) |
| pagesjaunes.fr | Landline + business |
| pappers.fr | SIRET/SIREN, directors, filed accounts (free API) |
| societe.com | Historical company data |
| data.gouv.fr | BODACC, RCS extracts |
| theses.fr | PhD dissertations |
| hal.science | Open-access publications |
| legifrance.gouv.fr | Registered professionals (doctors, lawyers, notaries) |
| filae.com | Civil records + surname demographics |
| geneanet.org | Genealogical trees |
| linternaute.com | Bac/brevet results, surname frequency by département |

---

## 11. Image & Reverse Search

- **Google Lens** — objects, scenes, landmarks
- **Yandex Images** — strong facial recognition for European faces
- **TinEye** — exact duplicate detection, image spread over time
- **PimEyes** — paid facial recognition across the open web

Feed from: GHunt `photo_url`, Instagram profile photo, LinkedIn photo.

---

## 12. OSINT Methodology

### Confidence levels
- **Confirmed** — tool-validated: SMTP valid, HIBP hit, GHunt found, title-detected profile
- **Probable** — strong circumstantial: same username on 3+ platforms, name + correct region
- **Possible** — weak match, needs corroboration

### Pivoting chain (missing persons)
```
Username found (Phase 1)
  → maigret: Strava/Komoot → GPS route area → last known location
  → maigret: Leboncoin/Vinted → city in listing → last posting date
  → Reddit: last comment + subreddit → geographic area + date
  → GitHub: location field + last commit date
  → Instagram first_seen (Wayback) + display name
  → ig_lookup: username → obfuscated email + phone
  → Email found (Phase 2) → HIBP → leaked phone/address
  → GHunt: photo_url → reverse image → other profiles
  → Phone → ignorant: Telegram/WhatsApp last seen
```

### Legal & ethical framework
- Only publicly accessible information
- No authentication, credential stuffing, or social engineering
- GDPR applies to personal data about EU residents
- Intended for authorised investigations: law enforcement, families, licensed investigators
