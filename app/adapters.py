"""
Public shelter catalog adapters.

The project must not depend on one aggregator. These adapters read public,
currently published animal cards from the shelter/municipal sites themselves,
respect robots.txt through app.main.fetch(), and preserve the original URL.
"""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone

YUNA_ROOT = "https://yunacenter.ru"
DORINVEST_ROOT = "https://dorinvest.ru"
DOR_CATALOG = (
    DORINVEST_ROOT
    + "/index.php/activities/priyuty-dlya-beznadzornykh-zhivotnykh/"
      "katalog-zhivotnykh-gotovykh-k-pristrojstvu"
)

def _clean(value, clean_text):
    return clean_text(value or "")

def _same_host(url, root):
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.") == (urlparse(root).hostname or "").lower().lstrip("www.")
    except Exception:
        return False

def _detail_links(html, base_url, pattern):
    out=[]
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I):
        u=urljoin(base_url, href)
        if pattern(u) and u not in out:
            out.append(u)
    return out

def _ensure_shelter(db, name, website, region, city, main):
    name=_clean(name, main.clean_text) or "Неизвестный приют"
    clean=name.lower().replace("приют ", "").strip()
    rows=db.scalars(main.select(main.Shelter).where(main.Shelter.active.is_(True))).all()
    for s in rows:
        sn=(s.name or "").lower().replace("приют ", "").strip()
        if sn == clean or clean in sn or sn in clean:
            if website and not s.website: s.website=website
            if website and not s.source_url: s.source_url=website
            return s
    import hashlib
    sid="external-"+hashlib.sha256((name+"|"+website).encode("utf-8")).hexdigest()[:24]
    s=db.get(main.Shelter,sid)
    if not s:
        s=main.Shelter(
            id=sid,name=name,region=region,city=city,website=website,
            source_url=website,verified=True,active=True,
            source_type="website_catalog",import_enabled=False,status="active"
        )
        db.add(s); db.flush()
    return s

def _parse_yuna_detail(url, html, main):
    title_m=re.search(r"<h1[^>]*>(.*?)</h1>",html,re.I|re.S)
    title=_clean(title_m.group(1) if title_m else "",main.clean_text)
    if not title: return None
    # Yuna pages publish the animal's key facts as short text blocks.
    text=main.clean_text(html)
    age_m=re.search(r"\b(\d+(?:[.,]\d+)?)\s*(год(?:а|ов)?|месяц(?:а|ев)?)\b",text,re.I)
    sex=None
    if re.search(r"\bДевочка\b",text,re.I): sex="female"
    elif re.search(r"\bМальчик\b",text,re.I): sex="male"
    species="cat" if re.search(r"/cats?/|\bкош",url+" "+text,re.I) else "dog"
    item={
        "title":title[:255],
        "description":text[:10000],
        "link":url,
        "photo_urls":main.extract_page_images(url,html),
        "species_hint":species,
    }
    if age_m:
        item["description"] += " Возраст: "+age_m.group(0)
    return item

def import_yuna(main):
    # The live site exposes /animal/<slug>/ cards and separate dog/cat catalogs.
    seeds=[YUNA_ROOT+"/animals/",YUNA_ROOT+"/dogs/",YUNA_ROOT+"/cats/"]
    links=[]
    for seed in seeds:
        r=main.fetch(seed)
        if not r or r.status_code>=400: continue
        links += _detail_links(
            r.text,str(r.url),
            lambda u: _same_host(u,YUNA_ROOT) and re.match(r"https?://yunacenter\.ru/animal/[^/]+/?$",u,re.I)
        )
    links=list(dict.fromkeys(links))[:150]
    created=updated=0
    for url in links:
        r=main.fetch(url)
        if not r or r.status_code>=400: continue
        item=_parse_yuna_detail(url,r.text,main)
        if not item: continue
        with main.SessionLocal() as db:
            shelter=_ensure_shelter(db,"Юна",YUNA_ROOT+"/priut/", "Московская область","Подольск",main)
            c,u=main.upsert_animal(db,shelter,item,"yuna")
            created+=int(c); updated+=int(u and not c)
            shelter.last_import_at=main.now(); shelter.last_source_ok_at=main.now()
            shelter.last_error=None; shelter.consecutive_failures=0
            db.commit()
    return created,updated

