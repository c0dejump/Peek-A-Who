# Social Media Skills

Username-based platform detection using public HTML / title-based scraping.  
No authentication required. No credentials stored.

## Skills

| File | Platform(s) | Method |
|------|------------|--------|
| `instagram.py` | Instagram | `og:title` via `facebookexternalhit/1.1` UA — Meta/Instagram whitelists this to return profile data to link-preview crawlers |
| `platforms.py` | Twitter/X, TikTok, Snapchat, Telegram, LinkedIn, BeReal | Parallel title-pattern matching (kept for standalone CLI use; pipeline uses pre-validation instead) |
| `maigret.py` | 36 targeted sites | CLI subprocess wrapping `maigret` with `--site` flags for `_MISSING_PERSONS_SITES` |
| `sherlock.py` | 36 targeted sites | CLI subprocess wrapping `sherlock` with `--site` flags for `_MISSING_PERSONS_SITES` |
| `ig_lookup.py` | Instagram (account lookup) | POST to `i.instagram.com/api/v1/users/lookup/` with `q=<username>` → obfuscated email + phone |

---

## instagram

Username detection for Instagram. Generates candidates from name/keywords/pseudo, checks each one.

```bash
python -m skills.social_media.instagram --firstname Jean --lastname Dupont
python -m skills.social_media.instagram --firstname Jean --lastname Dupont --keywords jd --pseudo jdupont
```

Detection: `(@{username})` present in `og:title` = profile exists.  
First-seen date: Wayback Machine CDX API.

**Interfaces:** `run_sync(firstname, lastname, keywords=[], birth_year="", pseudo="", dept_codes=[])`, `async run(...)`

---

## platforms

Parallel detection across 6 platforms for a list of username candidates.

```bash
python -m skills.social_media.platforms --firstname Jean --lastname Dupont
```

### Detection logic

| Platform | URL | Signal |
|---|---|---|
| Twitter/X | `x.com/{username}` | `(@{username})` in title |
| TikTok | `tiktok.com/@{username}` | `(@{username})` or `{username} | TikTok` |
| Snapchat | `snapchat.com/add/{username}` | `@{username}` in title |
| Telegram | `t.me/{username}` | `@{username}` in title |
| LinkedIn | `linkedin.com/in/{username}/` | Name before separator, not sign-in page |
| BeReal | `bere.al/@{username}` | HTTP 200 + username in title |

Facebook: generates manual search URL only (auth required for real detection).

**Interfaces:** `run_sync(usernames, firstname, lastname, keywords=[])`, `async run(...)`

---

## maigret

Runs the `maigret` CLI on a list of username candidates and categorises results.

**Requirements:** `pip install maigret`

```bash
python -m skills.social_media.maigret jean.dupont jdupont j.dupont
```

Scans **36 targeted sites** (`_MISSING_PERSONS_SITES` in `agent.py`) via `--site` flags. Run in parallel with sherlock inside `_prevalidate_usernames` (Step 0.93); results are merged per username.

- **Location/Sport** — Strava, Komoot, AllTrails, Wikiloc, Geocaching, Garmin, Foursquare
- **Marketplace** — LeBonCoin, Vinted, BlaBlaCar, Airbnb, Etsy, eBay
- **Gaming** — Steam, Twitch, Xbox, PlayStation
- **Social** — Reddit, Twitter, Instagram, TikTok, Snapchat, Telegram, Discord, Pinterest, Tumblr, Flickr, Mastodon
- **Professional** — GitHub, LinkedIn, Spotify, SoundCloud

**Interfaces:** `run_sync(usernames)`, `async run(usernames)`

---

## sherlock

Runs the `sherlock` CLI on a list of username candidates and categorises results.

**Requirements:** `pip install sherlock-project`

```bash
python -m skills.social_media.sherlock jean.dupont jdupont
```

Same 36 targeted sites as maigret. Launched **in parallel** with maigret inside `_prevalidate_usernames` (Step 0.93). Results merged per-username; any username with ≥1 hit is validated.

**Interfaces:** `run_sync(usernames)`, `async run(usernames)`

---

## ig_lookup

Instagram account lookup by **username** (not email). Queries Instagram's private user lookup endpoint to retrieve the obfuscated email and phone number associated with an account.

No authentication required. May be rate-limited (HTTP 429) after repeated calls.

```bash
python -m skills.social_media.ig_lookup johndoe
python -m skills.social_media.ig_lookup johndoe --phone +33612345678
```

Returns:
```json
{
  "status":           "found",
  "username":         "johndoe",
  "obfuscated_email": "j***@g***.com",
  "obfuscated_phone": "+33 ** ** ** 78",
  "phone_match":      true
}
```

Technique: `POST i.instagram.com/api/v1/users/lookup/` with `signed_body=...q={username}...`

**Interfaces:** `run_sync(username, phone="")`, `async run(username, phone)`

---

## Relevance scoring (0–10)

Applied in `instagram.py` and `platforms.py` to rank matched profiles:

| Signal | Points |
|--------|--------|
| Last name in display name | +5 |
| First name in display name | +4 |
| Keyword in username | +3 |
| Keyword in display name / bio | +3 |
| Max | 10 |

Score ≥ 7 → high confidence · Score ≥ 4 → medium · Score < 4 → low
