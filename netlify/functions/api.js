const { neon } = require("@neondatabase/serverless");

function getSql() {
  const url = process.env.DATABASE_URL || process.env.NETLIFY_DATABASE_URL;
  if (!url) return null;
  return neon(url);
}

const NEWS_TERMS = [
  "благодарим","спасибо","новости","мероприят","выставк","акция",
  "субботник","день открытых дверей","волонт","помощь приют",
  "закуп","поставка","корм","сбор средств","донат","праздник",
  "поздрав","отчет","отчёт","стикер","скачали","компания"
];
const PROFILE_TERMS = [
  "возраст","год рождения","пол","окрас","порода","стерилиз",
  "кастрац","вакцинир","привит","ищет дом","ищет хозя",
  "пристройство","куратор"
];
const ANIMAL_TERMS = [
  "собак","собака","пёс","пес","щен","кошк","кошка","кот",
  "котён","котен","dog","cat"
];
const STRUCTURED = new Set(["rospriut_dog","rospriut_cat","pechatniki","yuna","dorinvest"]);

function normalize(v="") {
  return String(v).toLowerCase().replace(/[^\p{L}\p{N}_\s-]/gu," ").replace(/\s+/g," ").trim();
}
function realAnimal(a) {
  const text = normalize(`${a.name || ""} ${a.description || ""}`);
  const url = String(a.original_url || "").toLowerCase();
  if (NEWS_TERMS.some(x => text.includes(x))) return false;
  if (/\/(news|novosti|blog|articles?|posts?)(\/|$)/i.test(url)) return false;
  if (STRUCTURED.has(a.source_type) && ["dog","cat"].includes(a.species)) return true;
  return PROFILE_TERMS.some(x => text.includes(x)) && ANIMAL_TERMS.some(x => text.includes(x));
}
function photoRows(rows, id) {
  return rows.filter(x => Number(x.animal_id) === Number(id)).sort((a,b) => (a.sort_order||0)-(b.sort_order||0) || a.id-b.id).map(x=>x.url);
}
function json(body, status=200) {
  return {
    statusCode: status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=30, s-maxage=60",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,OPTIONS"
    },
    body: JSON.stringify(body)
  };
}
function pathOf(event) {
  let p = event.path || "/";
  p = p.replace(/^.*\/.netlify\/functions\/api/, "");
  p = p.replace(/^\/api(?=\/|$)/, "");
  if (!p || p === "/") {
    const q = event.queryStringParameters?.path;
    if (q) p = q.startsWith("/") ? q : "/" + q;
  }
  return p || "/";
}

