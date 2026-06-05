# Email OSINT Skills

## Skills

| File | What it does |
|------|-------------|
| `smtp_validate.py` | SMTP validation — custom/corporate domains; marks consumer providers as unverifiable |
| `ghunt.py` | GHunt Google account probe — confirms Gmail existence, retrieves name, Gaia ID, photo, Maps reviews |
| `hibp.py` | HaveIBeenPwned v3 — breach history for an email address (requires API key) |

> **Email permutation** is handled by `paw_agent/engine/permuter.py` (not a skill — pure logic, no network calls).  
> **Instagram lookup by username** is in `skills/social_media/ig_lookup.py` (username-based, not email-based).

---

## smtp_validate

Validates email addresses using SMTP probing via [isitarealemail.com](https://isitarealemail.com).  
Consumer domains (Gmail, Outlook, Yahoo, ProtonMail, etc.) are immediately marked **unverifiable** — no network call wasted. Use HIBP for those instead.

```bash
python -m skills.email.smtp_validate jean.dupont@example.com
python -m skills.email.smtp_validate --batch jean@a.com,paul@b.com
```

Returns:
```json
{
  "email":       "jean@example.com",
  "valid":       true,
  "domain_type": "custom"
}
```
`valid: null` = unverifiable domain (big provider).

**Interfaces:** `run_sync(email)`, `validate_batch(emails, max_results=20)`, `validate_all(candidates)`, `async run(email)`

---

## ghunt

Runs the `ghunt` CLI on a Gmail/Googlemail address to confirm account existence and gather metadata.

**Requirements:** `pip install ghunt` + `ghunt login` (one-time browser OAuth)

```bash
python -m skills.email.ghunt jean.dupont@gmail.com
```

Returns:
```json
{
  "email":        "jean@gmail.com",
  "found":        true,
  "gaia_id":      "1234567890",
  "name":         "Jean Dupont",
  "last_edit":    "2024-01-15",
  "photo_url":    "https://...",
  "maps_reviews": 5,
  "maps_photos":  2,
  "cal_events":   0
}
```

**Pivoting from GHunt:**
- `gaia_id` → Maps profile: `g.co/maps/person/{gaia_id}` (may show reviewed locations)
- `photo_url` → reverse image search (Yandex, PimEyes, Google Lens)
- `name` → cross-reference with social media profiles

**Interfaces:** `run_sync(email)`, `async run(email)`

---

## hibp

Checks an email address against the [HaveIBeenPwned v3](https://haveibeenpwned.com/API/Key) API.  
Requires `HIBP_API_KEY` in `.env`.

```bash
python -m skills.email.hibp jean.dupont@gmail.com
```

Returns:
```json
{
  "email":    "jean@gmail.com",
  "breached": true,
  "count":    3,
  "breaches": [
    {"name": "LinkedIn", "date": "2012-05-05", "data": ["Emails", "Passwords"]},
    {"name": "Facebook", "date": "2021-04-03", "data": ["Emails", "Phone numbers"]}
  ]
}
```

`breached: false` = email never appeared in any breach.  
Key breaches for French targets: LinkedIn 2016, Facebook 2021, Deezer 2022, Ledger 2020.

**Interfaces:** `run_sync(email)`, `async run(email)`

---

## Validation strategy by domain

| Domain type | Method | Tool |
|---|---|---|
| Custom / corporate | SMTP probe (isitarealemail.com) | `smtp_validate` |
| Gmail / Googlemail | GHunt CLI | `ghunt` |
| Outlook / Hotmail / Yahoo / ProtonMail / Orange / SFR / iCloud | Unverifiable — skip SMTP, go to HIBP | `hibp` |
