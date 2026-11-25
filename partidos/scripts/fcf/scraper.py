#!/usr/bin/env python3
"""
Scraper FCF para un equipo de fútbol base.

Parte de la URL de un partido del equipo, descubre las páginas del grupo
(calendario, resultados, clasificación, equipo, goleadores...) y todas las
actas de los partidos del equipo, y lo guarda en JSON + HTML bruto.

Uso:
    pip install -r requirements.txt
    python scraper.py                 # usa config.json
    python scraper.py --max-pages 60  # límite de páginas
"""
import argparse, json, re, sys, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
SKIP_TYPES = {"jugador", "jugadora", "arbitre", "arbitro", "noticia", "noticies"}


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def parse_start(url):
    """/es/partit/2026-2027/prebenjami-s8/grup-3/jornada-1/a-vs-b"""
    parts = [p for p in urlparse(url).path.split("/") if p]
    lang, tipo, temporada, categoria, grup = parts[:5]
    return {
        "lang": lang,
        "context": f"/{temporada}/{categoria}/{grup}",
        "temporada": temporada,
        "categoria": categoria,
        "grup": grup,
    }


def page_type(path):
    parts = [p for p in path.split("/") if p]
    tipo = parts[1] if len(parts) > 1 else "home"
    if tipo == "competicio" and len(parts) > 5:
        tipo = parts[5]  # resultats, classificacio, calendari...
    return tipo


def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def extract(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    tables = []
    for tb in soup.find_all("table"):
        headers = [clean(th.get_text()) for th in tb.find_all("th")]
        rows = []
        for tr in tb.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            rows.append([
                {
                    "text": clean(td.get_text(" ")),
                    "links": [urljoin(url, a["href"]) for a in td.find_all("a", href=True)],
                    "imgs": [img.get("alt") or img.get("src") for img in td.find_all("img")],
                }
                for td in cells
            ])
        tables.append({"headers": headers, "rows": rows})

    main = soup.find("main") or soup.body or soup
    lines = [clean(l) for l in main.get_text("\n").split("\n")]
    lines = [l for l in lines if l]

    return {
        "title": clean(soup.title.get_text()) if soup.title else "",
        "headings": [clean(h.get_text(" ")) for h in soup.find_all(["h1", "h2", "h3", "h4"])],
        "tables": tables,
        "text_lines": lines,
        "links": sorted({urljoin(url, a["href"]) for a in soup.find_all("a", href=True)}),
    }


def slug_of(path, query=""):
    raw = path.strip("/") + (("_" + query) if query else "")
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", raw) or "index"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    start = cfg["start_url"]
    team = cfg["team_slug"]
    delay = cfg.get("delay_seconds", 2.0)
    max_pages = args.max_pages or cfg.get("max_pages", 150)
    ctx = parse_start(start)
    host = urlparse(start).netloc

    out = ROOT / cfg.get("output_dir", "data")
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "raw").mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({
        "User-Agent": cfg.get("user_agent", "Mozilla/5.0 (uso personal, familia PB Anguera)"),
        "Accept-Language": "es,ca;q=0.8",
    })

    def allowed(link):
        u = urlparse(link)
        if u.netloc and u.netloc != host:
            return False
        path = u.path
        if not path.startswith(f"/{ctx['lang']}/"):
            return False
        tipo = page_type(path)
        if tipo in SKIP_TYPES:
            return False
        if ctx["context"] in path:
            # partidos: solo los del equipo
            return tipo != "partit" or team in path
        # páginas del equipo fuera del contexto (ficha de club/equipo)
        return team in path and tipo != "partit"

    # Semillas: resultados y clasificación de cada jornada + otras vistas del grupo
    base = f"https://{host}/{ctx['lang']}/competicio{ctx['context']}"
    seeds = [start]
    for j in range(1, cfg.get("max_jornadas", 30) + 1):
        seeds += [f"{base}/{v}?jornada={j}" for v in ("calendari", "resultats", "classificacio", "gols", "sancions")]
    seeds += [f"{base}/{v}" for v in cfg.get("extra_views", [])]
    queue, seen, index = deque(seeds), set(), []
    misses = 0
    while queue and len(seen) < max_pages:
        url = queue.popleft().split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        try:
            r = s.get(url, timeout=30)
        except requests.RequestException as e:
            print(f"  ! {url}: {e}", file=sys.stderr)
            continue
        print(f"[{r.status_code}] {url}")
        if r.status_code == 403:
            print("  ! La web ha devuelto 403 (bloqueo). Para y prueba más tarde o desde otra red.")
            break
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            time.sleep(delay)
            continue

        pu = urlparse(url)
        path = pu.path
        tipo = page_type(path)
        name = slug_of(path, pu.query)
        (out / "raw" / f"{name}.html").write_text(r.text, encoding="utf-8")
        data = extract(r.text, url)
        data.update({"url": url, "type": tipo,
                     "fetched_at": datetime.now(timezone.utc).isoformat()})
        (out / "pages" / tipo).mkdir(exist_ok=True)
        (out / "pages" / tipo / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append({"url": url, "type": tipo, "title": data["title"],
                      "file": f"pages/{tipo}/{name}.json"})

        for link in data["links"]:
            link = link.split("#")[0]
            if link not in seen and allowed(link):
                queue.append(link)
        time.sleep(delay)

    index.sort(key=lambda x: (x["type"], x["url"]))
    (out / "index.json").write_text(json.dumps({
        "team": team, **ctx, "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": index,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    by_type = {}
    for p in index:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    print("\nHecho. Páginas guardadas por tipo:", by_type)
    print(f"Índice: {out / 'index.json'}")


if __name__ == "__main__":
    main()
