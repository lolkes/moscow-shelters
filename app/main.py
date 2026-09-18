import asyncio
import hashlib
import html as html_lib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, or_, select, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE = Path(__file__).resolve().parent.parent
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE / 'shelters.db'}")
# Render/Neon usually provides postgresql://. SQLAlchemy's default PostgreSQL
# dialect expects psycopg2, while this project intentionally uses psycopg v3.
# Normalize the URL so the installed psycopg (v3) driver is selected.
if DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg://", 1)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = "MoscowSheltersCatalog/1.0 (+public-source-reader)"
ROS_PRIUT_INDEX = "https://rospriut.ru/shelters/msk/"
HOURLY_SECONDS = 3600
VERIFY_SECONDS = 7 * 24 * 3600
STALE_SECONDS = int(os.getenv("STALE_SECONDS", str(7 * 24 * 3600)))
SOURCE_RETRY_MINUTES = int(os.getenv("SOURCE_RETRY_MINUTES", "15"))
MAX_ITEMS_PER_SOURCE = int(os.getenv("MAX_ITEMS_PER_SOURCE", "200"))
DISCOVERY_URLS = [ROS_PRIUT_INDEX]

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Shelter(Base):
    __tablename__ = "shelters"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    vk_url: Mapped[Optional[str]] = mapped_column(String(500))
    telegram_url: Mapped[Optional[str]] = mapped_column(String(500))
    phone: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_type: Mapped[str] = mapped_column(String(30), default="none")
    import_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="active")
    animal_count: Mapped[int] = mapped_column(Integer, default=0)
    last_import_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_source_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

