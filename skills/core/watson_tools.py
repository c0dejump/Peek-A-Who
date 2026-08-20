"""
Watson tool definitions and execution layer.

Each tool is defined in OpenAI function-calling schema (litellm-compatible)
and has a corresponding _exec_* function that runs the actual skill.

The tool loop in app.py calls execute_tool() to dispatch from LLM tool_calls.
"""
from __future__ import annotations

import re
import socket
from typing import Any

# ── Tool schema definitions (OpenAI function-calling format) ──────────────────

WATSON_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web using DuckDuckGo. Use for: finding social profiles by name, "
                "SERP presence of emails/usernames, news mentions, business registry lookups, "
                "dorking (site:, inurl:, filetype:, etc.). Returns page title, snippet, and URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Include operators like site:, inurl:, \"exact phrase\" etc."
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 8, max 15)",
                        "default": 8
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "instagram_lookup",
            "description": (
                "Look up an Instagram account by username. Returns obfuscated email/phone hints "
                "(e.g. h***@hotmail.fr), account metadata, and whether the account was found. "
                "Uses the official Instagram API password-reset endpoint."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Instagram username (without @)"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sherlock_check",
            "description": (
                "Check if a username exists across social media platforms using Sherlock. "
                "Returns a list of found platform URLs and a total count. "
                "Best for: confirming cross-platform presence of a known username."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "The username to check across platforms"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout per platform in seconds (default 10)",
                        "default": 10
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_profile",
            "description": (
                "Enrich a specific social media profile URL to extract bio, follower count, "
                "following count, post count, private status, bio links, and other metadata. "
                "Supports Instagram, TikTok, GitHub, Reddit, and other public profiles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "Platform name (instagram, tiktok, github, reddit, twitter, linkedin, etc.)",
                        "enum": ["instagram", "tiktok", "github", "reddit", "twitter", "linkedin", "generic"]
                    },
                    "username": {
                        "type": "string",
                        "description": "Username or handle on the platform (without @)"
                    },
                    "url": {
                        "type": "string",
                        "description": "Full profile URL (optional — inferred from platform+username if absent)"
                    }
                },
                "required": ["platform", "username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "email_osint",
            "description": (
                "Perform OSINT on an email address: SMTP validation (does the mailbox exist?), "
                "HIBP breach check (was the email in data breaches?), GHunt analysis (if Gmail — "
                "linked accounts, last seen), and SERP presence (is the email indexed publicly?). "
                "Use this for any email address you want to investigate further."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The email address to investigate"
                    }
                },
                "required": ["email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "phone_lookup",
            "description": (
                "Look up information about a phone number: country, carrier, line type "
                "(mobile/landline/VoIP), and any linked social media accounts. "
                "Works best with international format (+33...)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Phone number in international format, e.g. +33612345678"
                    }
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_archive",
            "description": (
                "Query the Wayback Machine for archived snapshots of a URL. "
                "Returns the first and last capture dates and total snapshot count. "
                "Use for: determining when an account or page first appeared, "
                "or retrieving deleted content via archive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to check (e.g. https://www.instagram.com/username/)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "whois_lookup",
            "description": (
                "Perform a WHOIS lookup on a domain name. Returns registrar, creation date, "
                "expiry date, registrant organisation/email (if not privacy-protected), "
                "and nameservers. Use when a domain name is found in a bio, email, or profile."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name to query, e.g. example.com"
                    }
                },
                "required": ["domain"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_email_batch",
            "description": (
                "SMTP-validate a list of email address candidates. Returns which addresses "
                "have a valid mailbox. Use when you have generated email permutations "
                "and need to verify which ones actually exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "emails": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of email addresses to validate (max 20)"
                    }
                },
                "required": ["emails"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "geo_imagery",
            "description": (
                "Visually verify a place and find photos taken there: returns a Google "
                "Street View link at the exact spot plus geotagged photos nearby (Flickr). "
                "Use for a sighting location or any address. Accepts a place name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "Place/address to look at (geocoded)"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "leak_search",
            "description": (
                "Search breach/leak databases (Dehashed, LeakCheck, IntelX) for an "
                "email, username, phone, name, IP or domain. Unlike a breach check, this "
                "returns the leaked CONTENT — linked emails, usernames, passwords/hashes, "
                "phones, addresses — the strongest pivots. Returns a clear note if no "
                "provider key is configured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Identifier to search (email/username/phone/name/IP/domain)"},
                    "query_type": {"type": "string",
                                   "enum": ["auto", "email", "username", "phone", "name", "ip", "domain"],
                                   "description": "Type of identifier (default auto-detect)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reverse_image",
            "description": (
                "Reverse-image-search a photo by URL (e.g. a profile picture) to find where "
                "else it appears online and confirm identity. Returns ready-to-open engine "
                "links (Yandex — best for faces, Google Lens, Bing, TinEye) and best-effort "
                "matched pages. Use when you have an image URL to trace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "Public URL of the image to reverse-search"
                    }
                },
                "required": ["image_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_to_case",
            "description": (
                "Record a found social media account or profile into the current investigation case. "
                "Call this whenever the user says they found an account on a platform and wants to "
                "save it, add it to the case, or track it. Works for any natural phrasing like "
                "'the tiktok is nnoa_opz add to case', 'found bereal @peanaths', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "Social media platform name (e.g. tiktok, instagram, bereal, snapchat, steam, github, reddit, strava, telegram, vinted, twitter, linkedin)",
                    },
                    "username": {
                        "type": "string",
                        "description": "Username or handle on the platform (without @ prefix)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional context note about this finding"
                    }
                },
                "required": ["platform", "username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_keyword",
            "description": (
                "Add one or more keywords to the current investigation case (stored as "
                "'keyword' facts). Call this whenever the user asks to add/register a keyword, "
                "alias, or term — e.g. 'ajoute \"sen\" et \"game\" en keyword', 'add keyword ubx'. "
                "Keywords feed username and email-pattern generation on the NEXT run. "
                "Do NOT just echo the data back — you must call this tool to actually persist it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "One keyword, or several separated by commas (e.g. \"sen, game\")"
                    }
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rerun_email",
            "description": (
                "Regenerate email candidates for the case using its current facts "
                "(name + all keywords, including ones just added). Call this when the user "
                "asks to re-run / regenerate / relaunch the email part, or wants email "
                "patterns with the new keywords. Returns the ranked candidate list."
            ),
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Max candidates to return (default 40)"}
            }}
        }
    },
]


# ── Tool execution functions ───────────────────────────────────────────────────

def _exec_web_search(query: str, num_results: int = 8) -> dict:
    """Resilient multi-engine search (DDG → DDG-lite → Bing) with caching."""
    try:
        from skills.utils.search import web_search
    except ImportError as exc:
        return {"error": f"search core unavailable: {exc}", "query": query}
    return web_search(query, num_results=num_results)


def _exec_instagram_lookup(username: str) -> dict:
    try:
        from skills.social_media.ig_lookup import run_sync as ig_run
        result = ig_run(username)
        if isinstance(result, dict) and result.get("error"):
            return {"username": username, "found": False, "error": result["error"]}
        return result
    except Exception as exc:
        return {"username": username, "found": False, "error": str(exc)}


def _exec_sherlock_check(username: str, timeout: int = 10) -> dict:
    try:
        from skills.social_media.sherlock import run_sync as sherlock_run
        # sherlock skill takes a list of usernames
        result = sherlock_run([username])
        return result
    except Exception as exc:
        # Fallback: run sherlock CLI directly
        import subprocess, tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            cmd = ["python3", "-m", "sherlock", username,
                   "--timeout", str(timeout), "--print-found"]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60, cwd=tmp)
            found = []
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("[+]") and "http" in line:
                    found.append(line.replace("[+]", "").strip())
            return {"username": username, "found_count": len(found), "urls": found}
        except Exception as exc2:
            return {"username": username, "error": str(exc2)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _exec_enrich_profile(platform: str, username: str, url: str = "") -> dict:
    try:
        from skills.social_media.enrich import enrich_profile
        if not url:
            url_map = {
                "instagram": f"https://www.instagram.com/{username}/",
                "tiktok":    f"https://www.tiktok.com/@{username}",
                "github":    f"https://github.com/{username}",
                "reddit":    f"https://www.reddit.com/user/{username}",
                "twitter":   f"https://twitter.com/{username}",
                "linkedin":  f"https://www.linkedin.com/in/{username}",
            }
            url = url_map.get(platform.lower(), f"https://{platform}.com/{username}")
        result = enrich_profile(platform, username, url)
        return result or {"platform": platform, "username": username, "url": url, "enriched": False}
    except Exception as exc:
        return {"platform": platform, "username": username, "error": str(exc)}


def _exec_email_osint(email: str) -> dict:
    output: dict[str, Any] = {"email": email}

    # SMTP validation
    try:
        from skills.email.smtp_validate import run_sync as smtp_run
        smtp_res = smtp_run(email)
        output["smtp"] = smtp_res
    except Exception as exc:
        output["smtp"] = {"error": str(exc)}

    # HIBP breach check
    try:
        from skills.email.hibp import run_sync as hibp_run
        hibp_res = hibp_run(email)
        output["hibp"] = hibp_res
    except Exception as exc:
        output["hibp"] = {"error": str(exc)}

    # GHunt (Gmail only)
    if email.lower().endswith(("@gmail.com", "@googlemail.com")):
        try:
            from skills.email.ghunt import run_sync as ghunt_run
            output["ghunt"] = ghunt_run(email)
        except Exception as exc:
            output["ghunt"] = {"error": str(exc)}

    # SERP presence via web_search
    try:
        serp = _exec_web_search(f'"{email}"', num_results=5)
        output["serp_hits"] = len(serp.get("results", []))
        output["serp_indexed"] = output["serp_hits"] > 0
    except Exception:
        pass

    return output


def _phone_basic(phone: str) -> dict:
    """Offline phonenumbers parse — always fast, no network."""
    try:
        import phonenumbers
        from phonenumbers import carrier, geocoder, number_type, PhoneNumberType
        pn = phonenumbers.parse(phone, "FR")
        _types = {PhoneNumberType.MOBILE: "mobile", PhoneNumberType.FIXED_LINE: "landline",
                  PhoneNumberType.VOIP: "voip"}
        return {
            "phone": phone,
            "valid": phonenumbers.is_valid_number(pn),
            "e164": phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164),
            "carrier": carrier.name_for_number(pn, "fr") or None,
            "region": geocoder.description_for_number(pn, "fr") or None,
            "type": _types.get(number_type(pn), "unknown"),
        }
    except Exception as exc:
        return {"phone": phone, "error": str(exc)}


