# Peek-A-Who — OSINT Investigation Guide

## Architecture overview

PAW uses a **Clean Hybrid Architecture**:

| Component | Role |
|---|---|
| `pipeline.py` | Main orchestrator — deterministic, imports skills directly, litellm for synthesis |
| `agent.py` | Phase 1 legacy helpers (transitional — migrating to skills/) |
| `mcp_server.py` | Thin MCP wrapper over skills — for external tool-calling integrations only |
| `skills/` | Standalone OSINT modules — `run_sync()`, `async run()`, CLI interface |
| `skills/core/` | Watson AI layer: evidence, agents, OSINT knowledge, tools |
| litellm | Called directly by pipeline.py (2× per investigation) and Watson chat |

---

## 1. Investigation Workflow

### Phase 1 — Passive intel (no account queries)

| Step | What | Source |
|---|---|---|
| 0 | Surname demographics | filae.com (`etymology` skill) |
| 0.5 | Academic records | theses.fr, HAL, linternaute bac/brevet |
| 0.7 | Business registries | SIRENE (data.gouv.fr), Pappers |
| 0.8 | Annuaires links | Pages Blanches, Pages Jaunes (URL only — Cloudflare-protected) |
| 0.9 | Phone OSINT | phonenumbers, ignorant, PhoneInfoga |
| 0.93 | **Username pre-validation** | ALL candidates → maigret + sherlock on 36 targeted sites, 20 parallel workers; ≥1 hit = validated; Reddit/GitHub enrichment inline |
| 0.95 | Instagram | Validated candidates only |
| 0.95b | ig_lookup | Obfuscated email + phone per Instagram profile found |
| 0.95c | TikTok deep check | Embedded JSON (uniqueId field) |
| 0.95d | LinkedIn candidates | Slug candidates only (automated blocked) |
| 0.96 | Multi-platform | Twitter/X, Snapchat, BeReal, Telegram, Facebook |
| 0.99 | **LLM checkpoint** | IDENTITY / TIMELINE / LOCATIONS → user confirms or stops |

**Confirmation checkpoint** — synthesises Phase 1 into three sections the investigator reviews before Phase 2 runs.

### Phase 2 — Active OSINT (after confirmation)

| Step | What | Tool |
|---|---|---|
| 1 | Email permutation | `paw_agent/engine/permuter.py` |
| 2 | SMTP validation + SERP | `smtp_validate` skill |
| 2b | Google account probe | `ghunt` skill |
| 3 | Breach history | `hibp` skill |
| 4 | **Multi-agent synthesis** | 5 rule-based agents → single LLM call → full Phase 3 JSON |

### Phase 3 — Intelligence Report

Five deterministic specialist agents run first (< 100ms each, no LLM):
- **Identity** — confirmed name, birth year, cross-validation
- **Social** — active platforms, username pattern, behavioral signals
- **Geo** — confirmed/probable locations, evolution, cross-confirmation
- **Timeline** — chronological events, last known activity, span
- **Correlation** — links between findings, anomalies, coherence score

All 5 briefings → single LLM call → structured JSON with:
- `executive_summary`, `global_confidence`
- `identity` (confirmed / probable / rejected)
- `digital_presence` (platforms, username_pattern)
- `geolocation` (confirmed, current_estimate)
- `hypotheses[]` (claim, confidence 0–1, evidence_for, evidence_against)
- `pivot_suggestions[]` (action, priority: high/medium/low)
- `risk_indicators[]`, `timeline[]`, `human_verifications[]`, `missing_data[]`

Falls back to rule-based analysis if LLM is unavailable.

---

## 2. Watson — AI Investigation Partner

Watson is a permanent right sidebar in the investigation UI. It is **not** a popup.

### How it works

**Minimal command parser** (no LLM, instant, offline-safe):
```
"add @username to case"   → directly records to case graph
"investigate @username"   → enriches profile
```
Everything else → Watson LLM + tools (natural language, any phrasing, any language).

**Tool-use loop** — Watson calls OSINT skills directly (10 tools):
| Tool | What |
|---|---|
| `record_to_case(platform, username)` | **Save found profile to case** — writes directly to case store, no round-trip. Called automatically for "found tiktok @nnoa_opz", "le snapchat c'est johndoe add to case", etc. |
| `web_search(query)` | DuckDuckGo with operators (site:, inurl:, "exact phrase") |
| `instagram_lookup(username)` | Obfuscated email/phone hint |
| `sherlock_check(username)` | Cross-platform presence |
| `enrich_profile(platform, username)` | Bio, followers, links |
| `email_osint(email)` | SMTP + HIBP + GHunt + SERP |
| `phone_lookup(phone)` | Carrier, region, social platforms |
| `web_archive(url)` | Wayback Machine first/last snapshot |
| `whois_lookup(domain)` | Registrar, dates, org |
| `validate_email_batch(emails)` | SMTP-validate a list |

