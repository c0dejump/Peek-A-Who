"""
Case Runner — reactive OSINT investigation triggered by individual facts.

When a fact is added to a case, this module starts a background
investigation targeting that specific fact type, then updates the case
with structured findings and AI-synthesised links.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
import traceback
import uuid
from typing import Optional

from paw_agent.case_store import get_store, _finding_id


# ── Platform icon mapping ─────────────────────────────────────────────

_PLATFORM_ICONS = {
    "instagram": "📸",
    "twitter":   "🐦",
    "tiktok":    "📱",
    "snapchat":  "👻",
    "linkedin":  "💼",
    "telegram":  "✈️",
    "facebook":  "📘",
    "youtube":   "▶️",
    "twitch":    "🎮",
    "github":    "🐙",
    "reddit":    "🟠",
    "pinterest": "📌",
    "default":   "🌐",
}

_FACT_TYPE_ICONS = {
    "name":       "👤",
    "keyword":    "🔑",
    "email":      "📧",
    "phone":      "📞",
    "city":       "🏙️",
    "birth_year": "📅",
    "alias":      "🎭",
}


def _det_id(key: str) -> str:
    """Deterministic finding ID from content key."""
    return f"fnd_{hashlib.md5(key.encode()).hexdigest()[:8]}"


# ── CaseInvestigation ─────────────────────────────────────────────

class CaseInvestigation:
    """
    Runs a background OSINT investigation triggered by a specific fact,
    buffers log events, and streams them via SSE.
    """

    def __init__(self, case_id: str, fact_id: Optional[str]):
        self.inv_id      = uuid.uuid4().hex[:8]
        self.case_id  = case_id
        self.fact_id     = fact_id   # None = full re-run
        self.log: list[dict] = []
        self.done        = False
        self._lock       = threading.Lock()

    def _emit(self, text: str, event_type: str = "log") -> None:
        with self._lock:
            self.log.append({"type": event_type, "text": text})

    def start(self) -> None:
        def _thread():
            try:
                asyncio.run(self._run())
            except Exception as exc:
                tb = traceback.format_exc()
                self._emit(f"[ERROR] {exc}\n{tb[-600:]}", "error")
            finally:
                with self._lock:
                    self.log.append({"type": "done", "text": ""})
                    self.done = True

        threading.Thread(target=_thread, daemon=True).start()

    def stream_events(self, start_idx: int = 0):
        """SSE generator — yields dicts, pings every 15 s."""
        idx       = start_idx
        last_ping = time.monotonic()

        while True:
            with self._lock:
                chunk   = list(self.log[idx:])
                is_done = self.done and (idx + len(chunk) >= len(self.log))

            for event in chunk:
                yield event
                idx += 1

            if is_done:
                break

            if not chunk:
                now = time.monotonic()
                if now - last_ping >= 15:
                    yield {"type": "ping"}
                    last_ping = now
                time.sleep(0.2)

    # ── Main async runner ─────────────────────────────────────────

    async def _run(self) -> None:
        store    = get_store()
        case_data  = store.get(self.case_id)
        if not case_data:
            self._emit(f"[ERROR] Case {self.case_id} not found.", "error")
            return

        facts    = case_data.get("facts", {})
        trigger  = facts.get(self.fact_id) if self.fact_id else None

        self._emit(f"[CASE] Starting investigation for: {case_data.get('title', self.case_id)}")
        store.append_log(self.case_id, "investigation_started",
                         f"trigger_fact={self.fact_id or 'all'}")

        # ── Gather context from all facts ─────────────────────────
        firstname  = ""
        lastname   = ""
        keywords: list[str] = []
        aliases: list[str]  = []
        emails: list[str]   = []
        phones: list[str]   = []
        cities: list[str]   = []
        birth_year = ""

        for fid, fact in facts.items():
            ftype = fact.get("type", "")
            val   = fact.get("value")
            if ftype == "name" and isinstance(val, dict):
                firstname = val.get("firstname", "") or firstname
                lastname  = val.get("lastname", "")  or lastname
            elif ftype == "keyword" and val:
                keywords.append(str(val))
            elif ftype == "alias" and val:
                aliases.append(str(val))
            elif ftype == "email" and val:
                emails.append(str(val))
            elif ftype == "phone" and val:
                phones.append(str(val))
            elif ftype == "city" and val:
                cities.append(str(val))
            elif ftype == "birth_year" and val:
                birth_year = str(val) or birth_year

        # Determine which types to run based on trigger fact
        if trigger is None:
            # Full re-run: all types
            run_social   = True
            run_email    = bool(emails)
            run_phone    = bool(phones)
        else:
            ttype        = trigger.get("type", "")
            run_social   = ttype in ("name", "keyword", "alias", "city", "birth_year")
            run_email    = ttype == "email"
            run_phone    = ttype == "phone"
            # city/birth_year: re-run social too since username candidates change
            if ttype in ("city", "birth_year"):
                run_social = True

        new_findings: dict = {}
        new_links: list    = []

        # ── Phase 1: Social media ──────────────────────────────────
        if run_social and (firstname or lastname or keywords or aliases):
            await self._run_social(
                firstname, lastname, keywords, aliases, birth_year, cities,
                facts, new_findings, new_links,
            )

        # ── Phase 2: Email OSINT ───────────────────────────────────
        if run_email and emails:
            await self._run_email(emails, facts, new_findings, new_links)

        # ── Phase 3: Phone OSINT ──────────────────────────────────
        if run_phone and phones:
            await self._run_phone(phones, facts, new_findings, new_links)

        # ── Phase 4: LLM link synthesis ───────────────────────────
        if new_findings:
            await self._llm_link_synthesis(facts, new_findings, new_links, case_data)

        # ── Persist ───────────────────────────────────────────────
        store.update_findings(self.case_id, new_findings, new_links)
        self._emit(
            f"[DONE] {len(new_findings)} findings, {len(new_links)} links added.",
            "log",
        )

    # ── Social media phase ────────────────────────────────────────

    async def _run_social(
        self,
        firstname: str,
        lastname: str,
        keywords: list[str],
        aliases: list[str],
        birth_year: str,
        cities: list[str],
        facts: dict,
        new_findings: dict,
        new_links: list,
    ) -> None:
        from paw_agent.engine.agent import (
            _generate_ig_usernames,
            _search_instagram_direct,
            _search_social_platforms_direct,
            _run_maigret_direct,
        )

        self._emit("[SOCIAL] Generating username candidates...")
        pseudo = aliases[0] if aliases else ""
        usernames = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=keywords, pseudo=pseudo,
        )
        self._emit(f"[SOCIAL] {len(usernames)} candidates generated.")

        # Find name fact id and keyword/alias fact ids for linking
        name_fact_id   = next((fid for fid, f in facts.items() if f["type"] == "name"), None)
        kw_fact_ids    = {f["value"]: fid for fid, f in facts.items() if f["type"] == "keyword"}
        alias_fact_ids = {f["value"]: fid for fid, f in facts.items() if f["type"] == "alias"}

        # Value of the trigger fact (alias/keyword) for username matching
        trigger_fact = facts.get(self.fact_id) if self.fact_id else None
        trigger_value = ""
        if trigger_fact and trigger_fact.get("type") in ("alias", "keyword"):
            v = trigger_fact.get("value", "")
            if isinstance(v, str):
                trigger_value = v

        # Instagram
        self._emit("[SOCIAL] Searching Instagram...")
        try:
            ig_result = await _search_instagram_direct(
                usernames, firstname=firstname, lastname=lastname, keywords=keywords
            )
            found = ig_result.get("found", [])
            self._emit(f"[IG] {len(found)} profiles found (checked {ig_result.get('checked', 0)})")
            for prof in found:
                key = f"instagram:{prof['username']}"
                fnd_id = _det_id(key)
                new_findings[fnd_id] = {
                    "id":           fnd_id,
                    "type":         "social_profile",
                    "platform":     "Instagram",
                    "username":     prof["username"],
                    "display_name": prof.get("display_name", ""),
                    "url":          prof["url"],
                    "relevance":    prof.get("relevance", 0),
                    "first_seen":   prof.get("first_seen"),
                    "found_at":     _now_str(),
                }
                self._emit(f"[IG] Found: @{prof['username']} (relevance={prof.get('relevance', 0)})")
                _add_rule_links(
                    fnd_id, prof["username"], prof.get("display_name", ""),
                    firstname, lastname, keywords, kw_fact_ids,
                    name_fact_id, new_links, self.fact_id,
                    trigger_value=trigger_value, alias_fact_ids=alias_fact_ids,
                )
        except Exception as exc:
            self._emit(f"[IG] Error: {exc}")

        # Other platforms
        self._emit("[SOCIAL] Searching Twitter, TikTok, Snapchat, LinkedIn, Telegram...")
        try:
            sm_result = await _search_social_platforms_direct(
                usernames[:10], firstname=firstname, lastname=lastname, keywords=keywords
            )
            for plat_key, plat_data in sm_result.items():
                label = plat_data.get("label", plat_key)
                for prof in plat_data.get("found", []):
                    key = f"{plat_key}:{prof['username']}"
                    fnd_id = _det_id(key)
                    new_findings[fnd_id] = {
                        "id":           fnd_id,
                        "type":         "social_profile",
                        "platform":     label,
                        "username":     prof["username"],
                        "display_name": prof.get("display_name", ""),
                        "url":          prof["url"],
                        "relevance":    prof.get("relevance", 0),
                        "found_at":     _now_str(),
                    }
                    self._emit(f"[{label}] Found: @{prof['username']}")
                    _add_rule_links(
                        fnd_id, prof["username"], prof.get("display_name", ""),
                        firstname, lastname, keywords, kw_fact_ids,
                        name_fact_id, new_links, self.fact_id,
                        trigger_value=trigger_value, alias_fact_ids=alias_fact_ids,
                    )
        except Exception as exc:
            self._emit(f"[SOCIAL] Error: {exc}")

        # Maigret (cross-platform)
        maigret_names = usernames[:5]
        if maigret_names:
            self._emit(f"[MAIGRET] Scanning {maigret_names[:3]}... (may take 2–3 min)")
            try:
                mg_result = await _run_maigret_direct(maigret_names)
                total = mg_result.get("total_found", 0)
                self._emit(f"[MAIGRET] {total} profiles found across platforms")
                all_sites: dict = mg_result.get("found", {})
                for site_name, site_info in all_sites.items():
                    url = site_info.get("url", "")
                    if not url:
                        continue
                    key    = f"maigret:{site_name}:{url}"
                    fnd_id = _det_id(key)
                    uname  = site_info.get("username", maigret_names[0] if maigret_names else "")
                    new_findings[fnd_id] = {
                        "id":        fnd_id,
                        "type":      "social_profile",
                        "platform":  site_name,
                        "username":  uname,
                        "url":       url,
                        "tags":      site_info.get("tags", []),
                        "relevance": 5,
                        "found_at":  _now_str(),
                    }
                    # Link only when the found username actually matches a known alias/keyword
                    _add_rule_links(
                        fnd_id, uname, "",
                        firstname, lastname, keywords, kw_fact_ids,
                        name_fact_id, new_links, self.fact_id,
                        trigger_value=trigger_value, alias_fact_ids=alias_fact_ids,
                    )
            except Exception as exc:
                self._emit(f"[MAIGRET] Error: {exc}")

    # ── Email phase ───────────────────────────────────────────────

    async def _run_email(
        self,
        emails: list[str],
        facts: dict,
        new_findings: dict,
        new_links: list,
    ) -> None:
        self._emit("[EMAIL] Analyzing email addresses (rule-based)...")
        email_fact_ids = {f["value"]: fid for fid, f in facts.items() if f["type"] == "email"}

        for email in emails:
            self._emit(f"[EMAIL] Processing: {email}")
            domain = email.split("@")[-1].lower() if "@" in email else ""
            is_gmail = domain == "gmail.com"

            key    = f"email:{email}"
            fnd_id = _det_id(key)
            new_findings[fnd_id] = {
                "id":       fnd_id,
                "type":     "email_validated",
                "address":  email,
                "domain":   domain,
                "is_gmail": is_gmail,
                "note":     "Email registered as fact — run GHunt/HIBP for deeper OSINT",
                "found_at": _now_str(),
            }

            fact_id = email_fact_ids.get(email) or self.fact_id
            if fact_id:
                new_links.append({
                    "from":       fact_id,
                    "to":         fnd_id,
                    "type":       "email_confirmed",
                    "reason":     f"Email {email} recorded as investigator fact",
                    "confidence": 1.0,
                })

            if is_gmail:
                self._emit(f"[EMAIL] Gmail detected — GHunt can retrieve Google profile data")

    # ── Phone phase ───────────────────────────────────────────────

    async def _run_phone(
        self,
        phones: list[str],
        facts: dict,
        new_findings: dict,
        new_links: list,
    ) -> None:
        from paw_agent.engine.agent import _search_phone_direct

        phone_fact_ids = {f["value"]: fid for fid, f in facts.items() if f["type"] == "phone"}

        for phone in phones:
            self._emit(f"[PHONE] Analyzing: {phone}")
            try:
                result = await _search_phone_direct(phone)
                key    = f"phone:{phone}"
                fnd_id = _det_id(key)

                summary_parts = []
                if result.get("valid"):
                    summary_parts.append(f"Valid {result.get('type', '')} number")
                if result.get("carrier"):
                    summary_parts.append(f"Carrier: {result['carrier']}")
                if result.get("region"):
                    summary_parts.append(f"Region: {result['region']}")

                new_findings[fnd_id] = {
                    "id":        fnd_id,
                    "type":      "phone_result",
                    "phone":     phone,
                    "e164":      result.get("e164", ""),
                    "valid":     result.get("valid", False),
                    "number_type": result.get("type", ""),
                    "carrier":   result.get("carrier", ""),
                    "region":    result.get("region", ""),
                    "country":   result.get("country_code", ""),
                    "summary":   "; ".join(summary_parts) or "Phone analyzed",
                    "found_at":  _now_str(),
                }

                if result.get("ignorant_platforms"):
                    found_plats = [
                        p["site"] for p in result["ignorant_platforms"]
                        if p.get("status") == "found"
                    ]
                    if found_plats:
                        new_findings[fnd_id]["platforms_registered"] = found_plats
                        self._emit(f"[PHONE] Registered on: {', '.join(found_plats[:5])}")

                fact_id = phone_fact_ids.get(phone) or self.fact_id
                if fact_id:
                    new_links.append({
                        "from":       fact_id,
                        "to":         fnd_id,
                        "type":       "phone_linked",
                        "reason":     f"Phone {phone} analyzed: {'; '.join(summary_parts[:2])}",
                        "confidence": 1.0,
                    })
                self._emit(f"[PHONE] {'; '.join(summary_parts) or 'Done'}")
            except Exception as exc:
                self._emit(f"[PHONE] Error: {exc}")

    # ── LLM link synthesis ────────────────────────────────────────

    async def _llm_link_synthesis(
        self,
        facts: dict,
        new_findings: dict,
        new_links: list,
        case_data: dict,
    ) -> None:
        try:
            import litellm  # noqa: F401
        except ImportError:
            return

        self._emit("[LLM] Synthesizing connections with AI...")
        try:
            existing_links = case_data.get("links", [])
            all_findings   = {**case_data.get("findings", {}), **new_findings}

            prompt = (
                "You are an OSINT analyst. Analyze these facts and findings and identify connections.\n\n"
                f"Facts (investigator-provided):\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
                f"Findings (OSINT discovered):\n{json.dumps(all_findings, ensure_ascii=False, indent=2)}\n\n"
                f"Existing links:\n{json.dumps(existing_links + new_links, ensure_ascii=False, indent=2)}\n\n"
                "Output ONLY a JSON array of NEW links to add (not duplicating existing ones):\n"
                '[{"from": "<fact_or_finding_id>", "to": "<finding_id>", '
                '"type": "<type>", "reason": "<1 sentence>", "confidence": 0.0-1.0}]\n\n'
                "Link types: name_match, keyword_in_username, keyword_in_displayname, "
                "email_confirmed, phone_linked, location_match, cross_platform_same_person\n\n"
                "Only output valid JSON. No explanation."
            )

            import os
            from dotenv import load_dotenv
            load_dotenv(
                dotenv_path=os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", ".env")
                )
            )

            import litellm as _ll
            _ll.suppress_debug_info = True

            model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
            resp  = _ll.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
            )
            raw = resp.choices[0].message.content.strip()

            # Extract JSON array from response
            import re
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                llm_links = json.loads(m.group(0))
                added = 0
                existing_keys = {
                    (lk.get("from"), lk.get("to"), lk.get("type"))
                    for lk in existing_links + new_links
                }
                for lk in llm_links:
                    if not isinstance(lk, dict):
                        continue
                    key = (lk.get("from"), lk.get("to"), lk.get("type"))
                    if key not in existing_keys:
                        new_links.append(lk)
                        existing_keys.add(key)
                        added += 1
                self._emit(f"[LLM] Added {added} AI-inferred links.")
        except Exception as exc:
            self._emit(f"[LLM] Skipped: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────

def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_rule_links(
    fnd_id: str,
    username: str,
    display_name: str,
    firstname: str,
    lastname: str,
    keywords: list[str],
    kw_fact_ids: dict,
    name_fact_id: Optional[str],
    new_links: list,
    trigger_fact_id: Optional[str],
    trigger_value: str = "",       # actual value of the trigger fact (alias/keyword)
    alias_fact_ids: Optional[dict] = None,  # {alias_str: fact_id}
) -> None:
    """
    Create links only when there is real evidence of a connection.
    No generic 'I triggered this' links — every link must be justified by content.
    """
    un_low = username.lower().strip()
    dn_low = (display_name or "").lower()
    tv     = trigger_value.lower().strip()

    # 1. Alias fact matches username directly (strongest signal)
    if trigger_fact_id and tv and un_low:
        # Exact match or one contains the other (handles jdoe42 ↔ jdoe_42 etc.)
        if tv == un_low or (len(tv) >= 3 and tv in un_low) or (len(un_low) >= 3 and un_low in tv):
            new_links.append({
                "from":       trigger_fact_id,
                "to":         fnd_id,
                "type":       "username_match",
                "reason":     f"Username @{username} matches '{trigger_value}'",
                "confidence": 0.95,
            })
            return  # strongest match found — stop here

    # 2. Any alias matches username
    if alias_fact_ids:
        for alias, alias_fid in alias_fact_ids.items():
            al = alias.lower().strip()
            if al and len(al) >= 3 and (al == un_low or al in un_low or un_low in al):
                new_links.append({
                    "from":       alias_fid,
                    "to":         fnd_id,
                    "type":       "username_match",
                    "reason":     f"Username @{username} matches alias '{alias}'",
                    "confidence": 0.9,
                })
                return

    # 3. Keyword in username or display name
    for kw, kw_fid in kw_fact_ids.items():
        kw_l = kw.lower().strip()
        if kw_l and len(kw_l) >= 3 and kw_l in un_low:
            new_links.append({
                "from":       kw_fid,
                "to":         fnd_id,
                "type":       "keyword_in_username",
                "reason":     f"Keyword '{kw}' found in username @{username}",
                "confidence": 0.9,
            })
        elif kw_l and len(kw_l) >= 3 and kw_l in dn_low:
            new_links.append({
                "from":       kw_fid,
                "to":         fnd_id,
                "type":       "keyword_in_displayname",
                "reason":     f"Keyword '{kw}' in display name '{display_name}'",
                "confidence": 0.75,
            })

    # 4. Real name match in display name
    if name_fact_id and dn_low:
        fn_l = firstname.lower() if firstname else ""
        ln_l = lastname.lower()  if lastname  else ""
        if (fn_l and len(fn_l) >= 3 and fn_l in dn_low) or \
           (ln_l and len(ln_l) >= 3 and ln_l in dn_low):
            new_links.append({
                "from":       name_fact_id,
                "to":         fnd_id,
                "type":       "name_match",
                "reason":     f"Name match in display name '{display_name}'",
                "confidence": 0.8,
            })

    # No generic fallback — if none of the above matched, no link is created.


# ── Global store ──────────────────────────────────────────────────────

_active_case_investigations: dict[str, CaseInvestigation] = {}


def start_case_investigation(case_id: str, fact_id: Optional[str]) -> str:
    """Start a background investigation for a case fact. Returns inv_id."""
    inv = CaseInvestigation(case_id, fact_id)
    _active_case_investigations[inv.inv_id] = inv
    inv.start()
    return inv.inv_id


def get_case_investigation(inv_id: str) -> Optional[CaseInvestigation]:
    return _active_case_investigations.get(inv_id)