def _exec_phone_lookup(phone: str) -> dict:
    try:
        import asyncio
        from skills.phone.lookup import run as phone_run
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)   # so inner get_event_loop() finds it
        try:
            res = loop.run_until_complete(phone_run(phone))
        finally:
            asyncio.set_event_loop(None)
            loop.close()
        # Full lookup can time out on the French directory scrapes — fall back
        # to the offline phonenumbers parse so we still return carrier/region.
        if not isinstance(res, dict) or res.get("error") or res.get("valid") is None:
            basic = _phone_basic(phone)
            if not basic.get("error"):
                basic["note"] = "Basic parse (web directory lookup unavailable)."
                return basic
        return res
    except Exception:
        return _phone_basic(phone)


def _exec_web_archive(url: str) -> dict:
    import requests
    # CDX API — no snapshots yet?
    try:
        api = "https://web.archive.org/cdx/search/cdx"
        base = {
            "url": url, "output": "json",
            "fl": "timestamp,statuscode",
            "filter": "statuscode:200",
        }

        # First snapshot — limit=1 returns the earliest capture
        r = requests.get(api, params={**base, "limit": 1}, timeout=12)
        first = None
        if r.ok:
            data = r.json()
            if len(data) > 1:  # row 0 is header
                first = data[1][0]  # timestamp

        # Most recent snapshot — negative limit returns the last N captures
        r2 = requests.get(api, params={**base, "limit": -1}, timeout=12)
        last = None
        if r2.ok:
            data2 = r2.json()
            if len(data2) > 1:
                last = data2[-1][0]

        # Rough volume proxy — showNumPages returns the number of CDX index
        # pages the query spans (not the exact capture count, which would
        # require paging through every row).
        r3 = requests.get(
            api,
            params={"url": url, "filter": "statuscode:200", "showNumPages": "true"},
            timeout=12,
        )
        index_pages = None
        if r3.ok:
            try:
                index_pages = int(r3.text.strip())
            except (ValueError, TypeError):
                pass

        def _fmt(ts: str | None) -> str | None:
            if not ts or len(ts) < 8:
                return ts
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"

        return {
            "url": url,
            "first_snapshot": _fmt(first),
            "last_snapshot":  _fmt(last),
            "cdx_index_pages": index_pages,
            "archive_url":    f"https://web.archive.org/web/*/{url}" if first else None,
        }
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def _exec_leak_search(query: str, query_type: str = "auto") -> dict:
    try:
        from skills.breach.leak_search import run_sync as leak_run
        return leak_run(query, query_type=query_type)
    except Exception as exc:
        return {"query": query, "error": str(exc)}


