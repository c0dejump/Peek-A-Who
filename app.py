import hashlib
import json
import os
import re as _re_global
import sys

from flask import Flask, Response, redirect, render_template, request, session, url_for

sys.path.insert(0, os.path.dirname(__file__))

from paw_agent.engine.runner import start_investigation, get_investigation, _HISTORY_DIR
from paw_agent.config_manager import (
    DEFAULT_MODELS, get_current_config, get_ollama_models, save_config
)
from paw_agent.case_store import get_store
from paw_agent.case_runner import start_case_investigation, get_case_investigation


def _fnd_id(key: str) -> str:
    return f"fnd_{hashlib.md5(key.encode()).hexdigest()[:8]}"


def _latest_history_report() -> tuple[dict, dict]:
    """Return (report, target) from the most recent history JSON, or ({}, {})."""
    if not os.path.isdir(_HISTORY_DIR):
        return {}, {}
    for fname in sorted(os.listdir(_HISTORY_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_HISTORY_DIR, fname), encoding="utf-8") as f:
                data = json.load(f)
            return data.get("report", {}), data.get("target", {})
        except Exception:
            continue
    return {}, {}


# ── Instant Watson actions (no LLM, < 100ms) ──────────────────────────────────

_INSTANT_PLATFORMS = (
    "tiktok|instagram|bereal|snapchat|steam|vinted|strava|telegram"
    "|reddit|github|twitter|linkedin|facebook|youtube|twitch|discord|pinterest"
)
# Pass 1 — platform → ≤30 chars → explicit @/"` quote → username
# Apostrophes excluded: French contractions (d'Angers, c'est, y'a…) cause false positives.
_INSTANT_RE_QUOTED = _re_global.compile(
    r"\b(" + _INSTANT_PLATFORMS + r")\b.{0,30}?[@\"`]([\w.\-_]{3,40})",
    _re_global.I | _re_global.S,
)
# Pass 2 — platform + optional connector + bare username word
_INSTANT_RE_BARE = _re_global.compile(
    r"\b(" + _INSTANT_PLATFORMS + r")\b\s+(?:(?:is|c.{0,3}est|est)\s+)?([\w.\-_]{3,40})\b",
    _re_global.I,
)
# Words that signal "please record/save this"
_INSTANT_RECORD_RE = _re_global.compile(
    r'\b(?:add|case|ajoute?|enregistre?|found|trouv[eé]|save|record|met[sz]?|put|note)\b',
    _re_global.I,
)
# Words to reject as usernames (common connectors, English/French nouns)
_NOISE_WORDS = frozenset(
    "the his her its our add and for but not que les des une son est cas pas sur "
    "lui elle avec dans account profile page user handle channel group name "
    "tu as il elle on nous vous ils elles avez avons ont".split()
)


def _instant_record_to_case(question: str, inv_id: str, case_id: str = "") -> dict | None:
    """
    Detect "record platform @username to case" intent without LLM.
    Returns execute result dict on match, else None.
    case_id is the case DID; inv_id kept for signature compat but not used for writing.
    """
    # Questions are never recording commands — let Watson handle them
    stripped = question.strip()
    if stripped.endswith("?"):
        return None

    if not _INSTANT_RECORD_RE.search(question):
        return None
    # Try quoted / @-prefixed username first (most explicit)
    for pattern in (_INSTANT_RE_QUOTED, _INSTANT_RE_BARE):
        m = pattern.search(question)
        if m:
            platform = m.group(1).lower()
            username = m.group(2)
            if username.lower() not in _NOISE_WORDS:
                from skills.core.watson_tools import _exec_record_to_case
                return _exec_record_to_case(platform=platform, username=username,
                                            case_id=case_id or None)
    return None

# ── Instant "add keyword" action (no LLM) ─────────────────────────────────────
_KW_VERB     = r"(?:ajout\w*|add|enregistr\w*|register|met[sz]?\w*|rajout\w*)"
_KW_NOUN     = r"(?:keywords?|mots?[-\s]?cl[ée]s?|kw)"
_KW_INTENT_RE = _re_global.compile(
    rf"\b{_KW_VERB}\b.*\b{_KW_NOUN}\b|\b{_KW_NOUN}\b.*\b{_KW_VERB}\b",
    _re_global.I | _re_global.S,
)
_KW_QUOTED_RE = _re_global.compile(r"[\"'“”«»]\s*([\w.\-]{1,30})\s*[\"'“”«»]")
_KW_NOISE = frozenset(
    "keyword keywords mot mots cle cles clé clés kw pour les des une le la et ainsi "
    "que surtout email emails mail mails adresse adresses de du au aux en and ou or "
    "comme as to dans in".split()
)


def _instant_add_keyword(question: str, case_id: str = "") -> dict | None:
    """Detect 'add keyword(s) X, Y' without an LLM. Returns a result dict or None."""
    if not _KW_INTENT_RE.search(question):
        return None
    # Prefer quoted tokens (most explicit); else bare words after the keyword noun
    kws = _KW_QUOTED_RE.findall(question)
    if not kws:
        # bare words AFTER the noun: "keyword: X, Y"
        seg = ""
        m = _re_global.search(rf"{_KW_NOUN}\s*[:=]?\s+(.+)$", question, _re_global.I)
        if m:
            seg = m.group(1)
        # or bare words BETWEEN verb and noun: "ajoute X et Y comme keyword"
        if not seg.strip():
            m2 = _re_global.search(
                rf"{_KW_VERB}\s+(.+?)\s+(?:comme|en|as|to|dans|in)\s+{_KW_NOUN}",
                question, _re_global.I)
            if m2:
                seg = m2.group(1)
        if seg:
            tail = _re_global.split(r"\b(?:pour|surtout|afin|because|parce)\b", seg, 1)[0]
            kws = [w for w in _re_global.split(r"[,\s;/]+", tail) if w]
    kws = [k.strip().lstrip("#@").lower() for k in kws]
    kws = [k for k in kws if k and k.lower() not in _KW_NOISE and len(k) >= 2]
    if not kws:
        return None
    from skills.core.watson_tools import _exec_add_keyword
    return _exec_add_keyword(keyword=",".join(kws), case_id=case_id or None)


# ── Instant "re-run email" action (no LLM) ────────────────────────────────────
_RERUN_EMAIL_RE = _re_global.compile(
    r"\b(relanc\w*|re[-\s]?run|r[eé]g[eé]n\w*|g[eé]n[eè]r\w*|refai[st]?\w*|redo)\b"
    r".*\b(e?[-\s]?mails?|adresses?|courriels?)\b"
    r"|\b(e?[-\s]?mails?|adresses?)\b.*\b(keywords?|mots?[-\s]?cl[ée]s?)\b",
    _re_global.I | _re_global.S,
)


def _instant_rerun_email(question: str, case_id: str = "") -> dict | None:
    """Detect 'relance/regenerate the email part' without an LLM."""
    if not _RERUN_EMAIL_RE.search(question):
        return None
    from skills.core.watson_tools import _exec_rerun_email
    return _exec_rerun_email(case_id=case_id or None)


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "paw-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def _quick_llm_ping(backend: str, timeout: int = 5) -> bool:
    """
    Fast sanity-check: returns True if the LLM backend is reachable AND the model exists.
    For Ollama, checks /api/tags and verifies the model name is in the list.
    """
    try:
        if backend.startswith("ollama/"):
            import requests as _req
            model_name = backend[len("ollama/"):]
            host = os.environ.get("OLLAMA_HOST",
                                  os.environ.get("OLLAMA_API_BASE", "http://localhost:11434"))
            r = _req.get(f"{host}/api/tags", timeout=timeout)
            if r.status_code != 200:
                return False
            installed = [m.get("name", "") for m in r.json().get("models", [])]
            if model_name and not any(m == model_name or m.startswith(model_name + ":")
                                      for m in installed):
                # Model not pulled — log clearly
                import logging
                logging.warning("Ollama model '%s' not found. Installed: %s", model_name, installed)
                return False
            return True
        # For API backends (openai/, anthropic/, …) assume reachable
        return True
    except Exception:
        return False


