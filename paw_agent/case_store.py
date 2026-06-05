"""
Case Store — persistent investigation case files.

Each case is saved as cases/{id}.json at the project root.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

_CASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "dossiers")
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id(prefix: str = "fct") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class CaseStore:
    """Thread-safe, file-backed case store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(_CASE_DIR, exist_ok=True)

    # ── Internal helpers ──────────────────────────────────────────────

    def _path(self, did: str) -> str:
        return os.path.join(_CASE_DIR, f"{did}.json")

    def _write(self, d: dict) -> None:
        """Atomic write: write to .tmp then rename."""
        path = self._path(d["id"])
        tmp  = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)

    def _read_raw(self, did: str) -> Optional[dict]:
        path = self._path(did)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ── Public API ────────────────────────────────────────────────────

    def create(self, form_data: dict) -> dict:
        """
        Parse initial form data and create a new case.

        Expected keys (all optional):
          firstname, lastname, keywords (comma string or list),
          pseudo, city, birth_year
        """
        did   = uuid.uuid4().hex[:8]
        now   = _now()

        firstname  = (form_data.get("firstname") or "").strip()
        lastname   = (form_data.get("lastname")  or "").strip()
        pseudo     = (form_data.get("pseudo")    or "").strip()
        city       = (form_data.get("city")      or "").strip()
        birth_year = (form_data.get("birth_year") or "").strip()

        raw_kw = form_data.get("keywords", "")
        if isinstance(raw_kw, list):
            keywords = [k.strip() for k in raw_kw if k.strip()]
        else:
            keywords = [k.strip() for k in raw_kw.split(",") if k.strip()]

        # Build title
        parts = [p for p in [firstname, lastname] if p]
        title = f"Investigation: {' '.join(parts)}" if parts else f"Case {did}"

        facts: dict = {}

        def _add_fact(ftype: str, value) -> None:
            fid = _short_id("fct")
            facts[fid] = {
                "id":       fid,
                "type":     ftype,
                "value":    value,
                "source":   "investigator",
                "added_at": now,
            }

        if firstname or lastname:
            _add_fact("name", {"firstname": firstname, "lastname": lastname})
        for kw in keywords:
            _add_fact("keyword", kw)
        if pseudo:
            _add_fact("alias", pseudo)
        if city:
            _add_fact("city", city)
        if birth_year:
            _add_fact("birth_year", birth_year)

        dossier = {
            "id":         did,
            "title":      title,
            "created_at": now,
            "updated_at": now,
            "facts":      facts,
            "findings":   {},
            "links":      [],
            "log":        [{"ts": now, "event": "case_created", "details": title}],
        }

        with self._lock:
            self._write(dossier)

        return dossier

    def get(self, did: str) -> Optional[dict]:
        with self._lock:
            return self._read_raw(did)

    def list_all(self) -> list[dict]:
        result = []
        try:
            files = sorted(os.listdir(_CASE_DIR), reverse=True)
        except OSError:
            return result
        with self._lock:
            for fname in files:
                if not fname.endswith(".json") or fname.endswith(".tmp"):
                    continue
                did = fname[:-5]
                d   = self._read_raw(did)
                if d:
                    result.append({
                        "id":         d.get("id", did),
                        "title":      d.get("title", did),
                        "created_at": d.get("created_at", ""),
                        "updated_at": d.get("updated_at", ""),
                        "fact_count":    len(d.get("facts", {})),
                        "finding_count": len(d.get("findings", {})),
                    })
        return result

    def add_fact(self, did: str, ftype: str, value) -> Optional[dict]:
        """Add a fact to an existing case. Returns the new fact dict or None."""
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return None
            fid  = _short_id("fct")
            now  = _now()
            fact = {
                "id":       fid,
                "type":     ftype,
                "value":    value,
                "source":   "investigator",
                "added_at": now,
            }
            d["facts"][fid]  = fact
            d["updated_at"]  = now
            d["log"].append({"ts": now, "event": "fact_added",
                             "details": f"{ftype}: {value}"})
            self._write(d)
        return fact

    def remove_fact(self, did: str, fid: str) -> bool:
        """Remove a fact and all links referencing it. Returns True if removed."""
        with self._lock:
            d = self._read_raw(did)
            if d is None or fid not in d.get("facts", {}):
                return False
            removed_fact = d["facts"].pop(fid)
            # Cascade: remove all links that reference this fact id
            d["links"] = [
                lk for lk in d.get("links", [])
                if lk.get("from") != fid and lk.get("to") != fid
            ]
            now = _now()
            d["updated_at"] = now
            d["log"].append({"ts": now, "event": "fact_removed",
                             "details": f"{removed_fact.get('type')}: {removed_fact.get('value')}"})
            self._write(d)
        return True

    def update_findings(self, did: str, new_findings: dict, new_links: list) -> bool:
        """
        Merge new findings into the case.
        Deduplicates findings by id; deduplicates links by (from, to, type).
        """
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return False
            existing_findings = d.get("findings", {})
            existing_links    = d.get("links", [])

            # Merge findings (new overrides same id)
            existing_findings.update(new_findings)
            d["findings"] = existing_findings

            # Merge links (deduplicate by from+to+type)
            existing_keys = {
                (lk.get("from"), lk.get("to"), lk.get("type"))
                for lk in existing_links
            }
            for lk in new_links:
                key = (lk.get("from"), lk.get("to"), lk.get("type"))
                if key not in existing_keys:
                    existing_links.append(lk)
                    existing_keys.add(key)
            d["links"] = existing_links

            now = _now()
            d["updated_at"] = now
            d["log"].append({
                "ts": now, "event": "findings_updated",
                "details": f"+{len(new_findings)} findings, +{len(new_links)} links",
            })
            self._write(d)
        return True

    def set_node_flag(self, did: str, nid: str, flag: "str | None") -> "dict | None":
        """Set or clear a flag on any node. Returns updated node_flags or None."""
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return None
            flags = d.get("node_flags", {})
            if flag:
                flags[nid] = flag
            else:
                flags.pop(nid, None)
            now = _now()
            d["node_flags"] = flags
            d["updated_at"] = now
            d["log"].append({"ts": now, "event": "node_flagged",
                             "details": f"{nid}: {flag or 'cleared'}"})
            self._write(d)
        return flags

    def dismiss_finding(self, did: str, fid: str) -> bool:
        """Toggle dismissed state on a finding. Returns True if case found."""
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return False
            dismissed = set(d.get("dismissed_findings", []))
            if fid in dismissed:
                dismissed.discard(fid)
                action = "finding_restored"
            else:
                dismissed.add(fid)
                action = "finding_dismissed"
            now = _now()
            d["dismissed_findings"] = sorted(dismissed)
            d["updated_at"] = now
            d["log"].append({"ts": now, "event": action, "details": fid})
            self._write(d)
        return True

    def delete(self, did: str) -> bool:
        """Delete a case file entirely. Returns True if deleted."""
        with self._lock:
            path = self._path(did)
            if not os.path.isfile(path):
                return False
            os.remove(path)
        return True

    def add_link(self, did: str, from_id: str, to_id: str,
                link_type: str = "manual", label: str = "linked") -> Optional[list]:
        """Add a manual link between two nodes. Returns updated links list or None."""
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return None
            existing = d.get("links", [])
            key = (from_id, to_id, link_type)
            if any((lk.get("from"), lk.get("to"), lk.get("type")) == key for lk in existing):
                return existing
            now = _now()
            existing.append({
                "from": from_id, "to": to_id,
                "type": link_type, "label": label,
                "confidence": 1.0, "manual": True,
                "added_at": now,
            })
            d["links"] = existing
            d["updated_at"] = now
            d["log"].append({"ts": now, "event": "link_added",
                             "details": f"{from_id} → {to_id} ({link_type})"})
            self._write(d)
        return existing

    def delete_finding(self, did: str, fid: str) -> bool:
        """Permanently delete a finding and its links. Returns True if deleted."""
        with self._lock:
            d = self._read_raw(did)
            if d is None or fid not in d.get("findings", {}):
                return False
            removed = d["findings"].pop(fid)
            d["links"] = [lk for lk in d.get("links", [])
                          if lk.get("from") != fid and lk.get("to") != fid]
            now = _now()
            d["updated_at"] = now
            d["log"].append({"ts": now, "event": "finding_deleted",
                             "details": f"{removed.get('platform', removed.get('type', fid))}"})
            self._write(d)
        return True

    def remove_link(self, did: str, from_id: str, to_id: str) -> Optional[list]:
        """Remove all links between from_id and to_id. Returns updated links or None."""
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return None
            before = len(d.get("links", []))
            d["links"] = [lk for lk in d.get("links", [])
                          if not (lk.get("from") == from_id and lk.get("to") == to_id)]
            now = _now()
            d["updated_at"] = now
            if len(d["links"]) < before:
                d["log"].append({"ts": now, "event": "link_removed",
                                 "details": f"{from_id} → {to_id}"})
            self._write(d)
        return d["links"]

    def append_log(self, did: str, event: str, details: str) -> bool:
        with self._lock:
            d = self._read_raw(did)
            if d is None:
                return False
            now = _now()
            d["log"].append({"ts": now, "event": event, "details": details})
            d["updated_at"] = now
            self._write(d)
        return True


# ── Module-level singleton ────────────────────────────────────────────
_store = CaseStore()


def get_store() -> CaseStore:
    return _store


def _finding_id(key: str) -> str:
    """Generate a deterministic finding ID from a content key."""
    return f"fnd_{hashlib.md5(key.encode()).hexdigest()[:8]}"
