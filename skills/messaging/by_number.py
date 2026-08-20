"""
Messaging apps by phone number — deep-links + existence hints, no session needed.

WhatsApp/Signal/Viber profile data (photo, about, last-seen) is only reachable
through a logged-in session (whatsapp-web / Baileys), which PAW doesn't run. What
we CAN do reliably and keyless:
  • normalise the number to E.164,
  • produce the click-to-chat deep-links (wa.me, signal.me, viber) so the
    investigator can open each and see if the account exists + its photo,
  • fold in Telegram-by-number, which PAW already resolves in phone OSINT.

Honest about the limits; the links are the deliverable.
"""
from __future__ import annotations


def run_sync(phone: str, region: str = "FR") -> dict:
    phone = (phone or "").strip()
    if not phone:
        return {"error": "No phone number."}
    e164 = phone
    digits = "".join(c for c in phone if c.isdigit())
    valid = None
    try:
        import phonenumbers
        pn = phonenumbers.parse(phone, region)
        valid = phonenumbers.is_valid_number(pn)
        e164 = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
        digits = e164.lstrip("+")
    except Exception:
        pass

    plus = "+" + digits
    links = {
        "whatsapp": f"https://wa.me/{digits}",
        "signal":   f"https://signal.me/#p/{plus}",
        "viber":    f"viber://chat?number={plus}",
        "telegram": f"https://t.me/{plus}",   # resolves only if the number is public
    }
    return {
        "phone":  phone,
        "e164":   e164,
        "valid":  valid,
        "links":  links,
        "note":   ("Open each link to check if the number has an account and see its "
                   "public photo. Profile photo / last-seen / status require a logged-in "
                   "session and are not fetched automatically."),
    }