# ── Page 1 : Target form ───────────────────────────────────────

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/investigate", methods=["POST"])
def investigate():
    firstname  = request.form.get("firstname", "").strip()
    lastname   = request.form.get("lastname", "").strip()
    pseudo     = request.form.get("pseudo", "").strip()
    mail       = request.form.get("mail", "").strip()
    phone      = request.form.get("phone", "").strip()
    city_raw   = request.form.get("city", "").strip()
    cities     = [c.strip() for c in city_raw.split(",") if c.strip()]
    birth_year = request.form.get("birth_year", "").strip()
    keywords   = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    language   = request.form.get("language", "all")
    modules    = request.form.getlist("modules") or ["demographics", "diplomas", "email"]
    picture    = None

    pictures = []
    for f in request.files.getlist("picture"):
        if f and f.filename:
            upload_dir = os.path.join("static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            import werkzeug.utils
            safe_name = werkzeug.utils.secure_filename(f.filename)
            path = os.path.join(upload_dir, safe_name)
            f.save(path)
            pictures.append(path)
    picture = pictures[0] if pictures else None

    target = {
        "firstname":  firstname,
        "lastname":   lastname,
        "pseudo":     pseudo,
        "mail":       mail,
        "phone":      phone,
        "city":       city_raw,
        "cities":     cities,
        "birth_year": birth_year,
        "keywords":   keywords,
        "language":   language,
        "modules":    modules,
        "picture":    picture,
        "pictures":   pictures,
    }

    # Start investigation immediately in background
    inv_id = start_investigation(target)
    session["target"]      = target
    session["inv_id"]      = inv_id
    session["create_case"] = request.form.get("create_case") == "1"
    session.pop("case_id", None)   # fresh investigation → not linked to a case yet
    return redirect(url_for("investigation"))


# ── Page 2 : Live investigation terminal ──────────────────────

@app.route("/investigation")
def investigation():
    target  = session.get("target")
    inv_id  = session.get("inv_id")
    case_id = session.get("case_id", "")
    if not target or not inv_id:
        # No live investigation in session — if it was saved as a case, go there
        if case_id and get_store().get(case_id):
            return redirect(url_for("case_detail", did=case_id))
        return redirect(url_for("home"))

    inv = get_investigation(inv_id)
    inv_done = inv.done if inv else True
    # Keep the session pointer accurate to the investigation's own case link
    if inv and getattr(inv, "case_id", ""):
        case_id = inv.case_id
        session["case_id"] = case_id

    return render_template("investigation.html", target=target,
                           inv_id=inv_id, inv_done=inv_done, case_id=case_id,
                           create_case=session.get("create_case", True))


@app.route("/investigation/confirm", methods=["POST"])
def investigation_confirm():
    """User confirms or stops at the passive-intel checkpoint."""
    inv_id = session.get("inv_id")
    inv    = get_investigation(inv_id) if inv_id else None
    if not inv:
        return {"error": "No active investigation"}, 404
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "stop")
    inv.confirm(action)
    return {"ok": True, "action": action}


@app.route("/investigation/rerun", methods=["POST"])
def investigation_rerun():
    """Re-run the same target."""
    target = session.get("target")
    if not target:
        return {"error": "No target"}, 400
    inv_id = start_investigation(target)
    session["inv_id"] = inv_id
    return {"inv_id": inv_id, "ok": True}


@app.route("/run")
def run():
    """SSE stream — replays full buffered log then streams live events."""
    inv_id = session.get("inv_id")
    inv    = get_investigation(inv_id) if inv_id else None

    if not inv:
        def _empty():
            yield f"data: {json.dumps({'type': 'error', 'text': 'No active investigation'})}\n\n"
        return Response(_empty(), mimetype="text/event-stream")

    def generate():
        for event in inv.stream_events(start_idx=0):
            if event["type"] == "ping":
                yield ": ping\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Backward compat redirect ───────────────────────────────────

@app.route("/results")
def results():
    return redirect(url_for("investigation"))


# ── Page 3 : Configuration ─────────────────────────────────────

@app.route("/config", methods=["GET", "POST"])
def config():
    flash = None

    if request.method == "POST":
        try:
            save_config(request.form)
            flash = {"type": "success", "msg": "&#10003; Configuration saved to .env"}
        except Exception as exc:
            flash = {"type": "error", "msg": f"Error saving config: {exc}"}

    cfg = get_current_config()
    ollama_running, ollama_installed = get_ollama_models(cfg.get("ollama_url", "http://localhost:11434"))
    ollama_suggested = [m for m in DEFAULT_MODELS["ollama"] if m not in ollama_installed]

    return render_template(
        "config.html",
        cfg=cfg,
        models=DEFAULT_MODELS,
        models_json=json.dumps(DEFAULT_MODELS),
        ollama_running=ollama_running,
        ollama_installed=ollama_installed,
        ollama_suggested=ollama_suggested,
        flash=flash,
    )


@app.route("/api/ollama-models")
def api_ollama_models():
    url = request.args.get("url", "http://localhost:11434")
    running, models = get_ollama_models(url)
    suggested = [m for m in DEFAULT_MODELS["ollama"] if m not in models]
    return {"running": running, "models": models, "suggested": suggested}


# ── Investigation history ──────────────────────────────────