def _parse_dor_detail(url,html,main):
    title_m=re.search(r"<h1[^>]*>(.*?)</h1>",html,re.I|re.S)
    title=_clean(title_m.group(1) if title_m else "",main.clean_text)
    if not title: return None
    text=main.clean_text(html)
    species="cat" if re.search(r"Животное:\s*кош",text,re.I) else "dog" if re.search(r"Животное:\s*собак",text,re.I) else "other"
    sex=None
    if re.search(r"Пол:\s*(?:сука|кошка)\b",text,re.I): sex="female"
    elif re.search(r"Пол:\s*(?:кобель|кот)\b",text,re.I): sex="male"
    year_m=re.search(r"Год рождения:\s*(\d{4})",text,re.I)
    shelter_m=re.search(r"Приют:\s*([^\n]+?)(?:\s{2,}|Характер:|$)",text,re.I)
    shelter_name=_clean(shelter_m.group(1) if shelter_m else "",main.clean_text)
    item={
        "title":title[:255],"description":text[:10000],"link":url,
        "photo_urls":main.extract_page_images(url,html),"species_hint":species,
        "shelter_name":shelter_name,
    }
    if year_m: item["description"] += " Год рождения: "+year_m.group(1)
    return item

def import_dorinvest(main):
    links=[]
    # 383 cards are currently published. Pages are 12 cards each; read a bounded
    # set per cycle so the Render free instance remains responsive.
    for start in range(0, 384, 12):
        sep="&" if "?" in DOR_CATALOG else "?"
        url=f"{DOR_CATALOG}{sep}start={start}"
        r=main.fetch(url)
        if not r or r.status_code>=400: continue
        links += _detail_links(
            r.text,str(r.url),
            lambda u: _same_host(u,DORINVEST_ROOT) and "/product/view/" in u
        )
        if len(set(links)) >= 150: break
    links=list(dict.fromkeys(links))[:150]
    created=updated=0
    for url in links:
        r=main.fetch(url)
        if not r or r.status_code>=400: continue
        item=_parse_dor_detail(url,r.text,main)
        if not item or not item.get("shelter_name"): continue
        with main.SessionLocal() as db:
            shelter=_ensure_shelter(db,item["shelter_name"],DOR_CATALOG,"Москва","Москва",main)
            c,u=main.upsert_animal(db,shelter,item,"dorinvest")
            created+=int(c); updated+=int(u and not c)
            shelter.last_import_at=main.now(); shelter.last_source_ok_at=main.now()
            shelter.last_error=None; shelter.consecutive_failures=0
            db.commit()
    return created,updated