exports.handler = async (event) => {
  const rawDbUrl = process.env.DATABASE_URL || process.env.NETLIFY_DATABASE_URL || "";
  const dbHost = (() => { try { return rawDbUrl ? new URL(rawDbUrl.replace(/^postgres(ql)?:\/\//, "https://")).hostname : null; } catch (_) { return null; } })();
  const sql = getSql();
  if (!sql) {
    return json({ok:false,error:"DATABASE_URL is not configured",database_configured:false},500);
  }
  if (event.httpMethod === "OPTIONS") {
    return {
      statusCode: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET,OPTIONS",
        "access-control-allow-headers": "Content-Type"
      },
      body: ""
    };
  }
  try {
    const path = pathOf(event);
    const q = event.queryStringParameters || {};

    if (path === "/health") {
      const r = await sql`select count(*)::int as shelters from shelters`;
      const a = await sql`select count(*)::int as animals from animals where active=true and status <> 'duplicate'`;
      return json({ok:true,time:new Date().toISOString(),database_configured:true,database_host:dbHost,shelters:r[0]?.shelters||0,animals:a[0]?.animals||0});
    }

    if (path === "/stats") {
      const rows = await sql`
        select a.*, s.name as shelter_name, s.region as shelter_region
        from animals a join shelters s on s.id=a.shelter_id
        where a.active = true and a.status <> 'duplicate'
        order by a.created_at desc
        limit 5000
      `;
      const real = rows.filter(realAnimal);
      const sh = await sql`select count(*)::int as n from shelters where active=true`;
      const vs = await sql`select count(*)::int as n from shelters where active=true and verified=true`;
      const src = await sql`select count(*)::int as n from shelters where import_enabled=true`;
      const ar = await sql`select count(*)::int as n from animals where status='archived'`;
      const last = await sql`select max(finished_at) as last_import from import_runs`;
      return json({
        shelters: sh[0]?.n||0,
        verified_shelters: vs[0]?.n||0,
        animals_active: real.length,
        dogs_active: real.filter(a=>a.species==="dog").length,
        cats_active: real.filter(a=>a.species==="cat").length,
        animals_archived: ar[0]?.n||0,
        sources_enabled: src[0]?.n||0,
        last_import: last[0]?.last_import || null
      });
    }

    if (path === "/animals") {
      const rows = await sql`
        select a.*, s.id as shelter_id_join, s.name as shelter_name, s.region as shelter_region,
               s.city as shelter_city, s.website as shelter_website, s.verified as shelter_verified
        from animals a join shelters s on s.id=a.shelter_id
        where a.active=true and a.status <> 'duplicate'
        order by a.created_at desc
        limit 5000
      `;
      let items = rows.filter(realAnimal);
      const species = q.species || "";
      const region = q.region || "";
      const search = normalize(q.q || "");
      if (species) items = items.filter(a=>a.species===species);
      if (region) items = items.filter(a=>a.shelter_region===region);
      if (search) items = items.filter(a=>normalize(`${a.name} ${a.description||""} ${a.breed||""} ${a.color||""}`).includes(search));
      const total = items.length;
      const limit = Math.min(Math.max(Number(q.limit||24),1),100);
      const page = Math.max(Number(q.page||1),1);
      const pageRows = items.slice((page-1)*limit, page*limit);
      const ids = pageRows.map(a=>a.id);
      const photos = ids.length ? await sql`select * from animal_photos where animal_id = any(${ids}) and is_active=true order by sort_order,id` : [];
      return json({
        items: pageRows.map(a=>({
          animal: {
            ...a,
            shelter_id: a.shelter_id_join,
            photos: photoRows(photos,a.id)
          },
          shelter: {
            id:a.shelter_id_join,name:a.shelter_name,region:a.shelter_region,
            city:a.shelter_city,website:a.shelter_website,verified:a.shelter_verified
          }
        })),
        page,limit,total,pages:Math.ceil(total/limit)
      });
    }

    const animalMatch = path.match(/^\/animals\/(\d+)$/);
    if (animalMatch) {
      const id = Number(animalMatch[1]);
      const rows = await sql`
        select a.*, s.id as shelter_id_join, s.name as shelter_name, s.region as shelter_region,
               s.city as shelter_city, s.website as shelter_website, s.verified as shelter_verified
        from animals a join shelters s on s.id=a.shelter_id
        where a.id=${id} limit 1
      `;
      const a=rows[0];
      if (!a || !a.active || a.status==="duplicate" || !realAnimal(a)) return json({detail:"Животное не найдено"},404);
      const photos=await sql`select * from animal_photos where animal_id=${id} and is_active=true order by sort_order,id`;
      return json({
        animal:{...a,shelter_id:a.shelter_id_join,photos:photos.map(x=>x.url)},
        shelter:{id:a.shelter_id_join,name:a.shelter_name,region:a.shelter_region,city:a.shelter_city,website:a.shelter_website,verified:a.shelter_verified}
      });
    }

    if (path === "/shelters") {
      const shelters = await sql`
        select s.id,s.name,s.region,s.city,s.address,s.website,s.source_url,s.verified,s.active,
               (select count(*)::int from animals a
                where a.shelter_id=s.id and a.active=true and a.status<>'duplicate'
                  and a.species in ('dog','cat')) as animal_count
        from shelters s
        where s.active=true
        order by s.region,s.name
      `;
      const badShelterTerms=["благодарим","спасибо","новости","мероприят","выставк","день открытых дверей","стикер","скачали","компания"];
      let out=shelters.filter(s=>{
        const t=normalize(s.name||"");
        const u=String(s.website||s.source_url||"").toLowerCase();
        return !badShelterTerms.some(x=>t.includes(x)) && !/\/(news|novosti|blog|articles?|posts?)(\/|$)/i.test(u);
      });
      if(q.region) out=out.filter(s=>s.region===q.region);
      if(q.q){
        const needle=normalize(q.q);
        out=out.filter(s=>normalize(s.name).includes(needle));
      }
      return json(out);
    }

    const shelterMatch = path.match(/^\/shelters\/([^/]+)$/);
    if (shelterMatch) {
      const id=decodeURIComponent(shelterMatch[1]);
      const rows=await sql`select * from shelters where id=${id} and active=true limit 1`;
      if(!rows[0]) return json({detail:"Приют не найден"},404);
      return json(rows[0]);
    }

    const shelterAnimals = path.match(/^\/shelters\/([^/]+)\/animals$/);
    if (shelterAnimals) {
      const id=decodeURIComponent(shelterAnimals[1]);
      const species=q.species||"";
      const rows=await sql`
        select a.* from animals a where a.shelter_id=${id} and a.active=true and a.status<>'duplicate'
        order by a.created_at desc limit 5000
      `;
      let real=rows.filter(realAnimal);
      if(species) real=real.filter(a=>a.species===species);
      const ids=real.map(a=>a.id);
      const photos=ids.length?await sql`select * from animal_photos where animal_id=any(${ids}) and is_active=true order by sort_order,id`:[];
      return json(real.map(a=>({...a,photos:photoRows(photos,a.id)})));
    }

    return json({detail:"API route not found"},404);
  } catch (err) {
    console.error(err);
    return json({ok:false,error:"Internal server error"},500);
  }
};
