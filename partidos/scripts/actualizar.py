#!/usr/bin/env python3
"""Lee la carpeta pública de Google Drive y genera partidos/data.json.

Estructura que entiende:
  Carpeta raíz/
    2026-11-22 PB Anguera vs Sant Andreu/   -> un partido (sus vídeos = partes)
    Temporada 2026-27/                       -> grupo con partidos dentro
    Amistoso.mp4                             -> vídeo suelto = partido de un vídeo
La fecha se saca del nombre si empieza por AAAA-MM-DD o DD-MM-AAAA (vale / . _ -).
No necesita claves: usa la vista pública de la carpeta (tiene que estar compartida
como "Cualquier persona con el enlace").
"""
import html, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone

ROOT_FOLDER_ID = '1u0bCn2u0GdQ0likwX8xcKtbUROuJY2u0'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data.json')
VIDEO_EXT = re.compile(r'\.(mp4|mov|m4v|avi|mkv|webm|3gp|mts|wmv)$', re.I)
ENTRY = re.compile(
    r'<div class="flip-entry" id="entry-([\w-]+)".*?<a href="([^"]+)"(.*?)'
    r'<div class="flip-entry-title">(.*?)</div>', re.S)
IMG = re.compile(r'<img src="([^"]*)"')


def fetch(folder_id):
    url = 'https://drive.google.com/embeddedfolderview?id=' + folder_id
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (partidos-bot)', 'Accept-Language': 'es'})
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # reintenta errores puntuales
            if intento == 2:
                raise
            time.sleep(3)


def listar(folder_id):
    folders, videos = [], []
    for fid, href, mid, title in ENTRY.findall(fetch(folder_id)):
        im = IMG.search(mid)
        icon = im.group(1) if im else ''
        name = html.unescape(re.sub(r'<[^>]+>', '', title)).strip()
        if '/folders/' in href:
            folders.append({'id': fid, 'name': name})
        elif VIDEO_EXT.search(name) or 'video' in (icon or ''):
            videos.append({'id': fid, 'name': name, 'size': 0})
    key = lambda x: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', x['name'])]
    return sorted(folders, key=key), sorted(videos, key=key)


def _ms(y, mo, d):
    try:
        return int(datetime(y, mo, d, 12, tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def fecha(name):
    """Fecha al principio del nombre (AAAA-MM-DD / DD-MM-AAAA) -> (ms, resto del nombre)."""
    m = re.match(r'\s*(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})', name)
    if m:
        ms = _ms(int(m[1]), int(m[2]), int(m[3]))
    else:
        m = re.match(r'\s*(\d{1,2})[-_./](\d{1,2})[-_./](\d{2,4})', name)
        if m:
            y = int(m[3]); y = 2000 + y if y < 100 else y
            ms = _ms(y, int(m[2]), int(m[1]))
        else:
            m = re.match(r'\s*(20\d{2})(\d{2})(\d{2})(?!\d)', name)
            ms = _ms(int(m[1]), int(m[2]), int(m[3])) if m else None
    if not m or ms is None:
        return compacta(name), name
    title = re.sub(r'^[\s\-_·|.:]+', '', name[m.end():]).strip() or name
    return ms, title


def compacta(text):
    """Busca una fecha AAAAMMDD dentro de un texto (p. ej. VID_20260207_1.mp4)."""
    for m in re.finditer(r'(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)', text):
        ms = _ms(int(m[1]), int(m[2]), int(m[3]))
        if ms:
            return ms
    return None


def temporada(text):
    """'T25/26 S7' -> 26 ; 'Copa 25/26' -> 26 ; 'Temporada 2026-27' -> 27."""
    m = re.search(r'(\d{2,4})\s*[/-]\s*(\d{2,4})', text or '')
    if m:
        return int(m[2][-2:])
    m = re.search(r'(?<!\d)(?:20)?(\d{2})(?!\d)', text or '')
    return int(m[1]) if m else 0


def partido(name, pid, videos, group, orden):
    ms, title = fecha(name)
    if ms is None:
        ms = next((d for d in (compacta(v['name']) for v in videos) if d), None)
    title = title.replace('_', ' ').strip()
    jornada = None
    m = re.match(r'\s*J\s?(\d{1,2})(?!\d)\s*[-–:·]?\s*', title, re.I)
    if m:
        jornada, title = int(m[1]), title[m.end():].strip() or title
    score = None
    m = re.search(r'\(\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})\s*\)', title)
    if m:
        score, title = f'{m[1]}-{m[2]}', (title[:m.start()] + title[m.end():]).strip()
    return {'id': pid, 'title': title, 'group': group, 'date': ms, 'jornada': jornada, 'score': score,
            'season': temporada(group) or temporada(name), 'orden': orden, 'videos': videos}


def recorrer(folder_id, group, depth, out, root=False):
    folders, videos = listar(folder_id)
    if root:
        for v in videos:
            out.append(partido(re.sub(r'\.[^.]+$', '', v['name']), v['id'], [v], '', len(out)))
    for f in folders:
        sub_folders, sub_videos = listar(f['id'])
        if sub_videos:
            out.append(partido(f['name'], f['id'], sub_videos, group, len(out)))
        if sub_folders and depth < 3:
            # Carpeta sin vídeos propios = grupo (temporada, torneo...)
            child_group = group if group or sub_videos else f['name']
            recorrer(f['id'], child_group, depth + 1, out)


def main():
    out = []
    recorrer(ROOT_FOLDER_ID, '', 0, out, root=True)
    # Más reciente primero: temporada, jornada, fecha; el resto en el orden de la carpeta
    out.sort(key=lambda m: (m['season'], m['jornada'] or 0, m['date'] or 0, -m['orden']), reverse=True)
    for i, m in enumerate(out):
        m['sort'] = len(out) - i
        del m['orden']
    data = {'updated': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'matches': out}
    if not out:
        print('Aviso: no se ha encontrado ningún vídeo. ¿La carpeta es pública?', file=sys.stderr)
        if os.path.exists(OUT):
            return  # no borra la lista anterior por un fallo puntual
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f'{len(out)} partidos, {sum(len(m["videos"]) for m in out)} vídeos')


if __name__ == '__main__':
    main()