**Streaming LLM** — tokens appear immediately via SSE. Uses `WATSON_LLM_BACKEND` (lighter, faster model).

**OSINT knowledge base** (`osint_knowledge.py`) — Watson's system prompt includes:
- Full OSINT investigation cycle (collection → validation → correlation → analysis → pivoting)
- Search operator cheatsheet (site:, inurl:, filetype:, before:, after:)
- French-specific sources (pappers.fr, societe.com, theses.fr, pages-blanches.fr, filae.com…)
- Platform-specific techniques (Instagram Wayback, LinkedIn dorks, GitHub commit email, Reddit Pushshift)
- Identity correlation methods (email format inference, username pattern, photo correlation)
- Pivot chain strategies for missing persons

### Watson configuration

```env
# Separate models for quality vs speed
LLM_BACKEND=ollama/qwen2.5-coder:32b     # pipeline synthesis
WATSON_LLM_BACKEND=ollama/qwen2.5:7b     # Watson chat (fast)
```

Recommended Watson models:
- `ollama/qwen2.5:7b` — 4.7GB, ~3s first token on CPU, excellent reasoning
- `ollama/llama3.2:3b` — 2GB, ~1s first token, lighter
- `ollama/mistral:7b` — 4.1GB, strong French support
- `groq/llama-3.3-70b-versatile` — API, free tier, very fast

---

## 3. Username Generation Priority

Keywords take **highest priority** after the pseudo:

1. **Pseudo** (exact)
2. **Keywords** + combos: `kw`, `fn.kw`, `kw.fn`, `ln.kw`, `fn.ln.kw`
3. **Name combos**: `fn.ln`, `ln.fn`, `fnln`, abbreviations
4. **Name + year**: `fn.ln90`, `fn.ln1990`
5. **Name + dept code**: `fn.ln75`

All candidates → pre-validation (Step 0.93) → only ≥1 hit on 36 sites proceeds.

---

## 4. Surname Rarity Interpretation

From `etymology` skill (filae.com):

| Bearers in birth period | Match confidence |
|---|---|
| < 5 | Near-certain — extremely rare |
| 5–30 | High — few candidates in France |
| 30–200 | Good — cross-reference city |
| 200–2000 | Medium — need extra corroboration |
| > 2000 | Low — common surname |

---

## 5. Email Strategy

### Permutation priority
```
jean.dupont@    j.dupont@    jean.d@    dupont.jean@
jean.dupont90@  jean.dupont1990@
jd@  jean.jd@  jd.jean@
```

### Validation by domain type

| Domain type | Method |
|---|---|
| Custom / corporate | SMTP (isitarealemail.com) |
| Gmail / Googlemail | GHunt CLI |
| Outlook / Hotmail / Yahoo / ProtonMail / Orange / SFR | HIBP only (SMTP unverifiable) |

### HIBP breach data
- `breached: true` = email was real at breach time
- `DataClasses` with `Passwords` + `Phone numbers` = high-value pivot
- Key breaches for French targets: LinkedIn 2016, Facebook 2021, Deezer 2022, Ledger 2020

---

## 6. Social Media Platform Detection

| Platform | Method |
|---|---|
| Instagram | `facebookexternalhit/1.1` UA → `og:title` contains `(@username)` |
| Twitter/X | `og:title` = "Name (@username) / X" |
| TikTok | Embedded JSON `uniqueId` field |
| Snapchat | `og:title` = "@username \| Snapchat" |
| Telegram | `og:title` = "Telegram: Contact @username" |
| BeReal | HTTP 200 + username in title = found; 404 = not found |
| LinkedIn | Title before ` - ` (not sign-in page) |
| Facebook | Search URL only (auth required) |

### Instagram username lookup (`ig_lookup`)
After finding an Instagram username → `POST i.instagram.com/api/v1/users/lookup/`:
- Returns `obfuscated_email` (e.g. `h***@hotmail.fr`) + `obfuscated_phone`
- No authentication required; rate-limited at 429

---

## 7. Activity Signals for Missing Persons

### Reddit (public API)
- Last post/comment date (`created_utc`)
- Subreddit activity → geographic clues (r/paris, r/lyon, r/marseille)

### GitHub (public API)
- `location` field (self-declared)
- `updated_at` → last activity date
- Commit email may reveal personal address

