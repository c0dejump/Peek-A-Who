# Phone OSINT Skills

## Skills

| File | What it does |
|------|-------------|
| `lookup.py` | Full phone analysis: validation, carrier, region, social platform registration, reverse lookup links |

## Data sources

1. **phonenumbers** (libphonenumber): parse, validate, format (E.164), carrier, region, line type (mobile/fixed/VoIP)
2. **ignorant**: check if phone is registered on WhatsApp, Telegram, Snapchat, Instagram (no auth)
3. **PhoneInfoga**: generates curated reverse lookup links (NumLookup, Truecaller, Google, etc.)

## Usage

```bash
python -m skills.phone.lookup +33612345678
```

Returns:
```json
{
  "e164": "+33612345678",
  "valid": true,
  "type": "MOBILE",
  "carrier": "Orange",
  "region": "FR",
  "country_code": "33",
  "reverse_links": {"NumLookup": "...", "Truecaller": "..."},
  "ignorant_platforms": [{"site": "WhatsApp", "status": "found"}, ...]
}
```
