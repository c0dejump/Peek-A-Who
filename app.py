import hashlib
import json
import os
import sys

from flask import Flask, Response, redirect, render_template, request, session, url_for

sys.path.insert(0, os.path.dirname(__file__))

from paw_agent.engine.runner import start_investigation, get_investigation, _HISTORY_DIR
from paw_agent.config_manager import (
    DEFAULT_MODELS, get_current_config, get_ollama_models, save_config
)
from paw_agent.case_store import CaseStore, get_store
from paw_agent.case_runner import start_case_investigation, get_case_investigation


def _fnd_id(key: str) -> str:
    return f"fnd_{hashlib.md5(key.encode()).hexdigest()[:8]}"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "paw-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


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

    if "picture" in request.files:
        f = request.files["picture"]
        if f and f.filename:
            upload_dir = os.path.join("static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            path = os.path.join(upload_dir, f.filename)
            f.save(path)
            picture = path

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
    }

    # Start investigation immediately in background
    inv_id = start_investigation(target)
    session["target"]      = target
    session["inv_id"]      = inv_id
    session["create_case"] = request.form.get("create_case", "1") == "1"
    return redirect(url_for("investigation"))


# ── Page 2 : Live investigation terminal ──────────────────────

@app.route("/investigation")
def investigation():
    target = session.get("target")
    inv_id = session.get("inv_id")
    if not target or not inv_id:
        return redirect(url_for("home"))

    inv = get_investigation(inv_id)
    inv_done = inv.done if inv else True

    return render_template("investigation.html", target=target,
                           inv_id=inv_id, inv_done=inv_done,
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

    # Instagram profiles — import all, link only when justified
    sm = report.get("social_media", {})
    ig_found = sm.get("instagram", {}).get("found", [])
    for prof in ig_found:
        fnd_id = _fnd_id(f"instagram:{prof['username']}")
        new_findings[fnd_id] = {
            "id":           fnd_id,
            "type":         "social_profile",
            "platform":     "Instagram",
            "username":     prof["username"],
            "display_name": prof.get("display_name", ""),
            "url":          prof.get("url", f"https://www.instagram.com/{prof['username']}/"),
            "relevance":    prof.get("relevance", 0),
            "first_seen":   prof.get("first_seen"),
            "found_at":     "",
        }
        if _username_matches(prof["username"]):
            _link(name_fact_id, fnd_id, "username_match",
                  f"@{prof['username']} matches search term", 0.9)
        elif _name_in_display(prof.get("display_name", "")):
            _link(name_fact_id, fnd_id, "name_match",
                  f"Name in display name '{prof.get('display_name','')}'", 0.8)

    # Other social platforms
    for plat_key, plat_data in sm.get("platforms", {}).items():
        label = plat_data.get("label", plat_key)
        for prof in plat_data.get("found", []):
            fnd_id = _fnd_id(f"{plat_key}:{prof['username']}")
            new_findings[fnd_id] = {
                "id":           fnd_id,
                "type":         "social_profile",
                "platform":     label,
                "username":     prof["username"],
                "display_name": prof.get("display_name", ""),
                "url":          prof.get("url", ""),
                "relevance":    prof.get("relevance", 0),
                "found_at":     "",
            }
            if _username_matches(prof["username"]):
                _link(name_fact_id, fnd_id, "username_match",
                      f"@{prof['username']} matches search term", 0.9)
            elif _name_in_display(prof.get("display_name", "")):
                _link(name_fact_id, fnd_id, "name_match",
                      f"Name in display name", 0.75)

    # Maigret cross-platform — link only when username matches
    mg = sm.get("maigret", {})
    seen_maigret: set = set()
    for site_name, site_info in mg.get("found", {}).items():
        url = site_info.get("url", "")
        if not url:
            continue
        fnd_id = _fnd_id(f"maigret:{site_name}:{url}")
        uname  = site_info.get("username", "")
        seen_maigret.add(fnd_id)
        new_findings[fnd_id] = {
            "id":        fnd_id,
            "type":      "social_profile",
            "platform":  site_name,
            "username":  uname,
            "url":       url,
            "tags":      site_info.get("tags", []),
            "relevance": 5,
            "found_at":  "",
        }
        if _username_matches(uname):
            _link(name_fact_id, fnd_id, "username_match",
                  f"@{uname} found on {site_name}", 0.85)

    # Also import maigret social flat list — link only when username matches
    for entry in mg.get("social", []):
        url  = entry.get("url", "")
        site = entry.get("site", "")
        if not url or not site:
            continue
        fnd_id = _fnd_id(f"maigret:{site}:{url}")
        if fnd_id in seen_maigret:
            continue
        uname = entry.get("username", "")
        new_findings[fnd_id] = {
            "id":        fnd_id,
            "type":      "social_profile",
            "platform":  site,
            "username":  uname,
            "url":       url,
            "relevance": 5,
            "found_at":  "",
        }
        if _username_matches(uname):
            _link(name_fact_id, fnd_id, "username_match",
                  f"@{uname} found on {site}", 0.85)

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

    return {"case_id": did, "redirect": f"/cases/{did}"}


@app.route("/cases/<did>")
def case_detail(did: str):
    store = get_store()
    case  = store.get(did)
    if not case:
        return redirect(url_for("cases_list"))
    return render_template("case.html", case=case)


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


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True, use_reloader=False)
