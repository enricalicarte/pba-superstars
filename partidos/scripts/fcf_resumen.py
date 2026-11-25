#!/usr/bin/env python3
"""Convierte las actas descargadas de la FCF (carpeta data/ del scraper) en partidos/fcf.json.

Solo publica lo necesario para la web y sin datos personales de más:
- fecha, hora, campo, equipos, escudos y resultado de cada jornada del Anguera;
- goles del Anguera con minuto, dorsal y NOMBRE DE PILA del goleador (nunca apellidos);
- goles del rival solo con el minuto (sin nombres de los niños del otro equipo).

Uso:  python fcf_resumen.py RUTA_A_data  [salida.json]
"""
import json, re, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path

TEAM_KEY = 'anguera'


def norm(s):
    return unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode().lower()


def nombre_pila(full):
    """'ESCOLANO TORNER, GERARD' -> 'Gerard' ; 'NICOLAS ITIRO' -> 'Nicolas' ; 'IAN' -> 'Ian'."""
    full = (full or '').strip()
    first = full.split(',', 1)[1].strip() if ',' in full else full
    first = first.split()[0] if first else ''
    return first[:1].upper() + first[1:].lower() if first else ''


def crests(raw_html):
    out = {}
    for alt, src in re.findall(r'<img alt="([^"]+)"[^>]*?src="(https://files\.fcf\.cat/escudos/[^"]+)"', raw_html or ''):
        out.setdefault(alt.replace('&amp;', '&'), src)
    return out


def parse_acta(lines, raw_html=''):
    L = [str(x).strip() for x in lines]
    def after(label):
        try:
            return L[L.index(label) + 1]
        except ValueError:
            return ''
    jornada = int(after('Jornada') or 0)
    fecha, hora, campo = after('DATA:'), after('HORARI:'), after('ESTADI:')
    # Marcador: "<local>", "<visitante>", "<g1>", "-", "<g2>", "<ESTADO>"
    home = away = status = ''
    score = None
    for i in range(len(L) - 5):
        if L[i + 5] in ('FINALITZAT', 'PENDENT', 'SUSPÈS', 'AJORNAT', 'EN JOC') and L[i + 3] == '-':
            home, away, status = L[i], L[i + 1], L[i + 5]
            if L[i + 2].isdigit() and L[i + 4].isdigit():
                score = [int(L[i + 2]), int(L[i + 4])]
            break
    ang_home = TEAM_KEY in norm(home)
    # Goles: "a - b", "(", "min", "')", "dorsal", "NOMBRE"
    goals, prev = [], (0, 0)
    try:
        start = L.index('GOLS')
    except ValueError:
        start = len(L)
    i = start
    while i < len(L) - 5:
        m = re.fullmatch(r'(\d+) - (\d+)', L[i])
        if m and L[i + 1] == '(' and L[i + 3] == "')":
            a, b = int(m[1]), int(m[2])
            if (a, b) <= prev and goals:   # vuelve a empezar la lista: fin
                break
            home_scored = a > prev[0]
            ours = home_scored == ang_home
            g = {'min': int(L[i + 2]) if L[i + 2].isdigit() else None, 'score': f'{a}-{b}', 'ours': ours}
            if ours:
                g['dorsal'] = L[i + 4] if L[i + 4].isdigit() else ''
                g['name'] = nombre_pila(L[i + 5])
            goals.append(g)
            prev = (a, b)
            i += 6
            continue
        if goals and L[i] in ('TITULARS', 'SUPLENTS'):
            break
        i += 1
    try:
        d = datetime.strptime(fecha, '%d.%m.%Y')
        iso = d.strftime('%Y-%m-%d')
    except ValueError:
        iso = None
    cr = crests(raw_html)
    return {
        'jornada': jornada, 'date': iso, 'time': hora.replace('h', '').replace('.', ':') if hora else '',
        'stadium': campo.title() if campo else '', 'home': home, 'away': away,
        'homeCrest': cr.get(home, ''), 'awayCrest': cr.get(away, ''),
        'angueraHome': ang_home, 'status': status, 'score': score, 'goals': goals,
    }


def main():
    data = Path(sys.argv[1] if len(sys.argv) > 1 else 'data')
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / 'fcf.json'
    actas = {}
    for p in sorted((data / 'pages' / 'partit').glob('*.json')):
        d = json.loads(p.read_text(encoding='utf-8'))
        raw = data / 'raw' / (p.stem + '.html')
        m = parse_acta(d.get('text_lines', []), raw.read_text(encoding='utf-8') if raw.exists() else '')
        if m['jornada'] and m['home'] and (TEAM_KEY in norm(m['home']) or TEAM_KEY in norm(m['away'])):
            actas[m['jornada']] = m
    if not actas:
        print('Aviso: no hay actas del Anguera; no se toca fcf.json', file=sys.stderr)
        return 1
    idx = json.loads((data / 'index.json').read_text(encoding='utf-8')) if (data / 'index.json').exists() else {}
    res = {
        'updated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'competition': 'Prebenjamí S8 · Grup 3', 'season': idx.get('temporada', ''),
        'group': 'T26/27 S8', 'matches': [actas[k] for k in sorted(actas)],
    }
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    played = [m for m in res['matches'] if m['score']]
    print(f'{len(res["matches"])} jornadas, {len(played)} jugadas -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