def _exec_geo_imagery(location: str = "", lat=None, lon=None) -> dict:
    try:
        from skills.geo.imagery import run_sync as geo_run
        return geo_run(lat=lat, lon=lon, location=location)
    except Exception as exc:
        return {"location": location, "error": str(exc)}


def _exec_reverse_image(image_url: str) -> dict:
    try:
        from skills.image.reverse_search import run_sync as ris_run
        return ris_run(image_url)
    except Exception as exc:
        return {"image_url": image_url, "error": str(exc)}


def _exec_whois_lookup(domain: str) -> dict:
    try:
        import whois as python_whois
        w = python_whois.whois(domain)
        def _date(v: Any) -> str | None:
            if isinstance(v, list):
                v = v[0]
            return str(v) if v else None
        return {
            "domain":       domain,
            "registrar":    w.registrar,
            "created":      _date(w.creation_date),
            "expires":      _date(w.expiration_date),
            "updated":      _date(w.updated_date),
            "name_servers": w.name_servers if isinstance(w.name_servers, list) else [w.name_servers],
            "org":          w.org,
            "emails":       w.emails if isinstance(w.emails, list) else ([w.emails] if w.emails else []),
            "status":       w.status,
        }
    except ImportError:
        # Fallback: manual socket WHOIS
        try:
            tld = domain.split(".")[-1]
            servers = {
                "fr": "whois.nic.fr", "com": "whois.verisign-grs.com",
                "net": "whois.verisign-grs.com", "org": "whois.pir.org",
                "io": "whois.nic.io",
            }
            srv = servers.get(tld, f"whois.{tld}.whois-servers.net")
            s = socket.socket()
            s.settimeout(10)
            s.connect((srv, 43))
            s.send(f"{domain}\r\n".encode())
            resp = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
            s.close()
            return {"domain": domain, "raw_whois": resp.decode("utf-8", errors="replace")[:1500]}
        except Exception as exc2:
            return {"domain": domain, "error": str(exc2)}
    except Exception as exc:
        return {"domain": domain, "error": str(exc)}


