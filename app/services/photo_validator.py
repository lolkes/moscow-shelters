
"""Safe image URL validation. No cross-site substitution."""
from urllib.parse import urlparse

ALLOWED_IMAGE_TYPES={"image/jpeg","image/png","image/webp","image/gif"}

def same_origin(image_url:str, source_url:str)->bool:
    try:
        a=urlparse(image_url); b=urlparse(source_url)
        return a.scheme in {"http","https"} and a.netloc.lower().lstrip("www.") == b.netloc.lower().lstrip("www.")
    except Exception:
        return False

def validate_candidate(image_url:str, source_url:str)->bool:
    return bool(image_url and same_origin(image_url, source_url))
