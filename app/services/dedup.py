
"""Conservative animal deduplication helpers."""
import re, hashlib

def norm(value):
    return re.sub(r"\s+"," ",str(value or "").strip().lower())

def fingerprint(animal):
    parts=[norm(animal.get(k)) for k in ("name","species","sex","city","shelter")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]

def likely_same(a,b):
    # Conservative: same normalized name plus at least one corroborating field.
    if norm(a.get("name")) != norm(b.get("name")): return False
    corroboration=sum(bool(x) for x in [
        norm(a.get("species")) and norm(a.get("species"))==norm(b.get("species")),
        norm(a.get("sex")) and norm(a.get("sex"))==norm(b.get("sex")),
        norm(a.get("shelter")) and norm(a.get("shelter"))==norm(b.get("shelter")),
    ])
    return corroboration >= 1