def _pechatniki_listing_items(html, base_url, species, main):
    """Extract animal cards from the official Pechatniki catalog pages.
    The site renders rich profiles, but the listing itself reliably exposes
    the animal name, age/sex and card image, so we use both layers.
    """
    soup=BeautifulSoup(html or "", "html.parser")
    out=[]
    for anchor in soup.find_all("a", href=True):
        href=anchor.get("href","").strip()
        url=urljoin(base_url, href).split("#",1)[0]
        if not _same_host(url, base_url):
            continue
        path=urlparse(url).path.lower().rstrip("/")
        if path in ("", "/dogs", "/cats", "/catalog", "/about", "/help", "/contacts"):
            continue
        if re.search(r"/(?:privacy|questions|help|about|contacts|take_cat|take_dog|catalog)(?:/|$)", path):
            continue
        name=main.clean_text(anchor.get_text(" ", strip=True))
        if not name or len(name) > 120:
            continue
        parent=anchor
        card_text=""
        card_img=None
        for _ in range(5):
            parent=parent.parent
            if parent is None:
                break
            txt=main.clean_text(parent.get_text(" ", strip=True))
            if 10 <= len(txt) <= 600 and re.search(r"\b\d+\s*(?:год|года|лет|месяц|месяца|месяцев)\b", txt, re.I) and re.search(r"\b(?:мальчик|девочка)\b", txt, re.I):
                card_text=txt
                img=parent.find("img")
                if img:
                    src=img.get("src") or img.get("data-src") or img.get("data-original")
                    if src:
                        card_img=urljoin(base_url, src)
                break
        if not card_text:
            continue
        if not re.search(r"\b(?:собак|собака|пёс|пес|кош|кошка|кот)\b", card_text+" "+name, re.I):
            # Species is supplied by the catalog section; no need to reject a
            # card just because the compact listing omits the species word.
            pass
        out.append({
            "title": name[:255],
            "description": card_text[:10000],
            "link": url,
            "photo_urls": [card_img] if card_img and main.same_origin_image(card_img, url) else [],
            "species_hint": species,
        })
    unique={}
    for item in out:
        unique[item["link"]]=item
    return list(unique.values())

def import_pechatniki(main):
    """Official dog + cat catalogs from the municipal Pechatniki shelter."""
    seeds=[
        ("https://pechatniki-pets.ru/dogs","dog"),
        ("https://cats.pechatniki-pets.ru/","cat"),
    ]
    created=updated=0
    for seed,species in seeds:
        r=main.fetch(seed)
        if not r or r.status_code>=400:
            continue
        items=_pechatniki_listing_items(r.text, str(r.url), species, main)
        for item in items[:180]:
            # Try the detail page for a richer description and original photos.
            detail=main.fetch(item["link"])
            if detail and detail.status_code<400:
                title_m=re.search(r"<h1[^>]*>(.*?)</h1>", detail.text, re.I|re.S)
                detail_title=main.clean_text(title_m.group(1) if title_m else "")
                detail_text=main.clean_text(detail.text)
                if detail_title and len(detail_title)<255 and not re.search(r"\b(?:ищет дом|нашли дом)\b", detail_title, re.I):
                    item["title"]=detail_title
                detail_photos=main.extract_page_images(item["link"], detail.text)
                if detail_photos:
                    item["photo_urls"]=detail_photos
                # Do not replace the reliable listing facts with a tiny meta
                # description returned by the site.
                if len(detail_text)>len(item["description"])+80:
                    item["description"]=detail_text[:10000]
            with main.SessionLocal() as db:
                shelter=_ensure_shelter(
                    db,"Приют Печатники","https://pechatniki-pets.ru",
                    "Москва","Москва",main
                )
                c,u=main.upsert_animal(db,shelter,item,"pechatniki")
                created+=int(c); updated+=int(u and not c)
                shelter.last_import_at=main.now()
                shelter.last_source_ok_at=main.now()
                shelter.last_error=None
                shelter.consecutive_failures=0
                db.commit()
    with main.SessionLocal() as db:
        main.update_counts(db); db.commit()
    return created,updated


def _is_animal_profile(url, title, body):
    """Strict classifier: shelter news/posts are never animal cards."""
    text=(title or "")+" "+(body or "")
    low=text.lower()
    path=urlparse(url).path.lower()
    if re.search(r"/(?:news|novosti|blog|articles?|posts?)(?:/|$)", path, re.I):
        return False
    news_terms=("благодарим","спасибо","новости","мероприят","выставк","акция",
                "субботник","день открытых дверей","волонтёр","волонтер",
                "помощь приюту","закуп","поставка","корм","сбор средств",
                "поздрав","отчёт","отчет","праздник")
    if any(x in low for x in news_terms):
        return False
    profile=sum(bool(re.search(p, low, re.I)) for p in (
        r"\bвозраст\b", r"год рождения", r"\bпол\s*[:—-]",
        r"окрас\s*[:—-]", r"порода\s*[:—-]", r"стерилиз",
        r"кастрирован", r"вакцинир", r"привит", r"ищет дом",
        r"готов[аы]? к пристрой"
    ))
    animal=bool(re.search(
        r"\b(?:собак|собака|пёс|пес|щен|кошк|кошка|кот|котён|котен|dog|cat)\b",
        low, re.I
    ))
    return animal and profile >= 1