@app.route("/history")
def history():
    entries = []
    if os.path.isdir(_HISTORY_DIR):
        for fname in sorted(os.listdir(_HISTORY_DIR), reverse=True):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(_HISTORY_DIR, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                tgt = data.get("target", {})
                rpt = data.get("report", {})
                entries.append({
                    "filename":   fname,
                    "saved_at":   data.get("saved_at", fname[:15]),
                    "firstname":  tgt.get("firstname", ""),
                    "lastname":   tgt.get("lastname", ""),
                    "pseudo":     tgt.get("pseudo", ""),
                    "risk_level": rpt.get("risk_level", "none"),
                    "emails_found": len(rpt.get("emails", {}).get("breached", [])),
                })
            except Exception:
                pass
    return render_template("history.html", entries=entries)


@app.route("/history/<filename>/delete", methods=["POST"])
def history_delete(filename):
    if not filename.endswith(".json") or "/" in filename or "\\" in filename:
        return {"error": "invalid filename"}, 400
    path = os.path.join(_HISTORY_DIR, filename)
    if not os.path.isfile(path):
        return {"error": f"not found: {filename}"}, 404
    try:
        os.remove(path)
    except Exception as exc:
        return {"error": str(exc)}, 500
    return {"ok": True}


@app.route("/history/<filename>")
def history_detail(filename):
    if not filename.endswith(".json") or "/" in filename or "\\" in filename:
        return {"error": "invalid"}, 400
    path = os.path.join(_HISTORY_DIR, filename)
    if not os.path.isfile(path):
        return {"error": "not found"}, 404
    with open(path, encoding="utf-8") as f:
        return Response(f.read(), mimetype="application/json")


# ── Case (dossier) routes ──────────────────────────────────────

@app.route("/cases")
def cases_list():
    store = get_store()
    return render_template("cases.html", cases=store.list_all())


@app.route("/cases/new", methods=["POST"])
def cases_new():
    store = get_store()
    case  = store.create(request.form)
    return redirect(url_for("case_detail", did=case["id"]))


@app.route("/cases/from-investigation", methods=["POST"])
def cases_from_investigation():
    """Create a new case pre-filled from the current completed investigation."""
    inv_id = session.get("inv_id")
    target = session.get("target", {})
    inv    = get_investigation(inv_id) if inv_id else None
    report = inv.report if inv else {}

    # Build initial facts from the target
    form_data = {
        "firstname":  target.get("firstname", ""),
        "lastname":   target.get("lastname", ""),
        "keywords":   target.get("keywords", []),
        "pseudo":     target.get("pseudo", ""),
        "city":       target.get("city", ""),
        "birth_year": target.get("birth_year", ""),
    }
    store = get_store()
    case  = store.create(form_data)
    did   = case["id"]

    # Find name fact id for linking findings
    facts = case.get("facts", {})
    name_fact_id = next(
        (fid for fid, f in facts.items() if f["type"] == "name"), None
    )

    # Import confirmed emails as facts and collect their IDs
    email_fact_ids: dict[str, str] = {}
    emails_rpt = report.get("emails", {})
    confirmed_emails = list(dict.fromkeys(
        emails_rpt.get("smtp_valid", []) + emails_rpt.get("ghunt_confirmed", [])
    ))[:8]
    for em in confirmed_emails:
        f = store.add_fact(did, "email", em)
        if f:
            email_fact_ids[em] = f["id"]

    # Import validated phone as fact
    phone_fact_id = None
    if target.get("phone"):
        ph = report.get("phone", {})
        if ph.get("valid"):
            pf = store.add_fact(did, "phone", ph.get("e164") or target["phone"])
            if pf:
                phone_fact_id = pf["id"]

    # ── Build findings from report ────────────────────────────────
    new_findings: dict = {}
    new_links:    list = []

    def _link(from_id, to_id, ltype, reason="", confidence=0.8):
        if from_id and to_id:
            new_links.append({"from": from_id, "to": to_id,
                               "type": ltype, "reason": reason,
                               "confidence": confidence})

    # Collect aliases/keywords for link matching
    pseudo     = target.get("pseudo", "")
    kw_list    = target.get("keywords", [])
    firstname  = target.get("firstname", "").lower()
    lastname   = target.get("lastname", "").lower()

    def _name_in_display(display: str) -> bool:
        dn = display.lower()
        return (bool(firstname) and len(firstname) >= 3 and firstname in dn) or \
               (bool(lastname)  and len(lastname)  >= 3 and lastname  in dn)

    def _username_matches(uname: str) -> bool:
        un = uname.lower()
        if pseudo and len(pseudo) >= 3:
            psl = pseudo.lower()
            if psl == un or psl in un or un in psl:
                return True
        for kw in kw_list:
            kwl = kw.lower()
            if kwl and len(kwl) >= 3 and (kwl == un or kwl in un):
                return True
        return False

    # Social profiles are added to the graph only when manually validated
    # via the "Validate" button — not auto-injected here.

    # Phone finding (carrier/region details)
    ph = report.get("phone", {})
    if ph.get("valid") and phone_fact_id:
        fnd_id = _fnd_id(f"phone:{ph.get('e164', target.get('phone', ''))}")
        new_findings[fnd_id] = {
            "id":      fnd_id,
            "type":    "phone_info",
            "phone":   ph.get("e164", target.get("phone", "")),
            "carrier": ph.get("carrier", ""),
            "region":  ph.get("region", ""),
            "valid":   True,
        }
        _link(phone_fact_id, fnd_id, "phone_linked", "Phone carrier/region info", 0.9)

    if new_findings:
        store.update_findings(did, new_findings, new_links)

    # Persist the link so the terminal/Watson still know the case after navigation.
    session["case_id"] = did
    if inv:
        inv.case_id = did
    return {"case_id": did, "redirect": f"/cases/{did}"}


@app.route("/cases/<did>")
def case_detail(did: str):
    store    = get_store()
    case     = store.get(did)
    if not case:
        return redirect(url_for("cases_list"))
    parent   = store.get(case["parent_id"]) if case.get("parent_id") else None
    children = store.get_children(did)
    return render_template("case.html", case=case, parent=parent, children=children)


@app.route("/cases/<did>/fact", methods=["POST"])
def case_add_fact(did: str):
    store = get_store()
    data  = request.get_json(silent=True) or {}
    ftype = data.get("type", "").strip()
    value = data.get("value", "")

    if not ftype:
        return {"error": "Missing fact type"}, 400

    if ftype == "name" and isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass

    fact = store.add_fact(did, ftype, value)
    if fact is None:
        return {"error": "Case not found"}, 404

    # Notes and images don't trigger an investigation
    if ftype in ("note", "image"):
        return {"fact": fact, "inv_id": None}

    inv_id = start_case_investigation(did, fact["id"])
    return {"fact": fact, "inv_id": inv_id}


@app.route("/cases/<did>/fact/<fid>", methods=["DELETE"])
def case_remove_fact(did: str, fid: str):
    store = get_store()
    ok    = store.remove_fact(did, fid)
    if not ok:
        return {"error": "Fact or case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/node/<nid>/flag", methods=["POST"])
def case_node_flag(did: str, nid: str):
    store = get_store()
    data  = request.get_json(silent=True) or {}
    flag  = data.get("flag") or None          # None clears the flag
    flags = store.set_node_flag(did, nid, flag)
    if flags is None:
        return {"error": "Case not found"}, 404
    return {"node_flags": flags}


@app.route("/cases/<did>/node/<nid>/note", methods=["POST"])
def case_node_note(did: str, nid: str):
    """Set inline annotation text on a fact or finding — no new node, no link."""
    store = get_store()
    data  = request.get_json(silent=True) or {}
    text  = data.get("text", "")
    ok    = store.update_node_note(did, nid, text)
    if not ok:
        return {"error": "Node or case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/sub-case", methods=["POST"])
def case_create_sub(did: str):
    """Create a sub-case under the given parent case."""
    store = get_store()
    if not store.get(did):
        return {"error": "Parent case not found"}, 404
    data  = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    sub   = store.create({"title": title or f"Sub-case of {did}"}, parent_id=did)
    return {"case_id": sub["id"], "redirect": f"/cases/{sub['id']}"}


@app.route("/cases/<did>/image", methods=["POST"])
def case_add_image(did: str):
    """Upload an image and attach it as an image fact to the case."""
    store = get_store()
    if not store.get(did):
        return {"error": "Case not found"}, 404
    f = request.files.get("image")
    if not f or not f.filename:
        return {"error": "No image file provided"}, 400
    import werkzeug.utils
    upload_dir = os.path.join("static", "uploads", "cases", did)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = werkzeug.utils.secure_filename(f.filename)
    path = os.path.join(upload_dir, safe_name)
    f.save(path)
    # Store relative path from static/ so we can serve it
    rel_path = os.path.join("cases", did, safe_name)
    fact = store.add_fact(did, "image", rel_path)
    if fact is None:
        return {"error": "Could not add image fact"}, 500
    return {"fact": fact, "url": f"/static/uploads/{rel_path}"}


@app.route("/cases/<did>/fact/<fid>/value", methods=["PATCH"])
def case_update_fact_value(did: str, fid: str):
    """Update the value of a fact (e.g. note text auto-save)."""
    store = get_store()
    data  = request.get_json(silent=True) or {}
    value = data.get("value", "")
    ok    = store.update_fact_value(did, fid, value)
    if not ok:
        return {"error": "Fact or case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/color", methods=["POST"])
def case_set_color(did: str):
    """Persist a portfolio color for the case."""
    store = get_store()
    data  = request.get_json(silent=True) or {}
    color = (data.get("color") or "").strip()
    if not color:
        return {"error": "color required"}, 400
    ok = store.update_case_color(did, color)
    if not ok:
        return {"error": "Case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/delete", methods=["POST"])
def case_delete(did: str):
    store = get_store()
    try:
        ok = store.delete(did)
    except Exception as exc:
        return {"error": str(exc)}, 500
    if not ok:
        return {"error": "Case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/finding/<fid>/dismiss", methods=["POST"])
def case_dismiss_finding(did: str, fid: str):
    store = get_store()
    ok    = store.dismiss_finding(did, fid)
    if not ok:
        return {"error": "Case not found"}, 404
    case = store.get(did)
    return {"dismissed": case.get("dismissed_findings", [])}


@app.route("/cases/<did>/finding/<fid>", methods=["DELETE"])
def case_delete_finding(did: str, fid: str):
    store = get_store()
    ok    = store.delete_finding(did, fid)
    if not ok:
        return {"error": "Finding or case not found"}, 404
    return {"ok": True}


@app.route("/cases/<did>/link", methods=["DELETE"])
def case_remove_link(did: str):
    store   = get_store()
    data    = request.get_json(silent=True) or {}
    from_id = data.get("from", "").strip()
    to_id   = data.get("to", "").strip()
    if not from_id or not to_id:
        return {"error": "Missing from/to"}, 400
    links = store.remove_link(did, from_id, to_id)
    if links is None:
        return {"error": "Case not found"}, 404
    return {"links": links}


@app.route("/cases/<did>/link", methods=["POST"])
def case_add_link(did: str):
    store   = get_store()
    data    = request.get_json(silent=True) or {}
    from_id = data.get("from", "").strip()
    to_id   = data.get("to", "").strip()
    if not from_id or not to_id:
        return {"error": "Missing from/to"}, 400
    links = store.add_link(did, from_id, to_id,
                           link_type=data.get("type", "manual"),
                           label=data.get("label", "linked"))
    if links is None:
        return {"error": "Case not found"}, 404
    return {"links": links}


@app.route("/cases/<did>/investigate", methods=["POST"])
def case_investigate(did: str):
    """Full re-run investigation with all current facts."""
    store = get_store()
    if store.get(did) is None:
        return {"error": "Case not found"}, 404
    inv_id = start_case_investigation(did, None)
    return {"inv_id": inv_id}


@app.route("/cases/<did>/stream/<inv_id>")
def case_stream(did: str, inv_id: str):
    """SSE stream for a case investigation."""
    inv = get_case_investigation(inv_id)

    if not inv:
        def _empty():
            yield f"data: {json.dumps({'type': 'error', 'text': 'Investigation not found'})}\n\n"
        return Response(_empty(), mimetype="text/event-stream")

    def generate():
        for event in inv.stream_events(start_idx=0):
            if event["type"] == "ping":
                yield ": ping\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/cases/<did>/data")
def case_data(did: str):
    """Return the current case JSON (used by JS after investigation completes)."""
    store = get_store()
    case  = store.get(did)
    if not case:
        return {"error": "Case not found"}, 404
    return Response(
        json.dumps(case, ensure_ascii=False, default=str),
        mimetype="application/json",
    )