def _exec_validate_email_batch(emails: list[str]) -> dict:
    if not emails:
        return {"results": {}, "valid": []}
    emails = emails[:20]  # hard cap
    try:
        from skills.email.smtp_validate import validate_batch
        results = validate_batch(emails)
        valid = [e for e, r in results.items() if r.get("valid")]
        return {"results": results, "valid": valid, "checked": len(emails)}
    except Exception as exc:
        return {"error": str(exc), "emails_attempted": emails}


def _exec_record_to_case(platform: str, username: str, notes: str = "",
                         case_id: str | None = None) -> dict:
    platform = platform.lower().strip().lstrip("@")
    username = username.strip().lstrip("@")

    url_map = {
        "tiktok":    f"https://www.tiktok.com/@{username}",
        "instagram": f"https://www.instagram.com/{username}/",
        "bereal":    f"https://bere.al/{username}",
        "snapchat":  f"https://www.snapchat.com/add/{username}",
        "steam":     f"https://steamcommunity.com/id/{username}",
        "vinted":    f"https://www.vinted.fr/member/{username}",
        "strava":    f"https://www.strava.com/athletes/{username}",
        "telegram":  f"https://t.me/{username}",
        "reddit":    f"https://www.reddit.com/user/{username}",
        "github":    f"https://github.com/{username}",
        "githubgist": f"https://github.com/{username}",
        "twitter":   f"https://x.com/{username}",
        "x":         f"https://x.com/{username}",
        "pinterest": f"https://www.pinterest.com/{username}",
        "linkedin":  f"https://www.linkedin.com/in/{username}",
    }
    url = url_map.get(platform, f"https://{platform}.com/{username}")

    result: dict = {"status": "recorded", "platform": platform, "username": username, "url": url}

    if case_id:
        try:
            from paw_agent.case_store import get_store, _now, _short_id
            store = get_store()
            fid = _short_id("fct")
            finding = {
                fid: {
                    "id":             fid,
                    "type":           "profile",
                    "platform":       platform,
                    "username":       username,
                    "url":            url,
                    "display_name":   username,
                    "relevance":      1,
                    "manually_added": True,
                    "source":         "watson",
                    "added_at":       _now(),
                    "notes":          notes,
                }
            }
            ok = store.update_findings(case_id, finding, [])
            if ok:
                result["added_to_case"] = True
                result["case_id"] = case_id
            else:
                result["case_error"] = f"Case '{case_id}' not found — finding not saved"
        except Exception as exc:
            result["case_error"] = str(exc)
    else:
        result["note"] = "No case ID — finding recorded but not linked to any case"

    return result