### Maigret categories (missing persons focus)
| Category | Platforms | Signal |
|---|---|---|
| Location/Sport | Strava, Komoot, Garmin, AllTrails | GPS routes, last activity |
| Marketplace | Leboncoin, Vinted, BlaBlaCar | City in listing, last post date |
| Gaming | Steam, Xbox, PSN, Twitch | Last online timestamp |
| Social | Reddit, Mastodon, Pinterest | Last post date, location clues |

---

## 8. Evidence Confidence Levels

| Level | Criteria |
|---|---|
| **confirmed** | Multiple independent sources agree, or primary source directly states it |
| **probable** | One strong source or multiple weak signals pointing the same direction |
| **low** | Single weak signal, indirect inference, unverifiable claim |
| **rejected** | Contradicted by evidence or logic |

Never present a hypothesis as a fact. Always cite the source.

---

## 9. Pivoting Chain (missing persons)

```
Username found (Phase 1)
  → maigret: Strava/Komoot → GPS area → last known location
  → maigret: Leboncoin/Vinted → city in listing → last post date
  → Reddit: last comment date + subreddit → geographic area
  → GitHub: location field + last commit date
  → Instagram first-seen (Wayback CDX) + ig_lookup → obfuscated email/phone
  → Email found (Phase 2)
    → SMTP validation → confirmed mailbox
    → HIBP → breach data (leaked phone, address, linked accounts)
    → GHunt (Gmail) → Gaia ID → Maps profile → reviewed locations
    → photo_url → reverse image search → other profiles
  → Phone → ignorant → Telegram/WhatsApp last seen
  → Watson: web_search "site:strava.com firstname lastname" → Strava profile
  → Watson: whois_lookup domain → registrant identity
  → Watson: web_archive instagram.com/username → account creation date
```

---

## 10. French-Specific Sources

| Source | What |
|---|---|
| pagesblanches.fr | Residential directory (search URL, Cloudflare-protected) |
| pagesjaunes.fr | Landline + business |
| pappers.fr | SIRET/SIREN, directors, filed accounts |
| societe.com / societe.ninja | Historical company data |
| bodacc.fr | Official commercial announcements |
| data.gouv.fr | RCS, SIRENE, BODACC extracts |
| theses.fr | PhD dissertations |
| hal.science | Open-access publications |
| legifrance.gouv.fr | Registered professionals (doctors, lawyers, notaries) |
| filae.com | Civil records + surname demographics |
| geneanet.org | Genealogical trees |
| linternaute.com | Bac/brevet results, surname frequency by département |
| copains-davant.fr | School class pages |

---

## 11. Academic Records Matching

**Strict rule:** both firstname AND lastname required, whole-word, accent-insensitive.
- "Michel Eloise" ≠ "Tristan Michel" (michel is lastname here)
- "Tristane Dupont" ≠ "Tristan Dupont" (whole-word boundary)
- "Éloïse Michel" = "Eloise Michel" (accent normalisation ✓)

---

## 12. Facial Recognition (built-in)

When a reference photo is uploaded at the start of an investigation, PAW encodes the face
and automatically compares it against profile pictures found during validation.

**How it works:**
- Reference face encoded at upload time (`skills/face/face_match.py` — 128-dim dlib vector)
- Comparison runs automatically when "Validate" is clicked and the profile has a `profile_pic` URL
- Distance < 0.50 = match; < 0.45 = probable; < 0.35 = strong match

**Confidence boost on match:**
| Distance | Boost applied to link confidence |
|---|---|
| < 0.35 (strong) | +40 points |
| < 0.45 (probable) | +30 points |
| < 0.50 (possible) | +20 points |

**Graph indicators:**
- Matched node: green border + glow shadow + 🧬 label suffix
- Link edge: green color + thicker width + "face match" tooltip
- Node popup: "Strong / Probable / Possible Face Match" badge with distance and %

**Install:** `pip install cmake dlib face_recognition` (optional — degrades gracefully if absent)

---

## 13. Reverse Image Search (external)

- **Yandex Images** — strongest facial recognition for European faces
- **Google Lens** — objects, scenes, landmarks, public figures
- **TinEye** — exact duplicates, spread over time
- **PimEyes** — paid facial recognition across the open web

Feed from: GHunt `photo_url`, Instagram profile photo, LinkedIn photo, Wayback snapshots.

---

## 14. Legal & Ethical Framework

- Only publicly accessible information — no authentication or credential stuffing
- GDPR applies to personal data about EU residents
- Intended for authorised investigations: families, law enforcement, licensed investigators, journalists
- Investigators are responsible for compliance with local laws and platform terms of service