@app.route("/cases/<did>/map")
def case_map(did: str):
    """Geotime map — plots the case's 'geotime' sightings (location + time)."""
    store = get_store()
    case  = store.get(did)
    if not case:
        return redirect(url_for("cases_list"))
    points = []
    for f in case.get("facts", {}).values():
        if f.get("type") != "geotime":
            continue
        v = f.get("value") or {}
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                continue
        points.append({
            "id": f.get("id"), "location": v.get("location", ""), "when": v.get("when", ""),
            "note": v.get("note", ""), "lat": v.get("lat"), "lon": v.get("lon"),
            "display": v.get("display", ""), "added_at": f.get("added_at", ""),
            "seq": v.get("seq"),
        })
    return render_template("map.html", case=case,
                           points_json=json.dumps(points, ensure_ascii=False, default=str))


@app.route("/cases/<did>/geotime", methods=["POST"])
def case_add_geotime(did: str):
    """Add a geotime sighting to a case from the map UI. Body: {location, when, note, near}."""
    body = request.get_json(force=True, silent=True) or {}
    from skills.core.watson_tools import _exec_add_geotime
    res = _exec_add_geotime(
        location=(body.get("location") or "").strip(),
        when=(body.get("when") or "").strip(),
        note=(body.get("note") or "").strip(),
        near=(body.get("near") or "").strip(),
        lat=body.get("lat"), lon=body.get("lon"),
        case_id=did,
    )
    if res.get("error"):
        return {"ok": False, "error": res["error"]}, 400
    return {"ok": True, "point": res.get("point", {})}