def import_generic_shelter_sites(main, max_sites=60, max_pages_per_site=20):
    """Read public animal profile pages from known shelter websites."""
    with main.SessionLocal() as db:
        rows=db.scalars(main.select(main.Shelter).where(
            main.Shelter.active.is_(True), main.Shelter.website.is_not(None)
        ).order_by(main.Shelter.name)).all()
        targets=[(s.id,s.name,s.website) for s in rows[:max_sites]]

    created=updated=0
    for sid,sname,website in targets:
        root=website.rstrip("/")
        queue=[root,root+"/",root+"/catalog/",root+"/animals/",root+"/animal/",
               root+"/pets/",root+"/dogs/",root+"/cats/",root+"/adoption/",
               root+"/pristroj/",root+"/pristroystvo/"]
        seen=set(); details=[]
        while queue and len(seen)<max_pages_per_site:
            url=queue.pop(0)
            if url in seen or not _same_host(url,root): continue
            seen.add(url)
            r=main.fetch(url)
            if not r or r.status_code>=400: continue
            html=r.text or ""
            title_m=re.search(r"<title[^>]*>(.*?)</title>",html,re.I|re.S)
            title=main.clean_text(title_m.group(1) if title_m else "")
            body=main.clean_text(html)
            if _is_animal_profile(url,title,body):
                details.append((url,html,title,body))
            for href in re.findall(r'href=["\']([^"\']+)',html,re.I):
                u=urljoin(str(r.url),href).split("#",1)[0]
                if _same_host(u,root) and u not in seen:
                    path=urlparse(u).path.lower()
                    if any(k in path for k in (
                        "/animal","/animals","/pet","/pets","/dog","/dogs",
                        "/cat","/cats","/adopt","/catalog","/pristro","/zhivot"
                    )):
                        queue.append(u)
        unique={x[0]:x for x in details}
        for url,html,title,body in list(unique.values())[:80]:
            species="cat" if re.search(r"кош|кот|cat",body+" "+url,re.I) else "dog" if re.search(r"собак|пёс|пес|dog",body+" "+url,re.I) else "other"
            item={"title":title[:255] or "Животное","description":body[:10000],
                  "link":url,"photo_urls":main.extract_page_images(url,html),
                  "species_hint":species}
            with main.SessionLocal() as db:
                shelter=db.get(main.Shelter,sid)
                if not shelter: continue
                c,u=main.upsert_animal(db,shelter,item,"website")
                created+=int(c); updated+=int(u and not c)
                shelter.last_import_at=main.now()
                shelter.last_source_ok_at=main.now()
                shelter.last_error=None
                shelter.consecutive_failures=0
                db.commit()
    with main.SessionLocal() as db:
        main.update_counts(db); db.commit()
    return created,updated

def import_external_catalogs():
    # Fail independently: one inaccessible site must not prevent other sources.
    from app import main
    totals={"yuna":(0,0),"dorinvest":(0,0),"pechatniki":(0,0),"generic":(0,0)}
    for key,fn in (("yuna",import_yuna),("dorinvest",import_dorinvest),("pechatniki",import_pechatniki),("generic",import_generic_shelter_sites)):
        try:
            totals[key]=fn(main)
        except Exception:
            # Import errors are intentionally isolated; source health can be
            # inspected through the normal /api/source endpoints.
            continue
    with main.SessionLocal() as db:
        main.update_counts(db)
        db.commit()
    return totals