def _exec_add_keyword(keyword: str = "", keywords=None, case_id: str | None = None) -> dict:
    """
    Add one or more keywords to a case as 'keyword' facts (deduplicated,
    case-insensitive). Accepts either `keyword` (a string, comma-separated OK)
    or `keywords` (a list). These keywords feed username/email generation on the
    NEXT investigation run.
    """
    # Normalise input into a clean list
    raw: list[str] = []
    if isinstance(keywords, list):
        raw += [str(k) for k in keywords]
    if keyword:
        raw += re.split(r"[,\n;]+", str(keyword))
    kws = [k.strip().lstrip("#@").lower() for k in raw]
    kws = [k for k in kws if k]
    # de-dup within the request, preserve order
    seen: set[str] = set()
    kws = [k for k in kws if not (k in seen or seen.add(k))]

    result: dict = {"status": "ok", "requested": kws}
    if not kws:
        return {"error": "No keyword provided."}
    if not case_id:
        result["status"] = "not_linked"
        result["note"] = ("No case linked — click «Save as Case» first, then I can "
                          "persist keywords. (Re-run the investigation to use them.)")
        return result

    try:
        from paw_agent.case_store import get_store
        store = get_store()
        case = store.get(case_id)
        if case is None:
            return {"error": f"Case '{case_id}' not found."}
        existing = {str(f.get("value", "")).lower()
                    for f in case.get("facts", {}).values()
                    if f.get("type") == "keyword"}
        added, skipped = [], []
        for k in kws:
            if k in existing:
                skipped.append(k)
                continue
            if store.add_fact(case_id, "keyword", k):
                added.append(k)
                existing.add(k)
        result.update({"added": added, "already_present": skipped, "case_id": case_id,
                       "hint": "Re-run the investigation to regenerate emails/usernames with these keywords."})
    except Exception as exc:
        return {"error": str(exc)}
    return result


_FACT_TYPES = {"email", "phone", "city", "alias", "birth_year", "keyword", "name", "note", "employer"}


def _geocode(place: str, near: str = "") -> dict | None:
    """Geocode a place name to lat/lon via OpenStreetMap Nominatim (free, no key)."""
    import requests
    q = f"{place}, {near}" if near and near.lower() not in place.lower() else place
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 1, "addressdetails": 0},
            headers={"User-Agent": "PAW-OSINT/1.0 (missing-person investigation tool)"},
            timeout=10,
        )
        if r.ok and r.json():
            hit = r.json()[0]
            return {"lat": float(hit["lat"]), "lon": float(hit["lon"]),
                    "display": hit.get("display_name", q)}
    except Exception:
        pass
    return None


def _exif_geotime(image_bytes: bytes) -> dict | None:
    """Extract GPS coords + capture datetime from a photo's EXIF. None if absent."""
    try:
        import io
        from datetime import datetime
        from PIL import Image, ExifTags
        img = Image.open(io.BytesIO(image_bytes))
        exif = getattr(img, "_getexif", lambda: None)()
        if not exif:
            return None
        tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}

        when = ""
        dto = tags.get("DateTimeOriginal") or tags.get("DateTime")
        if dto:
            try:
                when = datetime.strptime(str(dto), "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = str(dto)

        gps = tags.get("GPSInfo")
        lat = lon = None
        if gps:
            g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}
            def _dms(v, ref):
                d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                return -d if ref in ("S", "W") else d
            if g.get("GPSLatitude") and g.get("GPSLongitude"):
                lat = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"))
                lon = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))

        if lat is None and not when:
            return None
        return {"lat": lat, "lon": lon, "when": when}
    except Exception:
        return None


def _reverse_geocode(lat: float, lon: float) -> str:
    """lat/lon → human address via Nominatim reverse."""
    import requests
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 18},
            headers={"User-Agent": "PAW-OSINT/1.0 (missing-person investigation tool)"},
            timeout=10,
        )
        if r.ok:
            return r.json().get("display_name", "")
    except Exception:
        pass
    return ""