class Animal(Base):
    __tablename__ = "animals"
    __table_args__ = (UniqueConstraint("original_url", name="uq_animal_original_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shelter_id: Mapped[str] = mapped_column(ForeignKey("shelters.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    species: Mapped[str] = mapped_column(String(40), default="other", index=True)
    age: Mapped[Optional[str]] = mapped_column(String(100))
    sex: Mapped[Optional[str]] = mapped_column(String(40))
    breed: Mapped[Optional[str]] = mapped_column(String(255))
    size: Mapped[Optional[str]] = mapped_column(String(80))
    color: Mapped[Optional[str]] = mapped_column(String(255))
    sterilized: Mapped[Optional[bool]] = mapped_column(Boolean)
    vaccinated: Mapped[Optional[bool]] = mapped_column(Boolean)
    city: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    photo_url: Mapped[Optional[str]] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(30), default="new")
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_source_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    duplicate_reason: Mapped[Optional[str]] = mapped_column(String(255))

class AnimalPhoto(Base):
    __tablename__ = "animal_photos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    animal_id: Mapped[int] = mapped_column(ForeignKey("animals.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shelter_id: Mapped[str] = mapped_column(String(120), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    imported: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="running")
    error: Mapped[Optional[str]] = mapped_column(Text)


class AnimalHistory(Base):
    __tablename__ = "animal_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    animal_id: Mapped[int] = mapped_column(ForeignKey("animals.id"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    change_type: Mapped[str] = mapped_column(String(40))
    snapshot: Mapped[str] = mapped_column(Text)

class SourceCheck(Base):
    __tablename__ = "source_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shelter_id: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(40))
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    detail: Mapped[Optional[str]] = mapped_column(Text)

class AutomationLock(Base):
    __tablename__ = "automation_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

Base.metadata.create_all(engine)

def ensure_sqlite_schema():
    """Add newly introduced nullable columns when upgrading an existing SQLite DB."""
    if not DB_URL.startswith("sqlite"):
        return
    wanted = {
        "animals": {
            "breed": "VARCHAR(255)", "size": "VARCHAR(80)", "color": "VARCHAR(255)",
            "sterilized": "BOOLEAN", "vaccinated": "BOOLEAN", "duplicate_of_id": "INTEGER", "duplicate_reason": "VARCHAR(255)"
        }
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

ensure_sqlite_schema()

robots_cache: dict[str, tuple[float, robotparser.RobotFileParser]] = {}


def now() -> datetime:
    return datetime.now(timezone.utc)


def serialize(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def robots_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        root = f"{parsed.scheme}://{parsed.netloc}"
        cached = robots_cache.get(root)
        if not cached or time.time() - cached[0] > 3600:
            rp = robotparser.RobotFileParser()
            rp.set_url(root + "/robots.txt")
            try:
                rp.read()
            except Exception:
                # If robots.txt cannot be fetched, do not aggressively crawl the site.
                return False
            robots_cache[root] = (time.time(), rp)
            cached = robots_cache[root]
        return cached[1].can_fetch(USER_AGENT, url)
    except Exception:
        return False


def fetch(url: str):
    if not url or not url.startswith(("http://", "https://")) or not robots_allowed(url):
        return None
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            return client.get(url)
    except Exception:
        return None


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def normalize(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def fingerprint(shelter_id: str, title: str, description: str) -> str:
    raw = f"{shelter_id}|{normalize(title)}|{normalize(description)[:900]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def infer_species(text: str) -> str:
    t = text.lower()
    if re.search(r"кот|кош|котён|котен", t): return "cat"
    if re.search(r"собак|пёс|пес|щен|собач", t): return "dog"
    return "other"


def infer_sex(text: str) -> Optional[str]:
    t = text.lower()
    if re.search(r"\b(самка|девочк|стерилизованн\w*)\b", t): return "female"
    if re.search(r"\b(самец|мальчик|кастрированн\w*)\b", t): return "male"
    return None


def infer_age(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})\s*(лет|года|год|г\.|месяц(?:а|ев)?|мес\.)", text.lower())
    if not m: return None
    n = int(m.group(1))
    return f"{n} мес." if "мес" in m.group(2) or "месяц" in m.group(2) else f"{n} лет"



def infer_breed(text: str) -> Optional[str]:
    patterns = [
        r"порода\s*[:—-]\s*([^,.\n]+)",
        r"\b(лабрадор(?:-ретривер)?|овчарка|хаски|такса|шпиц|йоркширский терьер|чихуахуа|мейн-кун|британская|сиамская)\b"
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m: return m.group(1).strip()[:255]
    return None

def infer_size(text: str) -> Optional[str]:
    t=text.lower()
    for key in ("маленьк", "небольш", "средн", "крупн"):
        if key in t:
            return {"маленьк":"small","небольш":"small","средн":"medium","крупн":"large"}[key]
    return None

def infer_color(text: str) -> Optional[str]:
    m=re.search(r"(?:окрас|цвет)\s*[:—-]\s*([^,.\n]+)", text, re.I)
    return m.group(1).strip()[:255] if m else None

def infer_bool(text: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> Optional[bool]:
    t=text.lower()
    if any(x in t for x in positive): return True
    if any(x in t for x in negative): return False
    return None

def parse_feed(xml_text: str, base_url: str = ""):
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    out=[]
    for node in root.iter():
        if node.tag.rsplit("}",1)[-1] not in {"item","entry"}: continue
        vals={}; links=[]; images=[]
        for child in list(node):
            key=child.tag.rsplit("}",1)[-1]; txt=(child.text or "").strip(); href=child.attrib.get("href","")
            vals[key]=txt or href
            if key=="link" and (txt or href): links.append(txt or href)
            u=child.attrib.get("url") or child.attrib.get("href") or txt
            typ=(child.attrib.get("type") or "").lower()
            if u and ("image" in typ or re.search(r"\.(?:jpe?g|png|webp|gif)(?:[?#].*)?$",u,re.I)): images.append(urljoin(base_url,html_lib.unescape(u)))
            for sub in list(child):
                u2=sub.attrib.get("url") or sub.attrib.get("href") or (sub.text or "").strip()
                typ2=(sub.attrib.get("type") or "").lower()
                if u2 and ("image" in sub.tag.lower() or "thumbnail" in sub.tag.lower() or "image" in typ2):
                    images.append(urljoin(base_url,html_lib.unescape(u2)))
        link=(links[0] if links else None) or vals.get("guid") or vals.get("id")
        title=clean_text(vals.get("title","")); desc=clean_text(vals.get("description") or vals.get("summary") or vals.get("content") or "")
        if link and title:
            out.append({"title":title[:255],"description":desc[:10000],"link":urljoin(base_url,link),"photo_urls":list(dict.fromkeys(images))[:10]})
    return out

def same_origin_image(url:str, source_url:str)->bool:
    try:
        u,src=urlparse(url),urlparse(source_url)
        return u.scheme in {"http","https"} and u.netloc.lower()==src.netloc.lower()
    except Exception: return False

def extract_page_images(page_url:str, html:str)->list[str]:
    found=[]
    patterns=[
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
        r'<img[^>]+(?:src|data-src)=["\']([^"\']+)'
    ]
    for pat in patterns:
        for m in re.finditer(pat,html[:2_000_000],re.I):
            u=urljoin(page_url,html_lib.unescape(m.group(1)))
            if same_origin_image(u,page_url): found.append(u)
            if len(found)>=10: break
        if len(found)>=10: break
    return list(dict.fromkeys(found))[:10]

def discover_item_images(item:dict)->list[str]:
    imgs=[u for u in item.get("photo_urls",[]) if same_origin_image(u,item["link"])]
    if imgs: return imgs
    r=fetch(item["link"])
    if r and r.status_code<400: return extract_page_images(str(r.url),r.text)
    return []

def discover_feed(website: str) -> Optional[str]:
    r = fetch(website)
    if not r or r.status_code >= 400:
        return None
    body = r.text[:1_500_000]
    patterns = [
        r'<link[^>]+type=["\']application/(?:rss\+xml|atom\+xml)["\'][^>]+href=["\']([^"\']+)',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/(?:rss\+xml|atom\+xml)["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, body, re.I)
        if m:
            feed = urljoin(str(r.url), html_lib.unescape(m.group(1)))
            if robots_allowed(feed):
                return feed
    return None


def duplicate_candidate(db, shelter_id: str, item: dict, species: str, fp: str):
    """Find a strong cross-source duplicate without guessing on weak matches."""
    title = normalize(item.get("title", ""))
    if not title or len(title) < 3:
        return None
    # Exact fingerprint across different sources/shelters is strong enough.
    a = db.scalar(select(Animal).where(Animal.fingerprint == fp, Animal.active.is_(True)))
    if a and a.shelter_id != shelter_id:
        return a
    # Same species + near-identical title is only accepted when descriptions also overlap.
    candidates = db.scalars(select(Animal).where(Animal.active.is_(True), Animal.species == species).limit(1000)).all()
    words = {w for w in title.split() if len(w) >= 3}
    for c in candidates:
        ctitle = normalize(c.name)
        cwords = {w for w in ctitle.split() if len(w) >= 3}
        if words and cwords and len(words & cwords) / max(1, len(words | cwords)) >= 0.8:
            desc = normalize(item.get("description", ""))
            cdesc = normalize(c.description or "")
            if desc and cdesc:
                dwords = {w for w in desc.split() if len(w) >= 5}
                cdwords = {w for w in cdesc.split() if len(w) >= 5}
                if dwords and cdwords and len(dwords & cdwords) / max(1, len(dwords | cdwords)) >= 0.35:
                    return c
    return None


def upsert_animal(db, shelter: Shelter, item: dict, source_type: str):
    link = item["link"]
    item["photo_urls"] = discover_item_images(item)
    text = f"{item.get('title','')} {item.get('description','')}"
    fp = fingerprint(shelter.id, item.get("title", ""), item.get("description", ""))
    a = db.scalar(select(Animal).where(Animal.original_url == link))
    if not a:
        a = db.scalar(select(Animal).where(Animal.shelter_id == shelter.id, Animal.fingerprint == fp))
    species = item.get("species_hint") or infer_species(text); age = infer_age(text); sex = infer_sex(text)
    if not age:
        m_year = re.search(r"Год рождения\s*:\s*(\d{4})", text, re.I)
        if m_year: age = f"рожд. {m_year.group(1)}"
    dup = duplicate_candidate(db, shelter.id, item, species, fp)
    if dup and dup.original_url != link:
        a = db.scalar(select(Animal).where(Animal.original_url == link))
        if not a:
            a = Animal(shelter_id=shelter.id, name=item["title"], species=species, age=age, sex=sex, city=shelter.city, description=item["description"], original_url=link, source_type=source_type, active=False, status="duplicate", fingerprint=fp, duplicate_of_id=dup.id, duplicate_reason="Совпадение с существующим объявлением", last_seen_at=now(), last_source_check_at=now())
            db.add(a); db.flush()
            db.add(AnimalHistory(animal_id=a.id, change_type="duplicate_detected", snapshot=json.dumps({"duplicate_of_id":dup.id,"original_url":link}, ensure_ascii=False)))
        else:
            a.active=False; a.status="duplicate"; a.duplicate_of_id=dup.id; a.duplicate_reason="Совпадение с существующим объявлением"; a.last_seen_at=now()
        return False, False
    breed = infer_breed(text); size = infer_size(text); color = infer_color(text)
    sterilized = infer_bool(text, ("стерилизован", "стерилизована", "кастрирован", "кастрирована"), ("не стерилизован", "не кастрирован"))
    vaccinated = infer_bool(text, ("вакцинирован", "привит", "привита"), ("не вакцинирован", "не привит"))
    if a:
        before = {"name":a.name,"species":a.species,"age":a.age,"sex":a.sex,"breed":a.breed,"size":a.size,"color":a.color,"sterilized":a.sterilized,"vaccinated":a.vaccinated,"description":a.description,"active":a.active}
        after = {"name":item["title"],"species":species,"age":age,"sex":sex,"breed":breed,"size":size,"color":color,"sterilized":sterilized,"vaccinated":vaccinated,"description":item["description"],"active":True}
        changed = before != after
        if changed:
            db.add(AnimalHistory(animal_id=a.id, change_type="updated", snapshot=json.dumps(before, ensure_ascii=False)))
        a.name=item["title"]; a.description=item["description"]; a.species=species; a.age=age; a.sex=sex; a.breed=breed; a.size=size; a.color=color; a.sterilized=sterilized; a.vaccinated=vaccinated
        a.active=True; a.status="verified"; a.last_seen_at=now(); a.updated_at=now(); a.archived_at=None; a.last_source_check_at=now(); a.fingerprint=fp
        existing_photos={x.url for x in db.scalars(select(AnimalPhoto).where(AnimalPhoto.animal_id==a.id,AnimalPhoto.is_active.is_(True))).all()}
        for idx, photo in enumerate(item.get("photo_urls", [])):
            if same_origin_image(photo,item["link"]) and photo not in existing_photos: db.add(AnimalPhoto(animal_id=a.id,url=photo,sort_order=idx,is_active=True))
        return False, changed
    a = Animal(shelter_id=shelter.id,name=item["title"],species=species,age=age,sex=sex,breed=breed,size=size,color=color,sterilized=sterilized,vaccinated=vaccinated,city=shelter.city,description=item["description"],original_url=link,source_type=source_type,active=True,status="new",fingerprint=fp,last_seen_at=now(),last_source_check_at=now())
    db.add(a); db.flush()
    for idx, photo in enumerate(item.get("photo_urls", [])):
        if same_origin_image(photo,item["link"]): db.add(AnimalPhoto(animal_id=a.id,url=photo,sort_order=idx,is_active=True))
    db.add(AnimalHistory(animal_id=a.id, change_type="created", snapshot=json.dumps({"name":a.name,"species":a.species,"age":a.age,"sex":a.sex}, ensure_ascii=False)))
    return True, True




def update_counts(db):
    shelters = db.scalars(select(Shelter)).all()
    for s in shelters:
        s.animal_count = db.scalar(select(func.count(Animal.id)).where(Animal.shelter_id == s.id, Animal.active.is_(True), Animal.status != "duplicate")) or 0


def photo_urls(db, animal_id: int):
    return [x.url for x in db.scalars(select(AnimalPhoto).where(AnimalPhoto.animal_id==animal_id, AnimalPhoto.is_active.is_(True)).order_by(AnimalPhoto.sort_order, AnimalPhoto.id)).all()]

def _rospriut_shelter(db, name: str, href: str | None):
    """Resolve a RosPriut shelter to our canonical shelter record."""
    clean = normalize(name).replace("приют ", "").strip()
    rows = db.scalars(select(Shelter).where(Shelter.active.is_(True))).all()
    for s in rows:
        sn = normalize(s.name).replace("приют ", "").strip()
        if sn == clean or clean in sn or sn in clean:
            if href and not s.source_url:
                s.source_url = href
            return s
    slug = ""
    if href:
        m = re.search(r"/shelters/msk/([^/]+)/?", href)
        if m: slug = m.group(1)
    sid = slug or ("rospriut-" + hashlib.sha256((name + (href or "")).encode("utf-8")).hexdigest()[:20])
    s = db.get(Shelter, sid)
    if not s:
        s = Shelter(
            id=sid, name=name, region="Москва", city="Москва",
            source_url=href, website=None, verified=True, active=True,
            source_type="rospriut", import_enabled=False, status="active"
        )
        db.add(s); db.flush()
    return s


def _rospriut_detail(url: str, species: str):
    r = fetch(url)
    if not r or r.status_code >= 400:
        return None
    html = r.text
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    title = clean_text(title_m.group(1)) if title_m else ""
    if not title:
        return None
    shelter_m = re.search(
        r'''Приют\s*:\s*<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>''',
        html, re.I | re.S
    )
    shelter_name = clean_text(shelter_m.group(2)) if shelter_m else ""
    shelter_href = urljoin(str(r.url), shelter_m.group(1)) if shelter_m else None

    parts = []
    for m in re.findall(r"<blockquote[^>]*>(.*?)</blockquote>", html, re.I | re.S):
        t = clean_text(m)
        if t: parts.append(t)
    if not parts:
        body_text = clean_text(html)
        parts = [body_text[:10000]]

    images = extract_page_images(str(r.url), html)
    text = clean_text(html)
    item = {
        "title": title[:255],
        "description": " ".join(parts)[:10000],
        "link": str(r.url),
        "photo_urls": images,
        "species_hint": species,
        "shelter_name": shelter_name,
        "shelter_href": shelter_href,
    }
    return item


def import_rospriut_catalog(kind: str, pages: int = 6) -> tuple[int, int]:
    """Import current public animal cards from RosPriut, preserving original links."""
    base = f"https://rospriut.ru/{kind}/"
    urls = [base]
    if kind == "dogs":
        urls += [f"{base}page/{n}/" for n in range(2, pages + 1)]
    detail_urls = []
    for page_url in urls:
        r = fetch(page_url)
        if not r or r.status_code >= 400:
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, re.I):
            u = urljoin(str(r.url), html_lib.unescape(href))
            if re.match(rf"https?://rospriut\.ru/{kind}/[^/]+/?$", u, re.I):
                if u not in detail_urls:
                    detail_urls.append(u)
    detail_urls = detail_urls[:MAX_ITEMS_PER_SOURCE]
    if not detail_urls:
        return 0, 0

    created = updated = 0
    for url in detail_urls:
        item = _rospriut_detail(url, "dog" if kind == "dogs" else "cat")
        if not item or not item.get("shelter_name"):
            continue
        with SessionLocal() as db:
            shelter = _rospriut_shelter(db, item["shelter_name"], item.get("shelter_href"))
            db.commit()
            c, u = upsert_animal(
                db, shelter, item, "rospriut_" + ("dog" if kind == "dogs" else "cat")
            )
            created += int(c)
            updated += int(u and not c)
            db.commit()
    with SessionLocal() as db:
        update_counts(db)
        db.commit()
    return created, updated


def import_rss(shelter_id: str) -> tuple[int, int]:
    with SessionLocal() as db:
        shelter = db.get(Shelter, shelter_id)
        if not shelter or not shelter.source_url: raise RuntimeError("Источник не задан")
        source_url = shelter.source_url
    r = fetch(source_url)
    if not r or r.status_code >= 400:
        raise RuntimeError("RSS/Atom недоступен или запрещён robots.txt")
    items = parse_feed(r.text,str(r.url))
    created = updated = 0
    with SessionLocal() as db:
        shelter = db.get(Shelter, shelter_id)
        if not shelter: raise RuntimeError("Приют не найден")
        for item in items[:MAX_ITEMS_PER_SOURCE]:
            c, u = upsert_animal(db, shelter, item, "rss")
            created += int(c); updated += int(u and not c)
        shelter.last_import_at=now(); shelter.last_source_ok_at=now(); shelter.last_error=None; shelter.consecutive_failures=0
        update_counts(db); db.commit()
    return created, updated


def discover_sources():
    with SessionLocal() as db:
        shelters = db.scalars(select(Shelter).where(Shelter.active.is_(True))).all()
    for shelter in shelters:
        feed = discover_feed(shelter.website) if shelter.website else None
        with SessionLocal() as db:
            s=db.get(Shelter,shelter.id)
            if not s: continue
            if feed:
                s.source_type="rss"; s.source_url=feed; s.import_enabled=True; s.status="active"
            elif s.website and s.source_type == "none":
                s.source_type="website"; s.import_enabled=False
            db.commit()


def discover_new_shelters():
    # Conservative discovery: only recognize links that look like shelter cards from the public registry.
    # Unknown records are not inserted unless a name and a stable URL can be extracted.
    for url in DISCOVERY_URLS:
        r=fetch(url)
        if not r or r.status_code>=400: continue
        found=[]
        for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.I|re.S):
            href=urljoin(str(r.url), html_lib.unescape(m.group(1))); label=clean_text(m.group(2))
            if not href.startswith(("http://","https://")) or len(label)<3: continue
            if any(x in label.lower() for x in ["приют","зоозащит"]): found.append((label[:255],href))
        with SessionLocal() as db:
            for label, href in found:
                sid="discovered-"+hashlib.sha256(href.encode()).hexdigest()[:24]
                if not db.get(Shelter,sid):
                    db.add(Shelter(id=sid,name=label,region="Москва",city="Москва",website=href,source_url=href,verified=False,active=True,source_type="website",import_enabled=False,status="active"))
            db.commit()


def verify_shelter(shelter_id: str):
    with SessionLocal() as db:
        s=db.get(Shelter,shelter_id)
        if not s: return None
        urls=[x for x in [s.website,s.source_url] if x]
    result="error"; ok=False; detail="Нет доступного источника"; code=None
    for url in urls:
        try:
            if not robots_allowed(url):
                result="robots_disallowed"; detail="Доступ запрещён robots.txt"; continue
            r=fetch(url); code=r.status_code if r else None
            if r and r.status_code<400:
                ok=True; result="ok"; detail="Источник доступен"; break
            result="http_error"; detail=f"HTTP {code}"
        except Exception as exc: detail=str(exc)[:500]
    with SessionLocal() as db:
        s=db.get(Shelter,shelter_id)
        s.verified=ok; s.last_verified_at=now(); s.status="active" if ok else "needs_review"
        db.add(SourceCheck(shelter_id=s.id,url=(urls[0] if urls else ROS_PRIUT_INDEX),status=result,http_status=code,detail=detail))
        db.commit(); return serialize(s)


def verify_due():
    cutoff=now()-timedelta(seconds=VERIFY_SECONDS)
    with SessionLocal() as db:
        ids=db.scalars(select(Shelter.id).where(or_(Shelter.last_verified_at.is_(None),Shelter.last_verified_at<cutoff))).all()
    for sid in ids: verify_shelter(sid)


def archive_stale():
    cutoff=now()-timedelta(seconds=STALE_SECONDS)
    with SessionLocal() as db:
        # Only archive after a successful source check. A dead source must never hide animals.
        rows=db.scalars(select(Animal).join(Shelter).where(Animal.active.is_(True),Animal.last_seen_at<cutoff,Shelter.last_source_ok_at.is_not(None),Shelter.last_source_ok_at>cutoff)).all()
        for a in rows:
            a.active=False; a.status="archived"; a.archived_at=now(); a.updated_at=now()
            db.add(AnimalHistory(animal_id=a.id,change_type="archived",snapshot=json.dumps({"reason":"not_seen_after_successful_source_check"},ensure_ascii=False)))
        update_counts(db); db.commit()

def acquire_lock(seconds=3300):
    with SessionLocal() as db:
        lock=db.get(AutomationLock,1)
        if not lock: lock=AutomationLock(id=1); db.add(lock); db.flush()
        if lock.locked_until and lock.locked_until>now(): return False
        lock.locked_until=now()+timedelta(seconds=seconds); db.commit(); return True

def release_lock():
    with SessionLocal() as db:
        lock=db.get(AutomationLock,1)
        if lock: lock.locked_until=None; db.commit()

def cleanup_non_animal_posts():
    """Deactivate cards that are clearly shelter news/posts, not animal profiles."""
    news_terms = (
        "благодарим", "спасибо", "помощь приют", "новости", "мероприят",
        "выставк", "акция", "субботник", "день открытых дверей", "волонт",
        "поставк", "корм", "закуп", "сбор средств", "донат", "праздник",
        "поздрав", "отчет", "отчёт", "наши новости"
    )
    profile_terms = (
        "возраст", "год рождения", "пол", "окрас", "порода",
        "стерилизац", "кастрац", "вакцинир", "привит", "ищет дом",
        "ищет хозя", "готов к пристрой", "готова к пристрой"
    )
    with SessionLocal() as db:
        rows=db.scalars(select(Animal).where(
            Animal.active.is_(True), Animal.status != "duplicate"
        )).all()
        changed=0
        for a in rows:
            text=normalize(f"{a.name} {a.description or ''}")
            url=(a.original_url or "").lower()
            has_profile=any(x in text for x in profile_terms)
            looks_news=any(x in text for x in news_terms) or re.search(
                r"/(?:news|novosti|blog|articles?|posts?)(?:/|$)", url, re.I
            )
            if looks_news and not has_profile:
                a.active=False
                a.status="archived"
                a.archived_at=now()
                a.updated_at=now()
                changed += 1
        update_counts(db)
        db.commit()
        return changed

def import_all():
    discover_new_shelters()
    discover_shelter_websites()
    discover_sources()
    cleanup_non_animal_posts()

    from app.adapters import import_external_catalogs
    import_external_catalogs()
    cleanup_non_animal_posts()

    # RosPriut is a public animal-card catalog and is the reliable fallback.
    import_rospriut_catalog("dogs", pages=6)
    import_rospriut_catalog("cats", pages=1)

    with SessionLocal() as db:
        sources=[(s.id,s.name,s.source_type,s.source_url)
                 for s in db.scalars(select(Shelter).where(
                     Shelter.active.is_(True), Shelter.import_enabled.is_(True)
                 )).all()]
    for sid,name,source_type,source_url in sources:
        with SessionLocal() as db:
            run=ImportRun(shelter_id=sid,source_type=source_type,
                          source_url=source_url,started_at=now())
            db.add(run); db.commit(); run_id=run.id
        try:
            if source_type!="rss":
                raise RuntimeError(f"Нет безопасного автоматического адаптера для {source_type}")
            created,updated=import_rss(sid)
            with SessionLocal() as db:
                run=db.get(ImportRun,run_id)
                run.imported=created; run.updated=updated
                run.status="ok"; run.finished_at=now(); db.commit()
        except Exception as exc:
            with SessionLocal() as db:
                run=db.get(ImportRun,run_id)
                run.status="error"; run.error=str(exc)[:2000]; run.finished_at=now()
                s=db.get(Shelter,sid)
                if s:
                    s.last_error=str(exc)[:2000]
                    s.consecutive_failures=(s.consecutive_failures or 0)+1
                db.commit()

def automation_cycle():
    if not acquire_lock(): return
    try:
        import_all()
        cleanup_non_animal_posts()
        archive_stale()
        verify_due()
    finally:
        release_lock()

async def automation_loop():
    await asyncio.sleep(3)
    while True:
        await asyncio.to_thread(automation_cycle)
        await asyncio.sleep(HOURLY_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(automation_loop())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass


# --- public shelter website discovery/import --- 
def discover_shelter_websites():
    """Resolve official websites from the shelter pages in the public registry."""
    r = fetch(ROS_PRIUT_INDEX)
    if not r or r.status_code >= 400:
        return 0
    links = []
    for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.I | re.S):
        href = urljoin(str(r.url), html_lib.unescape(m.group(1)))
        label = clean_text(m.group(2))
        if "/shelters/msk/" in href and label:
            if href not in links:
                links.append(href)
    updated = 0
    for shelter_page in links[:100]:
        rr = fetch(shelter_page)
        if not rr or rr.status_code >= 400:
            continue
        candidates = []
        # Prefer an explicit "Сайт:" link from the registry page.
        for m in re.finditer(r'(?:Сайт(?:ы)?|Сайт)\s*:\s*(?:<[^>]+>\s*)?<a[^>]+href=["\']([^"\']+)["\']', rr.text, re.I | re.S):
            candidates.append(urljoin(str(rr.url), html_lib.unescape(m.group(1))))
        # Also accept visible absolute links on the shelter page, excluding the registry itself.
        for m in re.findall(r'href=["\'](https?://[^"\']+)["\']', rr.text, re.I):
            u = html_lib.unescape(m)
            if "rospriut.ru" not in (urlparse(u).hostname or "").lower():
                candidates.append(u)
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            continue
        with SessionLocal() as db:
            matches = db.scalars(select(Shelter).where(Shelter.active.is_(True))).all()
            target = None
            page_name = ""
            hm = re.search(r"<h1[^>]*>(.*?)</h1>", rr.text, re.I | re.S)
            if hm: page_name = normalize(clean_text(hm.group(1))).replace("приют ","").strip()
            for s in matches:
                sn = normalize(s.name).replace("приют ","").strip()
                if page_name and (sn == page_name or sn in page_name or page_name in sn):
                    target = s
                    break
            if not target:
                continue
            for u in candidates:
                if robots_allowed(u):
                    target.website = u
                    if target.source_type in ("none", "website", "rospriut"):
                        target.source_url = u
                    target.status = "active"
                    updated += 1
                    break
            db.commit()
    return updated

# --- v13 automatic source helpers ---
import hashlib
from urllib.parse import urljoin, urlparse

def _same_host(a: str, b: str) -> bool:
    try:
        return (urlparse(a).hostname or "").lower().lstrip("www.") == (urlparse(b).hostname or "").lower().lstrip("www.")
    except Exception:
        return False

def _is_http_url(value):
    return bool(value and value.startswith(("http://", "https://")))

def _extract_image_urls_from_html(html: str, base_url: str):
    """Extract likely original-site images without inventing/substituting photos."""
    urls = []
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)',
    ]
    for p in patterns:
        for m in re.finditer(p, html, flags=re.I):
            u = urljoin(base_url, m.group(1).strip())
            if _is_http_url(u) and _same_host(u, base_url):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= 10:
                return urls
    return urls

def _photo_fingerprint(url: str):
    return hashlib.sha256(url.split("#", 1)[0].encode("utf-8")).hexdigest()[:24]

def _source_kind(url: str):
    if not url:
        return "none"
    host = (urlparse(url).hostname or "").lower()
    if "rospriut" in host or "mospriut" in host:
        return "catalog"
    if "vk.com" in host:
        return "vk"
    if "t.me" in host or "telegram" in host:
        return "telegram"
    return "website"

app = FastAPI(title="Приюты Москвы и МО", version="12.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/shelters/{shelter_id}", response_class=HTMLResponse)
def shelter_page(shelter_id: str):
    return (BASE / "static" / "shelter.html").read_text(encoding="utf-8").replace("__SHELTER_ID__", shelter_id)

@app.get("/animals/{animal_id}", response_class=HTMLResponse)
def animal_page(animal_id: int):
    return (BASE / "static" / "animal.html").read_text(encoding="utf-8").replace("__ANIMAL_ID__", str(animal_id))

@app.get("/admin", response_class=HTMLResponse)
def admin():
    return (BASE / "static" / "admin.html").read_text(encoding="utf-8")

@app.get("/api/metrics")
def metrics():
    with SessionLocal() as db:
        return {
            "active_shelters": db.scalar(select(func.count(Shelter.id)).where(Shelter.active.is_(True))) or 0,
            "active_animals": db.scalar(select(func.count(Animal.id)).where(Animal.active.is_(True), Animal.status != "duplicate")) or 0,
            "runs_24h": db.scalar(select(func.count(ImportRun.id)).where(ImportRun.started_at>now()-timedelta(hours=24))) or 0,
            "errors_24h": db.scalar(select(func.count(ImportRun.id)).where(ImportRun.status=="error",ImportRun.started_at>now()-timedelta(hours=24))) or 0,
            "sources_with_failures": db.scalar(select(func.count(Shelter.id)).where(Shelter.consecutive_failures>0)) or 0,
        }

@app.get("/api/sources/status")
def sources_status():
    with SessionLocal() as db:
        return [serialize(s) for s in db.scalars(select(Shelter).order_by(Shelter.consecutive_failures.desc(),Shelter.name)).all()]

@app.get("/api/animals/{animal_id}/history")
def animal_history(animal_id:int):
    with SessionLocal() as db:
        if not db.get(Animal,animal_id): raise HTTPException(404,"Животное не найдено")
        return [serialize(x) for x in db.scalars(select(AnimalHistory).where(AnimalHistory.animal_id==animal_id).order_by(AnimalHistory.changed_at.desc())).all()]

@app.get("/api/health")
def health():
    with SessionLocal() as db:
        return {"ok": True, "time": now().isoformat(), "shelters": db.scalar(select(func.count(Shelter.id))) or 0}

@app.get("/api/stats")
def stats():
    with SessionLocal() as db:
        return {
            "shelters": db.scalar(select(func.count(Shelter.id)).where(Shelter.active.is_(True))) or 0,
            "verified_shelters": db.scalar(select(func.count(Shelter.id)).where(Shelter.active.is_(True), Shelter.verified.is_(True))) or 0,
            "animals_active": db.scalar(select(func.count(Animal.id)).where(Animal.active.is_(True), Animal.status != "duplicate")) or 0,
            "animals_archived": db.scalar(select(func.count(Animal.id)).where(Animal.status == "archived")) or 0,
            "sources_enabled": db.scalar(select(func.count(Shelter.id)).where(Shelter.import_enabled.is_(True))) or 0,
            "last_import": (lambda x: x.isoformat() if x else None)(db.scalar(select(func.max(ImportRun.finished_at))))
        }

@app.get("/api/shelters")
def shelters(region: Optional[str] = None, q: Optional[str] = None):
    with SessionLocal() as db:
        stmt = select(Shelter).where(Shelter.active.is_(True))
        if region: stmt = stmt.where(Shelter.region == region)
        if q: stmt = stmt.where(Shelter.name.ilike(f"%{q}%"))
        return [serialize(s) for s in db.scalars(stmt.order_by(Shelter.region, Shelter.name)).all()]

@app.get("/api/shelters/{sid}")
def shelter(sid: str):
    with SessionLocal() as db:
        s = db.get(Shelter, sid)
        if not s or not s.active: raise HTTPException(404, "Приют не найден")
        return serialize(s)

@app.get("/api/shelters/{sid}/animals")
def shelter_animals(sid: str, species: Optional[str] = None):
    with SessionLocal() as db:
        if not db.get(Shelter, sid): raise HTTPException(404, "Приют не найден")
        stmt = select(Animal).where(
            Animal.shelter_id == sid,
            Animal.active.is_(True),
            Animal.status != "duplicate"
        )
        normalized_species = (species or "").strip().lower()
        aliases = {
            "cats": "cat", "кошки": "cat", "кошка": "cat", "cat": "cat",
            "dogs": "dog", "собаки": "dog", "собака": "dog", "dog": "dog",
            "other": "other", "другое": "other"
        }
        if normalized_species in aliases:
            stmt = stmt.where(Animal.species == aliases[normalized_species])
        rows=db.scalars(stmt.order_by(Animal.created_at.desc())).all()
        out=[]
        for a in rows:
            d=serialize(a); d["photos"]=photo_urls(db,a.id); out.append(d)
        return out

def _catalog_record_is_real(a):
    """Final safety net: only animal profiles enter the public catalog."""
    text=normalize(f"{a.name or ''} {a.description or ''}")
    url=(a.original_url or "").lower()
    news_terms=("благодарим","спасибо","новости","мероприят","выставк","акция",
                "субботник","день открытых дверей","волонт","помощь приют",
                "закуп","поставка","корм","сбор средств","донат","праздник",
                "поздрав","отчет","отчёт","стикер","скачали","компания")
    if any(t in text for t in news_terms):
        return False
    if re.search(r"/(?:news|novosti|blog|articles?|posts?)(?:/|$)", url, re.I):
        return False
    profile_terms=("возраст","год рождения","пол","окрас","порода","стерилиз",
                   "кастрац","вакцинир","привит","ищет дом","ищет хозя",
                   "пристройство","куратор")
    animal_terms=("собак","собака","пёс","пес","щен","кошк","кошка","кот",
                  "котён","котен","dog","cat")
    return any(t in text for t in profile_terms) and any(t in text for t in animal_terms)

@app.get("/api/animals")
def animals(species: Optional[str] = None, region: Optional[str] = None, city: Optional[str] = None,
            q: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(24, ge=1, le=100)):
    with SessionLocal() as db:
        stmt = select(Animal).join(Shelter, Shelter.id == Animal.shelter_id).where(
            Animal.active.is_(True), Animal.status != "duplicate"
        )
        if species: stmt = stmt.where(Animal.species == species)
        if region: stmt = stmt.where(Shelter.region == region)
        if city: stmt = stmt.where(or_(Animal.city.ilike(f"%{city}%"), Shelter.city.ilike(f"%{city}%")))
        if q:
            like=f"%{q}%"
            stmt = stmt.where(or_(Animal.name.ilike(like), Animal.description.ilike(like),
                                  Animal.breed.ilike(like), Animal.color.ilike(like)))
        candidates=db.execute(stmt.order_by(Animal.created_at.desc()).limit(1000)).scalars().all()
        rows=[a for a in candidates if _catalog_record_is_real(a)]
        total=len(rows)
        start=(page-1)*limit
        rows=rows[start:start+limit]
        items=[]
        for a in rows:
            data=serialize(a); data["photos"]=photo_urls(db,a.id)
            items.append({"animal":data,"shelter":serialize(db.get(Shelter,a.shelter_id))})
        pages=(total+limit-1)//limit
        return {"items":items,"page":page,"limit":limit,"total":total,"pages":pages}

@app.get("/api/animals/{animal_id}")
def animal(animal_id: int):
    with SessionLocal() as db:
        a = db.get(Animal, animal_id)
        if not a: raise HTTPException(404, "Животное не найдено")
        s = db.get(Shelter, a.shelter_id)
        data=serialize(a); data["photos"]=photo_urls(db,a.id); return {"animal": data, "shelter": serialize(s) if s else None}


@app.get("/api/duplicates")
def duplicates(limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        rows=db.scalars(select(Animal).where(Animal.status=="duplicate").order_by(Animal.updated_at.desc()).limit(limit)).all()
        return [{"animal":serialize(a),"duplicate_of":serialize(db.get(Animal,a.duplicate_of_id)) if a.duplicate_of_id else None} for a in rows]

@app.get("/api/import/status")
def import_status(limit: int = Query(50, ge=1, le=200)):
    with SessionLocal() as db:
        return [serialize(x) for x in db.scalars(select(ImportRun).order_by(ImportRun.started_at.desc()).limit(limit)).all()]

@app.get("/api/system")
def system_status():
    with SessionLocal() as db:
        last = db.scalar(select(func.max(ImportRun.finished_at)))
        errors = db.scalar(select(func.count(ImportRun.id)).where(ImportRun.status == "error", ImportRun.started_at > now() - timedelta(hours=24))) or 0
        return {"version": app.version, "cycle": "hourly", "next_cycle_seconds": HOURLY_SECONDS, "last_import": last.isoformat() if last else None, "errors_24h": errors}



@app.get("/api/sources/health")
def source_health():
    with SessionLocal() as db:
        rows=db.scalars(select(Shelter).order_by(Shelter.consecutive_failures.desc(), Shelter.name)).all()
        return [{
            "id":s.id, "name":s.name, "source_type":s.source_type, "source_url":s.source_url,
            "status":s.status, "verified":s.verified, "consecutive_failures":s.consecutive_failures,
            "last_error":s.last_error, "last_import_at":s.last_import_at,
            "last_source_ok_at":s.last_source_ok_at
        } for s in rows]

@app.get("/api/import/summary")
def import_summary(hours:int=Query(24,ge=1,le=168)):
    cutoff=now()-timedelta(hours=hours)
    with SessionLocal() as db:
        runs=db.scalars(select(ImportRun).where(ImportRun.started_at>=cutoff)).all()
        return {
            "hours":hours, "runs":len(runs),
            "successful":sum(r.status=="ok" for r in runs),
            "failed":sum(r.status=="error" for r in runs),
            "created":sum(r.imported or 0 for r in runs),
            "updated":sum(r.updated or 0 for r in runs),
        }


@app.get("/api/animals/{animal_id}/photos")
def animal_photos(animal_id:int):
    with SessionLocal() as db:
        if not db.get(Animal,animal_id): raise HTTPException(404,"Животное не найдено")
        return [{"url":x.url,"sort_order":x.sort_order} for x in db.scalars(select(AnimalPhoto).where(AnimalPhoto.animal_id==animal_id,AnimalPhoto.is_active.is_(True)).order_by(AnimalPhoto.sort_order,AnimalPhoto.id)).all()]


@app.get("/api/sources/discover")
def discover_public_sources():
    """
    Safe source discovery only: public catalog/feed URLs.
    It does not bypass auth, CAPTCHA, robots restrictions, or rate limits.
    """
    seeds = [
        {"name": "РосПриют — Москва и МО", "url": "https://rospriut.ru/shelters/msk/", "kind": "catalog"},
        {"name": "РосПриют — собаки", "url": "https://rospriut.ru/dogs/", "kind": "catalog"},
        {"name": "РосПриют — кошки", "url": "https://rospriut.ru/cats/", "kind": "catalog"},
        {"name": "Мосприют — каталог", "url": "https://mospriut.ru/catalog", "kind": "catalog"},
    ]
    return {
        "safe_sources": seeds,
        "policy": "public_only",
        "rules": [
            "respect robots.txt",
            "respect rate limits",
            "no CAPTCHA bypass",
            "no authentication bypass",
            "keep original source_url",
        ],
    }