@app.route("/cases/<did>/geotime/<fid>", methods=["POST"])
def case_update_geotime(did: str, fid: str):
    """Edit or move a geotime sighting. Body: any of {location, when, note, lat, lon, near}."""
    body  = request.get_json(force=True, silent=True) or {}
    store = get_store()
    case  = store.get(did)
    if not case or fid not in case.get("facts", {}):
        return {"ok": False, "error": "Sighting not found"}, 404
    fact = case["facts"][fid]
    if fact.get("type") != "geotime":
        return {"ok": False, "error": "Not a geotime fact"}, 400
    val = dict(fact.get("value") or {})
    from skills.core.watson_tools import _geocode, _reverse_geocode

    moved = ("lat" in body and body.get("lat") is not None and body.get("lon") is not None)
    if moved:
        try:
            val["lat"], val["lon"] = float(body["lat"]), float(body["lon"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid coordinates"}, 400
        disp = _reverse_geocode(val["lat"], val["lon"])
        if disp:
            val["display"] = disp
            # Update the shown place to the new spot (first components of the address),
            # unless the caller also explicitly set a location this request.
            if "location" not in body:
                val["location"] = ", ".join(disp.split(",")[:2]).strip()
        val["geocoded"] = True
    if "when" in body:
        val["when"] = (body.get("when") or "").strip()
    if "note" in body:
        val["note"] = (body.get("note") or "").strip()
    if "location" in body:
        newloc = (body.get("location") or "").strip()
        # Re-geocode only if the place text changed and we weren't given coords
        if newloc and newloc != val.get("location") and not moved:
            g = _geocode(newloc, near=(body.get("near") or "").strip())
            if g:
                val.update(lat=g["lat"], lon=g["lon"], display=g["display"], geocoded=True)
        val["location"] = newloc

    store.update_fact_value(did, fid, val)
    return {"ok": True, "point": {**val, "id": fid}}


@app.route("/cases/<did>/geotime/reorder", methods=["POST"])
def case_reorder_geotime(did: str):
    """Set the manual chronological order of geotime pins. Body: {order: [factId,…]}."""
    body  = request.get_json(force=True, silent=True) or {}
    order = body.get("order") or []
    store = get_store()
    case  = store.get(did)
    if not case:
        return {"ok": False, "error": "Case not found"}, 404
    for i, fid in enumerate(order):
        fact = case.get("facts", {}).get(fid)
        if fact and fact.get("type") == "geotime":
            val = dict(fact.get("value") or {})
            val["seq"] = i
            store.update_fact_value(did, fid, val)
    return {"ok": True}


@app.route("/cases/<did>/geotime/<fid>", methods=["DELETE"])
def case_delete_geotime(did: str, fid: str):
    """Delete a geotime sighting."""
    ok = get_store().remove_fact(did, fid)
    return ({"ok": True} if ok else ({"ok": False, "error": "Not found"}, 404))


@app.route("/cases/<did>/geotime/photo", methods=["POST"])
def case_geotime_photo(did: str):
    """Drop a photo → extract EXIF GPS + date → add a geotime pin."""
    f = request.files.get("photo")
    if not f or not f.filename:
        return {"ok": False, "error": "No photo uploaded."}, 400
    from skills.core.watson_tools import _exif_geotime, _exec_add_geotime
    exif = _exif_geotime(f.read())
    if not exif:
        return {"ok": False, "error": "No EXIF GPS/date in this photo (often stripped by messaging apps/screenshots)."}, 422
    if exif.get("lat") is None:
        return {"ok": False, "error": f"Photo has a date ({exif.get('when','?')}) but no GPS coordinates.",
                "when": exif.get("when", "")}, 422
    note = f"From photo: {f.filename}"
    res = _exec_add_geotime(lat=exif["lat"], lon=exif["lon"], when=exif.get("when", ""),
                            note=note, case_id=did)
    if res.get("error"):
        return {"ok": False, "error": res["error"]}, 400
    return {"ok": True, "point": res.get("point", {})}


@app.route("/cases/<did>/graph-layout", methods=["POST"])
def case_save_graph_layout(did: str):
    """Persist node positions + viewport from the vis-network whiteboard."""
    body      = request.get_json(force=True, silent=True) or {}
    positions = body.get("positions", {})
    viewport  = body.get("viewport", {})
    store     = get_store()
    ok        = store.save_graph_layout(did, positions, viewport)
    return {"ok": ok}


# ── Profile validation + enrichment ───────────────────────────

@app.route("/api/case/add_fact", methods=["POST"])
def api_case_add_fact():
    """Add a typed fact (email/phone/city/note/…) to a case from the investigation page.

    Body: {case_id, fact_type, value}. Reuses the Watson add_fact executor
    (validation, French synonyms, dedup)."""
    body      = request.get_json(force=True, silent=True) or {}
    case_id   = (body.get("case_id") or "").strip()
    fact_type = (body.get("fact_type") or "note").strip()
    value     = body.get("value", "")
    if not case_id:
        return {"ok": False, "error": "No case linked — click «Save as Case» first."}, 400
    if not value:
        return {"ok": False, "error": "Empty value."}, 400
    from skills.core.watson_tools import _exec_add_fact
    res = _exec_add_fact(fact_type=fact_type, value=value, case_id=case_id)
    if res.get("error"):
        return {"ok": False, "error": res["error"]}, 400
    return {"ok": True, "status": res.get("status", "ok"),
            "fact_type": res.get("fact_type"), "value": res.get("value")}


@app.route("/api/validate_profile", methods=["POST"])
def api_validate_profile():
    """
    Validate a social media profile found during investigation.

    Body (JSON):
        platform   str   "instagram" | "tiktok" | "linkedin" | ...
        username   str   profile username (without @)
        url        str   profile URL
        display_name str (optional) already-known display name
        relevance  int   (optional) relevance score from detection
        case_id    str   (optional) case to add the finding to
        link_to    str   (optional) fact id to link the finding to (e.g. the name node)

    Returns:
        { ok, enriched, finding_id? }
    """
    from skills.social_media.enrich import enrich_profile

    body       = request.get_json(force=True, silent=True) or {}
    platform   = (body.get("platform") or "").strip().lower()
    username   = (body.get("username") or "").lstrip("@").strip()
    url        = body.get("url", "")
    display    = body.get("display_name", "")
    relevance  = body.get("relevance")
    case_id    = body.get("case_id", "").strip()
    link_to    = body.get("link_to", "").strip()

    if not platform or not username:
        return {"ok": False, "error": "platform and username are required"}, 400

    # ── Enrich ──────────────────────────────────────────────────
    try:
        enriched = enrich_profile(platform, username, url)
    except Exception as exc:
        enriched = {"platform": platform, "username": username, "url": url,
                    "source": "error", "note": str(exc)}

    # Merge any data already known from the detection phase
    if display and not enriched.get("display_name"):
        enriched["display_name"] = display
    if relevance is not None:
        enriched["relevance"] = relevance

    # ── Face comparison (when a reference photo was uploaded) ────
    _face_result: dict | None = None
    _ref_pic = (session.get("target") or {}).get("picture", "")
    _profile_pic_url = enriched.get("profile_pic", "")
    if _ref_pic and _profile_pic_url and os.path.isfile(_ref_pic):
        try:
            from skills.face.face_match import encode_face, compare_face_url
            from skills.face.face_match import is_available as _face_available
            if _face_available():
                _ref_enc = encode_face(_ref_pic)
                if _ref_enc:
                    _face_result = compare_face_url(_ref_enc, _profile_pic_url)
                    enriched["face_match"] = _face_result
        except Exception:
            pass

    # ── Inject into case if case_id provided ────────────────────
    finding_id = None
    if case_id:
        store = get_store()
        case  = store.get(case_id)
        if case:
            import hashlib, datetime

            fid = "fnd_" + hashlib.md5(
                f"social_profile:{platform}:{username}".encode()
            ).hexdigest()[:8]

            finding = {
                "id":           fid,
                "type":         "social_profile",
                "platform":     platform,
                "username":     username,
                "url":          enriched.get("url", url),
                "display_name": enriched.get("display_name", display),
                "bio":          enriched.get("bio", ""),
                "followers":    enriched.get("followers"),
                "following":    enriched.get("following"),
                "is_verified":  enriched.get("is_verified"),
                "profile_pic":  enriched.get("profile_pic", ""),
                "face_match":   _face_result if (_face_result and _face_result.get("matched")) else None,
                "relevance":    relevance,
                "validated_by": "investigator",
                "validated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "source":       enriched.get("source", ""),
                "note":         enriched.get("note", ""),
            }
            # Remove None/empty fields
            finding = {k: v for k, v in finding.items() if v not in (None, "")}

            # Build link to a fact node (name node if link_to not specified)
            links = []
            if link_to:
                anchor = link_to
            else:
                # Find the first name fact in the case
                anchor = next(
                    (fid2 for fid2, f in case.get("facts", {}).items()
                     if f.get("type") == "name"),
                    None,
                )
            if anchor:
                _base_conf = round((relevance or 5) / 10, 1)
                _face_boost = 0.0
                if _face_result and _face_result.get("matched"):
                    _d = _face_result.get("distance", 1.0)
                    _face_boost = 0.4 if _d < 0.35 else (0.3 if _d < 0.45 else 0.2)
                links.append({
                    "from":       anchor,
                    "to":         fid,
                    "type":       "social_profile",
                    "confidence": min(1.0, round(_base_conf + _face_boost, 2)),
                    **({"face_boost": round(_face_boost, 2)} if _face_boost else {}),
                })

            try:
                store.update_findings(case_id, {fid: finding}, links)
                finding_id = fid
            except Exception:
                pass

    return {
        "ok":        True,
        "enriched":  enriched,
        "finding_id": finding_id,
    }


@app.route("/investigation/report")
def investigation_report():
    """Phase 3 intelligence report from the current (or most recent) investigation."""
    inv_id = session.get("inv_id")
    target = session.get("target", {})
    inv    = get_investigation(inv_id) if inv_id else None
    report = inv.report if (inv and inv.report) else {}

    if not report:
        # Fall back to most recent history file
        report, hist_target = _latest_history_report()
        target = hist_target or target

    if not report:
        return redirect(url_for("investigation"))

    return render_template(
        "report.html",
        report_json=json.dumps(report, ensure_ascii=False, default=str),
        target_json=json.dumps(target, ensure_ascii=False),
    )


@app.route("/history/<filename>/report")
def history_report(filename: str):
    """Phase 3 intelligence report from a saved history file."""
    if not filename.endswith(".json") or "/" in filename or "\\" in filename:
        return {"error": "invalid filename"}, 400
    path = os.path.join(_HISTORY_DIR, filename)
    if not os.path.isfile(path):
        return {"error": "not found"}, 404
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    report = data.get("report", {})
    target = data.get("target", {})

    # Run rule-based agents if pre_analysis not stored
    if report and "pre_analysis" not in report:
        try:
            from skills.core.agents import run_all_agents
            report["pre_analysis"] = run_all_agents(report)
        except Exception:
            pass

    return render_template(
        "report.html",
        report_json=json.dumps(report, ensure_ascii=False, default=str),
        target_json=json.dumps(target, ensure_ascii=False),
    )


@app.route("/api/llm-status")
def api_llm_status():
    """Return current LLM warmup state for the UI indicator."""
    return {"status": _llm_warmup_state, "backend": os.environ.get("LLM_BACKEND", "")}


@app.route("/api/ollama/ping")
def api_ollama_ping():
    """Quick reachability check for Ollama — used by the Watson UI to re-poll after a restart."""
    host = os.environ.get("OLLAMA_API_BASE", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    alive = _quick_llm_ping(os.environ.get("LLM_BACKEND", "ollama/"), timeout=4)
    if alive:
        global _llm_warmup_state
        _llm_warmup_state = "ready"
    return {"alive": alive, "host": host, "status": _llm_warmup_state}


@app.route("/api/ollama/restart", methods=["POST"])
def api_ollama_restart():
    """
    Attempt to start (or restart) the Ollama server process.
    Runs `ollama serve` in the background and returns immediately.
    Polls for up to 10s to see if it comes up.
    """
    import subprocess

    host = os.environ.get("OLLAMA_API_BASE", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))

    # If already reachable, just update state and return
    if _quick_llm_ping("ollama/", timeout=3):
        global _llm_warmup_state
        _llm_warmup_state = "ready"
        return {"ok": True, "message": "Ollama is already running.", "status": "ready"}

    # Try to start `ollama serve` in the background
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "message": "ollama command not found. Make sure Ollama is installed and in PATH.",
            "status": "unavailable",
        }, 404
    except Exception as exc:
        return {"ok": False, "message": f"Could not start Ollama: {exc}", "status": "unavailable"}, 500

    _llm_warmup_state = "warming"

    # Poll for up to 12s in a background thread so the response is immediate
    def _wait_for_ollama():
        global _llm_warmup_state
        import time as _t, requests as _req
        for _ in range(12):
            _t.sleep(1)
            try:
                r = _req.get(f"{host}/api/tags", timeout=2)
                if r.status_code == 200:
                    _llm_warmup_state = "ready"
                    _ollama_prewarm()  # reload model into memory
                    return
            except Exception:
                pass
        _llm_warmup_state = "unavailable"

    import threading as _th
    _th.Thread(target=_wait_for_ollama, daemon=True, name="ollama-restart-poll").start()

    return {
        "ok": True,
        "message": "Starting Ollama… checking status every second.",
        "status": "warming",
    }


def _watson_llm_error(exc: Exception, kind: str = "generic") -> dict:
    """Return a human-friendly Watson error payload instead of the raw exception string."""
    backend = _watson_backend()
    is_groq = backend.startswith("groq/")
    # Model was removed / renamed by the provider (e.g. Groq deprecating Llama-3.x)
    exc_low = str(exc).lower()
    if "model_not_found" in exc_low or "does not exist" in exc_low or "notfound" in type(exc).__name__.lower():
        msg = f"The model '{backend}' is no longer available"
        if is_groq:
            msg += " — Groq deprecated the Llama-3.x models. Switch to groq/openai/gpt-oss-120b"
        return {"error": msg + " in Settings (/config)."}
    if kind == "timeout":
        if is_groq:
            return {"error": "Raphael timed out — Groq API did not respond. Check your GROQ_API_KEY and network."}
        return {
            "error": (
                "Raphael timed out waiting for the AI model. "
                "Ollama may still be loading the model (this can take 1-2 min on first run). "
                "Try again in a moment, or check that Ollama is running."
            )
        }
    if kind == "connection":
        if is_groq:
            exc_s = str(exc).lower()
            if "api_key" in exc_s or "401" in exc_s or "authentication" in exc_s:
                return {"error": "Groq API key invalid or missing — set GROQ_API_KEY in your .env file."}
            return {"error": "Raphael can't reach Groq API — check your internet connection and GROQ_API_KEY."}
        return {
            "error": (
                "Raphael can't reach the AI model. "
                "Make sure Ollama is running (`ollama serve`) and the model is pulled."
            )
        }
    # Surface Groq auth errors from generic exceptions too
    if is_groq:
        exc_s = str(exc).lower()
        if "api_key" in exc_s or "401" in exc_s or "authentication" in exc_s:
            return {"error": "Groq API key invalid or missing — set GROQ_API_KEY in your .env file."}
    return {"error": f"Raphael AI error: {exc}"}


def _watson_backend() -> str:
    """Return the LLM backend to use for Watson — WATSON_LLM_BACKEND if set, else LLM_BACKEND."""
    return (
        os.environ.get("WATSON_LLM_BACKEND", "").strip()
        or os.environ.get("LLM_BACKEND", "").strip()
    )


def _watson_build_context(inv_id: str) -> tuple[dict, str, str, dict]:
    """
    Load the investigation report and build Watson's system prompt + context.
    Returns (ctx_dict, target_name, system_content, report).
    """
    report: dict = {}
    inv = get_investigation(inv_id) if inv_id else None
    if inv and inv.report:
        report = inv.report
    else:
        report, _ = _latest_history_report()

    try:
        from skills.core.evidence import build_context_summary
        ctx = build_context_summary(report)
    except Exception:
        ctx = {"target": report.get("target", {})}

    tgt = ctx.get("target", {})
    target_name = f"{tgt.get('firstname', '')} {tgt.get('lastname', '')}".strip() or "the target"

    try:
        from skills.core.osint_knowledge import get_watson_system_prompt
        system_content = (
            get_watson_system_prompt(target_name=target_name, investigation_context=ctx)
            + "\n\n## INVESTIGATION DATA (already collected)\n"
            + json.dumps(ctx, ensure_ascii=False, indent=2)
            + "\n\nAnswer in plain, clear prose. If you use a tool, explain what you found. "
              "Keep answers focused and cite your sources."
        )
    except Exception:
        system_content = (
            f"You are Raphael, an expert OSINT investigation assistant analysing {target_name}.\n"
            f"Always cite sources. Distinguish CONFIRMED/PROBABLE/LOW CONFIDENCE findings.\n"
            f"Investigation data:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
        )

    return ctx, target_name, system_content, report


def _load_watson_report(inv_id: str) -> dict:
    """Load the live investigation report, else the most recent history one."""
    inv = get_investigation(inv_id) if inv_id else None
    if inv and inv.report:
        return inv.report
    report, _ = _latest_history_report()
    return report


def _watson_route(question: str, inv_id: str, case_id: str) -> dict | None:
    """Run the zero-LLM intent router, returning its raw result dict or None."""
    try:
        from skills.core.watson_intent import route as _intent_route
    except Exception:
        return None
    report = _load_watson_report(inv_id)
    try:
        return _intent_route(question, report=report, case_id=case_id or None)
    except Exception:
        return None


def _watson_intent_response(question: str, inv_id: str, case_id: str):
    """
    Try the zero-LLM intent router. Returns a Flask SSE Response when an intent
    matched, else None (so the caller can fall through / show a help message).
    """
    result = _watson_route(question, inv_id, case_id)
    if not result:
        return None

    tools = result.get("tools_used", [])
    answer = result.get("answer", "")

    def _sse():
        if tools:
            yield f"data: {json.dumps({'type': 'tools', 'tools_used': tools})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'tools_used': tools, 'engine': 'deterministic'})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(_sse(), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Watson JSON-plan agent (robust alternative to native tool-calling) ────────
# gpt-oss / Groq native function-calling can crash mid-stream (tool_use_failed),
# so instead of the `tools=` API we ask the model for a JSON plan of actions via
# response_format=json_object (rock solid), execute them ourselves, then have the
# model synthesise a final answer from the results. This is what makes Watson a
# real assistant: it both ACTS (mutations on the case/graph) and INVESTIGATES.

_WATSON_ACTION_CATALOG = """\
MUTATIONS (persist to the case / graph — use when the user asks to add/save/record something):
  add_fact(fact_type, value)      Add a TYPED fact. USE THIS for a found email/phone/city/name/employer.
                                  fact_type must be one of: email, phone, city, name, alias, birth_year, employer.
                                  e.g. found email → add_fact(fact_type="email", value="x@gmail.com");
                                  'works at GLS' → add_fact(fact_type="employer", value="GLS").
  add_keyword(keyword)            Add a keyword/search term (or several, comma-separated).
  add_geotime(location, when, note, near)  A SIGHTING: the person was at <location> at <when>.
                                  USE THIS whenever the user reports where/when the target was seen
                                  (e.g. 'toto était au Bar X à 17h' → location="Bar X", when="17h").
                                  Pass near=<city> if a city is known, to geocode accurately. Places a
                                  pin on the case map.
  add_note(text)                  Add a FREE-TEXT note only when no typed fact fits.
  record_to_case(platform, username)  Save a found social profile (with its platform).
  rerun_email()                   Regenerate email candidates from current keywords.
INVESTIGATION (gather data — use when the user asks to check/verify/look up something):
  web_search(query)               Search the web (supports site:, "exact", etc.).
  sherlock_check(username)        Check a username across platforms.
  enrich_profile(platform, username)  Pull bio/followers/links from a profile.
  email_osint(email)              SMTP + HIBP + GHunt + SERP on an email.
  name_search(firstname, lastname, city)  Web-search the name → LinkedIn (employer/school/location), GitHub, profiles.
  leak_search(query, query_type)  Breach/leak DBs (Dehashed/LeakCheck/IntelX) → leaked emails,
                                  passwords, phones, addresses for an email/username/phone/name.
  geo_imagery(location)           Street View at a spot + geotagged photos nearby (verify a place visually).
  messaging_by_number(phone)      WhatsApp/Signal/Viber/Telegram deep-links for a phone number.
  pivot_handle(handle)            DEPTH-FIRST on a strong username → real profile pages + GitHub identity (name/location/Twitter).
  telegram_lookup(username)       Public Telegram profile (name/bio/photo/subs) for a username.
  death_records(firstname, lastname, birth_year)  French INSEE death file — is the person deceased?
  phone_lookup(phone)             Carrier/region/linked accounts for a phone.
  web_archive(url)                Wayback first/last snapshot of a URL.
  whois_lookup(domain)            Registrar/dates/org for a domain.
  instagram_lookup(username)      Obfuscated email/phone hints for an IG account.
  reverse_image(image_url)        Reverse-search a photo URL (find where it appears, confirm identity)."""

_WATSON_MUTATIONS = {"add_fact", "add_geotime", "add_keyword", "add_note", "record_to_case", "rerun_email"}
_WATSON_INVESTIGATE = {"web_search", "sherlock_check", "enrich_profile", "email_osint",
                       "phone_lookup", "web_archive", "whois_lookup", "instagram_lookup",
                       "validate_email_batch", "reverse_image", "leak_search", "geo_imagery", "name_search", "telegram_lookup", "death_records", "messaging_by_number", "pivot_handle"}


_AGENT_TOOL_LABELS = {
    "web_search": "🌐 Searching the web…", "sherlock_check": "🕵️ Checking username across platforms…",
    "enrich_profile": "🔍 Enriching profile…", "email_osint": "📧 Investigating email (SMTP · HIBP · GHunt)…",
    "phone_lookup": "📞 Looking up phone…", "web_archive": "📁 Checking web archive…",
    "whois_lookup": "🌍 Running WHOIS…", "instagram_lookup": "📷 Instagram lookup…",
    "reverse_image": "🔍 Reverse-searching the image…",
    "name_search": "🔎 Searching the name (LinkedIn/GitHub)…",
    "leak_search": "🕳️ Searching breach/leak databases…",
    "geo_imagery": "🛰️ Fetching Street View & nearby photos…",
    "telegram_lookup": "✈️ Checking Telegram…",
    "messaging_by_number": "💬 Building messaging-app links…",
    "pivot_handle": "🔎 Pivoting on the handle (web + GitHub)…",
    "death_records": "⚰️ Searching French death records…",
    "validate_email_batch": "✉️ Validating emails…",
    "add_fact": "➕ Adding to case…", "add_keyword": "🔑 Adding keyword…", "add_note": "📝 Adding note…",
    "add_geotime": "🗺️ Placing sighting on the map…",
    "record_to_case": "💾 Saving profile…", "rerun_email": "✉️ Regenerating emails…",
}


def _watson_agent_stream(question, system_content, history, backend, timeout,
                         llm_completion, inv_id="", case_id=""):
    """
    Plan → execute → synthesise, as a GENERATOR yielding event dicts so the
    endpoint can stream progress (keeps slow tools like email_osint from
    dropping the connection) and tell the UI when the case/graph changed.

    Yields: {"kind":"fail"} | {"kind":"tools","tools_used":[…]}
          | {"kind":"progress","text":…}
          | {"kind":"final","text":…,"tools_used":[…],"case_dirty":bool}
    """
    from skills.core.watson_tools import execute_tool

    plan_system = (
        system_content
        + "\n\n## AVAILABLE ACTIONS\n" + _WATSON_ACTION_CATALOG
        + "\n\n## HOW TO RESPOND\n"
          "Decide what the user wants. If they ask you to ADD/SAVE something, emit the matching "
          "mutation action(s) — use add_fact with the right fact_type for an email/phone/city/name, "
          "add_keyword for search terms, add_note only for free text. If they ask you to "
          "CHECK/VERIFY/look up something or want a briefing, emit investigation action(s). "
          "If it's a plain question you can answer from the data above, emit no actions.\n"
          "IMPORTANT for web_search/sherlock/etc.: build the query from the ACTUAL investigation "
          "data (the target's real name, aliases, cities, keywords shown above) — NEVER from the "
          "user's sentence words. E.g. for 'cherche le nom avec les villes' use the target's full "
          "name + those cities (e.g. '\"Nathan Dupont\" Angers Rennes'), not words like 'peux-tu'.\n"
          "Respond ONLY with JSON:\n"
          '{"actions":[{"tool":"<name>","params":{...}}],"reply":"<short natural-language reply; '
          'for a plain question put the full answer here>"}'
    )
    messages = [{"role": "system", "content": plan_system}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn.get("content", "")})
    messages.append({"role": "user", "content": question})

    def _json_call(msgs, max_tokens=700):
        kwargs = {"model": backend, "messages": msgs, "max_tokens": max_tokens, "timeout": timeout}
        if not backend.startswith("ollama/"):
            kwargs["response_format"] = {"type": "json_object"}
        resp = llm_completion(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
        raw = _re_global.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Model added prose around the JSON — extract the first {...} block
            m = _re_global.search(r"\{.*\}", raw, _re_global.S)
            if m:
                return json.loads(m.group(0))
            raise

    # ── Phase 1: plan ────────────────────────────────────────────
    # gpt-oss is probabilistic — a bad-JSON reply usually parses on a retry.
    plan = None
    for _attempt in range(2):
        try:
            plan = _json_call(messages, max_tokens=600)
            break
        except Exception:
            continue
    if plan is None:
        yield {"kind": "fail"}
        return

    actions = plan.get("actions") or []
    reply   = (plan.get("reply") or "").strip()
    if not isinstance(actions, list):
        actions = []

    valid = [a for a in actions[:6] if isinstance(a, dict)
             and a.get("tool") in (_WATSON_MUTATIONS | _WATSON_INVESTIGATE)]
    if valid:
        yield {"kind": "tools",
               "tools_used": [{"tool": a["tool"],
                               "params": a.get("params") if isinstance(a.get("params"), dict) else {}}
                              for a in valid]}

    # ── Phase 2: execute (streaming progress) ────────────────────
    actions_taken, results, did_investigate, case_dirty = [], [], False, False
    for act in valid:
        name = act["tool"]
        params = act.get("params") if isinstance(act.get("params"), dict) else {}
        yield {"kind": "progress", "text": _AGENT_TOOL_LABELS.get(name, f"Running {name}…") + "\n"}
        res = execute_tool(name, params, case_id=case_id or None)
        actions_taken.append({"tool": name, "params": params})
        results.append({"tool": name, "params": params, "result": res})
        if name in _WATSON_INVESTIGATE:
            did_investigate = True
        if name in _WATSON_MUTATIONS and not res.get("error") and res.get("status") != "not_linked":
            case_dirty = True

    # ── Phase 3: answer ──────────────────────────────────────────
    if not results:
        yield {"kind": "final", "text": reply or "…", "tools_used": actions_taken, "case_dirty": case_dirty}
        return

    if did_investigate:
        synth_msgs = [
            {"role": "system", "content": system_content
                + "\n\nYou just ran tools for the analyst. Write a clear, concise briefing "
                  "in the user's language: what you checked, what you found, and what it means. "
                  "Cite which tool/source each finding came from. Be honest about negatives."},
            {"role": "user", "content": f"Original request: {question}\n\n"
                f"Tool results (JSON):\n{json.dumps(results, ensure_ascii=False, default=str)[:6000]}"},
        ]
        try:
            fr = llm_completion(model=backend, messages=synth_msgs, max_tokens=900, timeout=timeout)
            final = (fr.choices[0].message.content or "").strip()
        except Exception:
            final = reply or "Done — see results above."
        yield {"kind": "final", "text": final, "tools_used": actions_taken, "case_dirty": case_dirty}
        return

    # Pure mutations → confirm what was persisted
    lines = []
    for r in results:
        res = r["result"]
        if res.get("error"):
            lines.append(f"⚠ {r['tool']}: {res['error']}")
        elif res.get("status") == "not_linked":
            lines.append(f"⚠ {res.get('note','No case linked — click «Save as Case» first.')}")
        elif r["tool"] == "add_fact":
            if res.get("status") == "already_present":
                lines.append(f"• {res.get('fact_type')} already in case: {res.get('value')}")
            else:
                v = res.get("value"); v = f"{v.get('firstname','')} {v.get('lastname','')}".strip() if isinstance(v, dict) else v
                lines.append(f"✓ Added {res.get('fact_type','fact')}: {v}")
        elif r["tool"] == "add_keyword":
            a = res.get("added", []); lines.append(f"✓ Added keyword(s): {', '.join(a)}" if a else "Keyword(s) already present.")
        elif r["tool"] == "add_geotime":
            p = res.get("point", {})
            geo = "📍 pinned" if p.get("geocoded") else "⚠ not geocoded"
            lines.append(f"✓ Sighting saved ({geo}): {p.get('location','?')}"
                         + (f" @ {p.get('when')}" if p.get('when') else ""))
        elif r["tool"] == "add_note":
            lines.append(f"✓ Note added: {res.get('added','')[:80]}")
        elif r["tool"] == "record_to_case":
            lines.append(f"✓ Saved {r['params'].get('platform','')} @{r['params'].get('username','')}")
        elif r["tool"] == "rerun_email":
            lines.append(f"✓ Regenerated {res.get('total_candidates',0)} email candidates.")
        else:
            lines.append(f"✓ {r['tool']} done.")
    yield {"kind": "final",
           "text": (reply + ("\n\n" if reply else "") + "\n".join(lines)).strip(),
           "tools_used": actions_taken, "case_dirty": case_dirty}


def _watson_agent_run(question, system_content, history, backend, timeout,
                      llm_completion, inv_id="", case_id=""):
    """Sync wrapper over _watson_agent_stream. Returns (final_text|None, actions)."""
    final_text, tools = None, []
    for ev in _watson_agent_stream(question, system_content, history, backend, timeout,
                                   llm_completion, inv_id=inv_id, case_id=case_id):
        if ev["kind"] == "fail":
            return None, []
        if ev["kind"] == "final":
            final_text, tools = ev["text"], ev.get("tools_used", [])
    return final_text, tools


@app.route("/api/investigation/chat", methods=["POST"])
def api_investigation_chat():
    """
    Watson conversational endpoint.

    Body (JSON):
        inv_id   str    Investigation ID
        question str    The analyst's question
        history  list   [{role, content}] prior turns
        stream   bool   If true, returns text/event-stream SSE (default false)

    Returns (non-stream): { answer, sources, confidence, followup_questions, tools_used[] }
    Returns (stream):     SSE: data: {type, content|error|tools_used}
    """

    body      = request.get_json(force=True, silent=True) or {}
    question  = (body.get("question") or "").strip()
    inv_id    = (body.get("inv_id") or session.get("inv_id") or "").strip()
    case_id   = (body.get("case_id") or "").strip()
    history   = body.get("history", [])
    do_stream = bool(body.get("stream", True))  # default to streaming

    if not question:
        return {"error": "question is required"}, 400

    # ── Instant actions — no LLM needed ─────────────────────────
    instant = _instant_record_to_case(question, inv_id, case_id=case_id)
    if instant:
        platform  = instant["platform"].capitalize()
        username  = instant["username"]
        url       = instant.get("url", "")
        added     = instant.get("added_to_case", False)
        case_err  = instant.get("case_error", "")
        msg       = f"Recorded {platform} @{username}"
        if url:   msg += f" — {url}"
        if added:
            msg += " ✓"
        elif case_err:
            msg += f"  ⚠ {case_err}"
        else:
            msg += "  (no case linked — click «Save as Case» first)"
        tool_info = [{"tool": "record_to_case",
                      "params": {"platform": instant["platform"], "username": username}}]

        def _instant_sse():
            yield f"data: {json.dumps({'type': 'tools', 'tools_used': tool_info})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done',  'tools_used': tool_info})}\n\n"
            yield "data: [DONE]\n\n"

        return Response(
            _instant_sse(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Instant "add keyword(s)" — runs before the LLM so it always persists
    kw_res = _instant_add_keyword(question, case_id=case_id)
    if kw_res is not None:
        added   = kw_res.get("added", [])
        present = kw_res.get("already_present", [])
        if kw_res.get("status") == "not_linked":
            msg = ("⚠ No case linked yet — click «Save as Case» first, then I can add "
                   f"keyword(s): {', '.join(kw_res.get('requested', []))}.")
        elif kw_res.get("error"):
            msg = f"⚠ {kw_res['error']}"
        else:
            bits = []
            if added:   bits.append(f"Added keyword(s): {', '.join(added)} ✓")
            if present: bits.append(f"already present: {', '.join(present)}")
            msg = " — ".join(bits) if bits else "No new keyword to add."
            if added:
                msg += "\nℹ Re-run the investigation to regenerate emails/usernames with these keywords."
        kw_tool = [{"tool": "add_keyword", "params": {"keyword": ", ".join(kw_res.get("requested", []))}}]

        def _kw_sse():
            yield f"data: {json.dumps({'type': 'tools', 'tools_used': kw_tool})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'tools_used': kw_tool})}\n\n"
            yield "data: [DONE]\n\n"

        return Response(_kw_sse(), content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Instant "re-run email generation" — deterministic, runs before the LLM
    em_res = _instant_rerun_email(question, case_id=case_id)
    if em_res is not None:
        if em_res.get("error"):
            msg = f"⚠ {em_res['error']}"
        else:
            kws = em_res.get("keywords_used", [])
            by_kw = em_res.get("samples_by_keyword", {})
            msg = (f"Regenerated {em_res.get('total_candidates', 0)} email candidate(s) for "
                   f"{em_res.get('name','')} using keywords: {', '.join(kws) or '(none)'}.")
            if by_kw:
                msg += "\n\n**Samples per keyword:**"
                for kw, ex in by_kw.items():
                    msg += f"\n• _{kw}_ → " + ", ".join(ex[:4])
            else:
                msg += "\n\n" + "\n".join(f"• {c}" for c in em_res.get("candidates", [])[:20])
            msg += "\n\nℹ " + em_res.get("note", "")
        em_tool = [{"tool": "rerun_email", "params": {}}]

        def _em_sse():
            yield f"data: {json.dumps({'type': 'tools', 'tools_used': em_tool})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'tools_used': em_tool})}\n\n"
            yield "data: [DONE]\n\n"

        return Response(_em_sse(), content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    backend = _watson_backend()
    if not backend:
        # No LLM at all → deterministic intent router (still useful offline)
        resp = _watson_intent_response(question, inv_id, case_id)
        if resp is not None:
            return resp
        return {"error": ("No LLM configured. Raphael can still summarise the case or run a "
                          "search/lookup — try “résumé”, “cherche <nom>”, or paste an email/phone. "
                          "For free-form chat, add LLM_BACKEND to .env.")}, 503

    try:
        from litellm import completion as llm_completion
    except ImportError:
        return {"error": "LLM library not installed (pip install litellm)."}, 503

    # ── Pre-flight ───────────────────────────────────────────────
    if _llm_warmup_state == "unavailable":
        # LLM down → try the deterministic router before giving up
        resp = _watson_intent_response(question, inv_id, case_id)
        if resp is not None:
            return resp
        return _watson_llm_error(Exception(), kind="connection"), 503
    if _llm_warmup_state == "warming":
        return {"error": "Raphael's AI model is still loading. Try again in a moment."}, 503
    if backend.startswith("ollama/") and _llm_warmup_state not in ("ready",):
        if not _quick_llm_ping(backend, timeout=4):
            model_name = backend[len("ollama/"):]
            # Check if Ollama itself is up (then it's a missing model, not Ollama down)
            import requests as _req
            host = os.environ.get("OLLAMA_HOST",
                                  os.environ.get("OLLAMA_API_BASE", "http://localhost:11434"))
            try:
                alive = _req.get(f"{host}/api/tags", timeout=3).ok
            except Exception:
                alive = False
            if alive:
                return {
                    "error": (
                        f"Model '{model_name}' is not installed in Ollama. "
                        f"Run: ollama pull {model_name}"
                    )
                }, 503
            return _watson_llm_error(Exception(), kind="connection"), 503

    # ── Build context ────────────────────────────────────────────
    try:
        ctx, target_name, system_content, _report = _watson_build_context(inv_id)
    except Exception as exc:
        return {"error": f"Could not load investigation: {exc}"}, 500

    if not ctx.get("target"):
        return {"error": "No investigation data available. Run an investigation first."}, 404

    raw_timeout = os.environ.get("LLM_TIMEOUT", "").strip()
    timeout = int(raw_timeout) if raw_timeout.isdigit() else (120 if backend.startswith("ollama/") else 60)

    # ── Watson agent: plan → execute → answer (robust JSON-plan flow) ──
    if do_stream:
        def _sse(obj):
            return f"data: {json.dumps(obj)}\n\n"

        def generate():
            tools_used, case_dirty, got_final = [], False, False
            # Immediate keepalive so the browser doesn't drop the connection while
            # the (possibly slow) plan call runs before the first real event.
            yield ": keepalive\n\n"
            yield _sse({"type": "ping"})
            try:
                for ev in _watson_agent_stream(question, system_content, history, backend,
                                               timeout, llm_completion, inv_id=inv_id, case_id=case_id):
                    kind = ev.get("kind")
                    if kind == "fail":
                        break
                    if kind == "tools":
                        tools_used = ev["tools_used"]
                        yield _sse({"type": "tools", "tools_used": tools_used})
                    elif kind == "progress":
                        yield _sse({"type": "token", "content": ev["text"]})
                    elif kind == "final":
                        got_final = True
                        case_dirty = ev.get("case_dirty", False)
                        txt = ev.get("text") or "…"
                        for i in range(0, len(txt), 120):
                            yield _sse({"type": "token", "content": txt[i:i+120]})
            except Exception as exc:
                _el = str(exc).lower()
                if "model_not_found" in _el or "does not exist" in _el:
                    yield _sse({"type": "error", "error": _watson_llm_error(exc)["error"]})
                    yield "data: [DONE]\n\n"
                    return
                got_final = False

            if not got_final:
                # plan failed / crashed → deterministic router first
                routed = _watson_route(question, inv_id, case_id)
                if routed and routed.get("answer"):
                    if routed.get("tools_used"):
                        yield _sse({"type": "tools", "tools_used": routed["tools_used"]})
                    yield _sse({"type": "token", "content": routed["answer"]})
                else:
                    # Last resort: a PLAIN LLM answer from context (no JSON plan, no tools —
                    # far less likely to fail than the plan call). Answers things like
                    # "give me the BAC link" straight from the investigation data.
                    answered = False
                    try:
                        pmsgs = [{"role": "system", "content": system_content},
                                 {"role": "user", "content": question}]
                        pr = llm_completion(model=backend, messages=pmsgs,
                                            max_tokens=600, timeout=timeout)
                        txt = (pr.choices[0].message.content or "").strip()
                        if txt:
                            for i in range(0, len(txt), 120):
                                yield _sse({"type": "token", "content": txt[i:i+120]})
                            answered = True
                    except Exception:
                        pass
                    if not answered:
                        yield _sse({"type": "token", "content":
                            "I couldn't process that with the current model — try rephrasing, "
                            "ask for a “résumé”, or a specific action like “ajoute … en keyword” "
                            "or “vérifie …”."})

            yield _sse({"type": "done", "tools_used": tools_used, "case_dirty": case_dirty})
            yield "data: [DONE]\n\n"

        return Response(generate(), content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Non-streaming (legacy)
    final_text, tools_used = None, []
    try:
        final_text, tools_used = _watson_agent_run(
            question, system_content, history, backend, timeout,
            llm_completion, inv_id=inv_id, case_id=case_id)
    except Exception as exc:
        if "model_not_found" in str(exc).lower():
            return _watson_llm_error(exc), 503
        final_text = None
    if final_text is None:
        routed = _watson_route(question, inv_id, case_id)
        final_text = (routed or {}).get("answer") or "I couldn't process that with the current model."
        tools_used = (routed or {}).get("tools_used", [])
    return {"answer": final_text, "sources": [], "confidence": "unknown",
            "followup_questions": [], "tools_used": tools_used}


# ── Ollama pre-warm ────────────────────────────────────────────────────────────

_llm_warmup_state = "idle"   # idle | warming | ready | unavailable


def _ollama_prewarm():
    """
    Load the Ollama model into memory so it's ready when the first request comes in.
    Runs in a background daemon thread — never blocks Flask startup.
    """
    global _llm_warmup_state
    import threading, time, requests as _req

    backend = os.environ.get("LLM_BACKEND", "")
    if not backend.startswith("ollama/"):
        _llm_warmup_state = "ready"
        return

    model = backend[len("ollama/"):]
    host  = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def _warm():
        global _llm_warmup_state
        time.sleep(1)  # Let Flask finish booting first
        _llm_warmup_state = "warming"
        try:
            # Quick reachability check first (5s)
            ping = _req.get(f"{host}/api/tags", timeout=5)
            if ping.status_code != 200:
                _llm_warmup_state = "unavailable"
                return
            # Load the model into memory (keep_alive=-1 = keep forever)
            resp = _req.post(
                f"{host}/api/generate",
                json={"model": model, "prompt": "", "stream": False, "keep_alive": -1},
                timeout=60,  # 60s max for model load — generous but not 300s
            )
            _llm_warmup_state = "ready" if resp.status_code == 200 else "unavailable"
        except Exception:
            _llm_warmup_state = "unavailable"

    t = threading.Thread(target=_warm, daemon=True, name="ollama-prewarm")
    t.start()


# Start prewarm at module load time so it runs whether Flask is launched
# via `flask run`, gunicorn, or `python app.py`.
_ollama_prewarm()

if __name__ == "__main__":
    # use_reloader=True → the server auto-restarts on any code change, so you
    # never run stale code. Harmless for Groq (prewarm is a no-op off Ollama).
    app.run(debug=True, port=5000, threaded=True, use_reloader=True)
