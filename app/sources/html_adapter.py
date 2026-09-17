
"""Generic public HTML adapter.

It extracts only facts explicitly present in the page. It never guesses
missing fields and never bypasses robots/auth/CAPTCHA/rate limits.
"""
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

def extract_public_animal_page(html, source_url):
    soup=BeautifulSoup(html,"html.parser")
    title=(soup.title.get_text(" ",strip=True) if soup.title else "")
    desc=""
    meta=soup.find("meta",attrs={"name":"description"})
    if meta: desc=(meta.get("content") or "").strip()
    images=[]
    for tag in soup.find_all(["meta","img"]):
        u=None
        if tag.name=="meta" and tag.get("property","").lower()=="og:image":
            u=tag.get("content")
        elif tag.name=="img":
            u=tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if u:
            u=urljoin(source_url,u)
            a=urlparse(u); b=urlparse(source_url)
            if a.netloc and a.netloc.lower().lstrip("www.")==b.netloc.lower().lstrip("www."):
                if u not in images: images.append(u)
    return {"title":title,"description":desc,"photos":images[:10],"source_url":source_url}