def _exec_add_geotime(location: str = "", when: str = "", note: str = "",
                      near: str = "", lat=None, lon=None, case_id: str | None = None) -> dict:
    """
    Record a geo-temporal SIGHTING — 'person was at <location> at <when>'.
    If lat/lon are given (e.g. the user clicked the map) they are used as-is and
    the address is reverse-geocoded; otherwise the place name is geocoded.
    `near` (a city) improves geocoding accuracy for ambiguous place names.
    """
    location = (location or "").strip()
    if lat is not None and lon is not None:
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return {"error": "Invalid coordinates."}
        display = _reverse_geocode(lat, lon)
        value = {"location": location or (display.split(",")[0] if display else "Dropped pin"),
                 "when": (when or "").strip(), "note": (note or "").strip(),
                 "lat": lat, "lon": lon, "display": display or location, "geocoded": True}
    else:
        if not location:
            return {"error": "No location given."}
        geo = _geocode(location, near=near)
        value = {
            "location": location,
            "when":     (when or "").strip(),
            "note":     (note or "").strip(),
            "lat":      geo["lat"] if geo else None,
            "lon":      geo["lon"] if geo else None,
            "display":  geo["display"] if geo else location,
            "geocoded": bool(geo),
        }
    if not case_id:
        return {"status": "not_linked",
                "note": "No case linked — click «Save as Case» first.", "point": value}
    try:
        from paw_agent.case_store import get_store
        fact = get_store().add_fact(case_id, "geotime", value)
        if fact is None:
            return {"error": f"Case '{case_id}' not found."}
        return {"status": "ok", "point": {**value, "id": fact.get("id")},
                "fact_id": fact.get("id"), "case_id": case_id,
                "hint": None if value.get("geocoded") else f"Couldn't geocode '{location}' — pin not placed, but the sighting is saved."}
    except Exception as exc:
        return {"error": str(exc)}


def _exec_add_fact(fact_type: str = "", value: str = "", case_id: str | None = None) -> dict:
    """
    Add a TYPED fact to the case graph (email, phone, city, alias, name, …) so it
    renders with the right icon and colour — not a generic note. Use this for a
    found email/phone/city rather than add_note.
    """
    ftype = (fact_type or "").strip().lower()
    if ftype in ("mail", "e-mail", "adresse", "adresse mail", "courriel"):
        ftype = "email"
    if ftype in ("ville", "location", "lieu"):
        ftype = "city"
    if ftype in ("pseudo", "username", "handle"):
        ftype = "alias"
    if ftype in ("work", "job", "company", "société", "societe", "entreprise",
                 "employeur", "travail", "boîte", "boite"):
        ftype = "employer"
    if ftype not in _FACT_TYPES:
        return {"error": f"Unknown fact type '{fact_type}'. Use one of: {', '.join(sorted(_FACT_TYPES))}."}

    val = value.strip() if isinstance(value, str) else value
    if not val:
        return {"error": "Empty value."}

    # name → {firstname, lastname}
    if ftype == "name" and isinstance(val, str):
        parts = val.split(None, 1)
        val = {"firstname": parts[0], "lastname": parts[1] if len(parts) > 1 else ""}

    if not case_id:
        return {"status": "not_linked", "note": "No case linked — click «Save as Case» first.",
                "fact_type": ftype, "value": val}
    try:
        from paw_agent.case_store import get_store
        store = get_store()
        case = store.get(case_id)
        if case is None:
            return {"error": f"Case '{case_id}' not found."}
        # de-dup identical typed facts
        for f in case.get("facts", {}).values():
            if f.get("type") == ftype and str(f.get("value")).lower() == str(val).lower():
                return {"status": "already_present", "fact_type": ftype, "value": val, "case_id": case_id}
        fact = store.add_fact(case_id, ftype, val)
        if fact is None:
            return {"error": f"Case '{case_id}' not found."}
        return {"status": "ok", "fact_type": ftype, "value": val, "case_id": case_id}
    except Exception as exc:
        return {"error": str(exc)}


