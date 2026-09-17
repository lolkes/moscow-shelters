"""
Safe automatic source discovery for public animal catalogs.
No CAPTCHA/auth/robots/rate-limit bypass.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass(frozen=True)
class SourceCandidate:
    name: str
    url: str
    source_type: str
    enabled: bool = True

DEFAULT_PUBLIC_SOURCES = (
    SourceCandidate("РосПриют — Москва и МО", "https://rospriut.ru/shelters/msk/", "website"),
    SourceCandidate("РосПриют — собаки", "https://rospriut.ru/dogs/", "website"),
    SourceCandidate("РосПриют — кошки", "https://rospriut.ru/cats/", "website"),
    SourceCandidate("Мосприют — каталог", "https://mospriut.ru/catalog", "website"),
)

def is_allowed_public_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False

def discover_sources():
    return [s for s in DEFAULT_PUBLIC_SOURCES if is_allowed_public_url(s.url)]
