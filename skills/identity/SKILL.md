# Identity Skills

## Skills

| File | What it does |
|------|-------------|
| `etymology.py` | French surname rarity + geographic origin (filae.com) |
| `diplomas.py` | Academic records: theses.fr, HAL publications, bac/brevet results (linternaute.com) |

> **Business registries (SIRENE, Pappers)** are handled inline in `paw_agent/engine/agent.py` via `_search_sirene_pappers_direct()`. No standalone skill yet.

---

## etymology

Scrapes [filae.com](https://filae.com) to retrieve French surname demographics.

**Requirements:** `pip install beautifulsoup4`

```bash
python -m skills.identity.etymology Dupont
python -m skills.identity.etymology Dupont --birth-year 1990
```

Returns:
```json
{
  "lastname":           "dupont",
  "bearers_since_1890": 12500,
  "departments_count":  87,
  "national_rank":      "42",
  "birth_periods":      [{"from": 1890, "to": 1915, "count": 340}, ...],
  "birth_year_context": "450 bearers born in period 1966–1990 (out of 12500 since 1890)",
  "geographic_distribution": [{"department": "Nord", "count": "820"}, ...]
}
```

**Interpreting rarity:**

| Bearers in period | Confidence in a match |
|---|---|
| < 5 | Near-certain — extremely rare |
| 5–30 | High — few candidates |
| 30–200 | Good — cross-reference city |
| 200–2000 | Medium — need extra corroboration |
| > 2000 | Low — very common surname |

**Interfaces:** `run_sync(lastname, birth_year="")`, `async run(lastname, birth_year)`

---

## diplomas

Searches for academic records associated with a full name. Strict matching: **both firstname AND lastname required**, whole-word, accent-insensitive.

```bash
python -m skills.identity.diplomas Jean Dupont
python -m skills.identity.diplomas Jean Dupont --birth-year 1990 --cities Paris
```

Sources:
- **theses.fr** — PhD dissertations (author, institution, year, discipline)
- **HAL.science** — open-access publications (author affiliations)
- **linternaute.com bac** — bac exam results (year, diploma type, age at exam)
- **linternaute.com brevet** — brevet results

**Strict matching rule:** "Michel Eloise" does NOT match "Tristan Michel" — the lastname must appear as the actual family name, not as a first name.

**Interfaces:** `run_sync(firstname, lastname, cities=[], birth_year="")`, `async run(...)`