def _exec_add_note(text: str = "", case_id: str | None = None) -> dict:
    """Add a free-text note to the case (rendered as a note node on the graph)."""
    text = (text or "").strip()
    if not text:
        return {"error": "Empty note."}
    if not case_id:
        return {"status": "not_linked", "note": "No case linked — click «Save as Case» first.", "text": text}
    try:
        from paw_agent.case_store import get_store
        fact = get_store().add_fact(case_id, "note", text)
        if fact is None:
            return {"error": f"Case '{case_id}' not found."}
        return {"status": "ok", "added": text, "case_id": case_id}
    except Exception as exc:
        return {"error": str(exc)}


def _exec_rerun_email(case_id: str | None = None, limit: int = 40) -> dict:
    """
    Regenerate email candidates from the case's current facts (name, keywords,
    alias, birth year) — including any keywords just added. Pure permutation, no
    network; SMTP validation stays a separate step.
    """
    if not case_id:
        return {"error": "No case linked — click «Save as Case» first."}
    try:
        from paw_agent.case_store import get_store
        from paw_agent.engine.permuter import generate as _gen
        case = get_store().get(case_id)
        if case is None:
            return {"error": f"Case '{case_id}' not found."}

        firstname = lastname = birth_year = ""
        keywords: list[str] = []
        for f in case.get("facts", {}).values():
            t, v = f.get("type"), f.get("value")
            if t == "name" and isinstance(v, dict):
                firstname = v.get("firstname", "") or firstname
                lastname  = v.get("lastname", "") or lastname
            elif t == "keyword" and v:
                keywords.append(str(v))
            elif t == "alias" and v:
                keywords.append(str(v))
            elif t == "birth_year" and v:
                birth_year = str(v)

        if not firstname or not lastname:
            return {"error": "Case has no name fact — cannot generate emails."}

        # de-dup keywords, preserve order
        seen: set[str] = set()
        keywords = [k for k in keywords if not (k.lower() in seen or seen.add(k.lower()))]

        candidates = _gen(firstname=firstname, lastname=lastname,
                          birth_year=birth_year or None, keywords=keywords or None)

        # Per-keyword samples so keywords added late (ranked lower) stay visible
        samples_by_keyword: dict[str, list] = {}
        for kw in keywords:
            kwl = kw.lower()
            hits = [c for c in candidates if kwl in c.split("@", 1)[0]]
            if hits:
                samples_by_keyword[kw] = hits[:6]

        return {
            "status": "ok",
            "case_id": case_id,
            "name": f"{firstname} {lastname}",
            "keywords_used": keywords,
            "total_candidates": len(candidates),
            "candidates": candidates[:max(1, int(limit))],
            "samples_by_keyword": samples_by_keyword,
            "note": "Permutations only. Ask me to validate a batch, or re-run the full "
                    "investigation for SMTP + GHunt + HIBP.",
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Dispatch table ────────────────────────────────────────────────────────────

_EXECUTORS: dict[str, Any] = {
    "web_search":           _exec_web_search,
    "instagram_lookup":     _exec_instagram_lookup,
    "sherlock_check":       _exec_sherlock_check,
    "enrich_profile":       _exec_enrich_profile,
    "email_osint":          _exec_email_osint,
    "phone_lookup":         _exec_phone_lookup,
    "web_archive":          _exec_web_archive,
    "whois_lookup":         _exec_whois_lookup,
    "reverse_image":        _exec_reverse_image,
    "leak_search":          _exec_leak_search,
    "geo_imagery":          _exec_geo_imagery,
    "validate_email_batch": _exec_validate_email_batch,
}


def execute_tool(name: str, params: dict, case_id: str | None = None) -> dict:
    """
    Execute a Watson tool by name with the given parameters.
    case_id is the case DID used by record_to_case to persist findings.
    """
    if name == "record_to_case":
        return _exec_record_to_case(case_id=case_id, **params)
    if name == "add_keyword":
        return _exec_add_keyword(case_id=case_id, **params)
    if name == "rerun_email":
        return _exec_rerun_email(case_id=case_id, **params)
    if name == "add_note":
        return _exec_add_note(case_id=case_id, **params)
    if name == "add_fact":
        return _exec_add_fact(case_id=case_id, **params)
    if name == "add_geotime":
        return _exec_add_geotime(case_id=case_id, **params)
    fn = _EXECUTORS.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = fn(**params)
        if not isinstance(result, dict):
            result = {"result": result}
        return result
    except TypeError as exc:
        return {"error": f"Tool parameter error: {exc}"}
    except Exception as exc:
        return {"error": f"Tool execution failed: {exc}"}
