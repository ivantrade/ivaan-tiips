#!/usr/bin/env python3
"""
Painel de Análise Esportiva — coleta diária
=============================================
Roda todo dia via GitHub Actions e gera output/index.html (publicado pelo GitHub Pages).

Duas camadas, de propósito:
  - SÓLIDA:  footballdb.com (NFL) -> tabelas HTML de verdade, pandas.read_html funciona bem.
  - EXPERIMENTAL: aiscore.com (chutes/chutes no alvo no futebol) -> não é tabela HTML simples,
    a extração é por padrão de texto e PODE quebrar se o site mudar o layout. Por isso cada
    função tem try/except: se uma fonte falhar, o resto do relatório continua saindo normal,
    só aquele bloco aparece como "indisponível hoje".

Não precisa mexer neste arquivo pra usar. Se algum bloco começar a aparecer sempre como
"indisponível", me chame de volta na conversa com o Claude e mandamos ajuste.
"""

import re
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
TIMEOUT = 20

FUSO_BR = ZoneInfo("America/Sao_Paulo")


def log_erro(fonte: str, e: Exception):
    print(f"[AVISO] Falha em '{fonte}': {e}")


# ---------------------------------------------------------------------------
# CAMADA SÓLIDA — NFL via footballdb.com (tabelas HTML reais)
# ---------------------------------------------------------------------------

def nfl_defesa(tipo: str, url: str):
    """
    tipo: 'corrida' ou 'passe'. Lê a tabela de defesa da footballdb e devolve
    lista ordenada [{'time':..., 'jardas_jogo':..., 'td_permitidos':...}, ...]
    do PIOR pro MELHOR (quem mais cede é quem interessa pra apostas de ataque).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        tabelas = pd.read_html(resp.text)
        alvo = max(tabelas, key=lambda t: t.shape[0])  # a maior tabela da página é a que queremos

        cols = {c: str(c).strip().lower() for c in alvo.columns}

        def achar_coluna(*pistas):
            for col, nome in cols.items():
                if all(p in nome for p in pistas):
                    return col
            return None

        col_time = achar_coluna("team") or alvo.columns[0]
        col_jardas = achar_coluna("yds/g") or achar_coluna("avg") or achar_coluna("yds", "g")
        col_td = achar_coluna("td")

        linhas = []
        for _, row in alvo.iterrows():
            time_nome = str(row[col_time]).strip()
            if not time_nome or time_nome.lower() in ("team", "nan"):
                continue
            try:
                jardas = float(str(row[col_jardas]).replace(",", ""))
            except Exception:
                jardas = None
            try:
                td = int(float(str(row[col_td]).replace(",", "")))
            except Exception:
                td = None
            linhas.append({"time": time_nome, "jardas_jogo": jardas, "td_permitidos": td})

        linhas = [l for l in linhas if l["jardas_jogo"] is not None]
        linhas.sort(key=lambda l: l["jardas_jogo"], reverse=True)  # pior defesa primeiro
        return linhas
    except Exception as e:
        log_erro(f"NFL defesa {tipo}", e)
        traceback.print_exc()
        return None


def coletar_nfl():
    return {
        "defesa_corrida": nfl_defesa(
            "corrida",
            "https://www.footballdb.com/statistics/nfl/team-stats/defense-rushing/2025/regular-season",
        ),
        "defesa_passe": nfl_defesa(
            "passe",
            "https://www.footballdb.com/statistics/nfl/team-stats/defense-passing/2025/regular-season",
        ),
    }


# ---------------------------------------------------------------------------
# CAMADA EXPERIMENTAL — futebol via aiscore.com (extração por padrão de texto)
# ---------------------------------------------------------------------------

LIGAS_FUTEBOL = {
    "Brasileirão Série A": "https://m.aiscore.com/tournament-campeonato-brasileiro/r8lk2dil5t0736d/teamshots",
    "Brasileirão Série B": "https://m.aiscore.com/tournament-brazilian-serie-b/g63kv9il9tz7ezv/teamshots",
    "Liga MX": "https://m.aiscore.com/tournament-mexico-liga-mx/2j374oixwu4qo6d/teamshots/o17pji06gpa67jw",
    "MLS": "https://m.aiscore.com/tournament-mls-liga/w34kgmi82i1ko92/teamshots/r8lk2dieexcl736",
    "Championship (Inglaterra)": "https://m.aiscore.com/en/tournament-sunderland-a.f.c-queens-park-rangers/8vrqwnin9sjqn2o/teamshots",
    "Bundesliga": "https://m.aiscore.com/tournament-bundesliga/1edq09ignayqxgo/teamshots",
    "Copa Libertadores": "https://m.aiscore.com/tournament-conmebol-copa-libertadores/8vmqy9iolcek9r3/teamshots",
}

# Padrão: nome do time (letras/acentos/espaços) seguido de um número decimal (a média).
PADRAO_LINHA = re.compile(
    r"([A-ZÀ-Ý][A-Za-zÀ-ÿ0-9'\.\- ]{2,40}?)\s+(\d{1,2}\.\d{1,2})\b"
)


def chutes_por_liga(nome_liga: str, url: str, limite=8):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        texto = re.sub(r"<[^>]+>", " ", resp.text)  # tira tags HTML na força bruta
        texto = re.sub(r"\s+", " ", texto)

        vistos = set()
        resultado = []
        for time_nome, valor in PADRAO_LINHA.findall(texto):
            time_nome = time_nome.strip()
            if time_nome.lower() in vistos or len(time_nome) < 3:
                continue
            # filtra lixo comum (menus, versões, etc.) exigindo que pareça nome de time
            if time_nome.lower() in ("shots per", "per game", "aiscore com"):
                continue
            vistos.add(time_nome.lower())
            resultado.append({"time": time_nome, "chutes_jogo": float(valor)})
            if len(resultado) >= limite:
                break

        return resultado if resultado else None
    except Exception as e:
        log_erro(f"Futebol - {nome_liga}", e)
        return None


def coletar_futebol():
    dados = {}
    for liga, url in LIGAS_FUTEBOL.items():
        dados[liga] = chutes_por_liga(liga, url)
    return dados


# ---------------------------------------------------------------------------
# RELATÓRIO HTML
# ---------------------------------------------------------------------------

def bloco_nfl_defesa(titulo: str, linhas, unidade_label: str):
    if not linhas:
        return f"<h3>{titulo}</h3><p class='indisponivel'>Indisponível hoje — a fonte pode ter mudado de layout.</p>"
    linhas_html = "\n".join(
        f"<tr><td>{i+1}</td><td>{l['time']}</td><td class='num'>{l['jardas_jogo']:.1f}</td>"
        f"<td class='num'>{l['td_permitidos'] if l['td_permitidos'] is not None else '—'}</td></tr>"
        for i, l in enumerate(linhas[:10])
    )
    return f"""
    <h3>{titulo}</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Time</th><th class="num">{unidade_label}</th><th class="num">TD cedidos</th></tr></thead>
      <tbody>{linhas_html}</tbody>
    </table></div>
    """


def bloco_futebol(liga: str, linhas):
    if not linhas:
        return f"<h3>{liga}</h3><p class='indisponivel'>Indisponível hoje — camada experimental, fonte pode ter mudado.</p>"
    linhas_html = "\n".join(
        f"<tr><td>{i+1}</td><td>{l['time']}</td><td class='num'>{l['chutes_jogo']:.1f}</td></tr>"
        for i, l in enumerate(linhas)
    )
    return f"""
    <h3>{liga}</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Time</th><th class="num">Chutes/jogo</th></tr></thead>
      <tbody>{linhas_html}</tbody>
    </table></div>
    """


# ---------------------------------------------------------------------------
# BASQUETE — ainda sem temporada rolando em setembro/2026, então isto é só um
# aviso informativo com as datas reais de início. Quando cada liga começar,
# volte aqui pra transformar isto numa coleta de verdade (mesmo padrão acima).
# ---------------------------------------------------------------------------

INICIO_TEMPORADAS_BASQUETE = [
    ("NBA", "20 de outubro de 2026"),
    ("NBB (Brasil)", "geralmente outubro — confirmar data oficial mais perto da data"),
    ("EuroLiga", "geralmente final de setembro/início de outubro — confirmar data oficial"),
]


def bloco_basquete():
    linhas_html = "\n".join(
        f"<tr><td>{liga}</td><td>{data}</td></tr>" for liga, data in INICIO_TEMPORADAS_BASQUETE
    )
    return f"""
    <p class="indisponivel">Nenhuma liga de basquete relevante está em temporada ainda —
    não é falha de fonte de dados, o jogo não começou. "Chance de vencer o 1º quarto/1º tempo"
    é um mercado de aposta calculado por casas com modelo próprio; assim que a temporada
    começar, dá pra montar uma leitura baseada no histórico de cada time (não é a mesma coisa
    que a probabilidade oficial da casa, mas é um indicador real).</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Liga</th><th>Início da temporada 26/27</th></tr></thead>
      <tbody>{linhas_html}</tbody>
    </table></div>
    """


def gerar_html(nfl, futebol):
    agora = datetime.now(FUSO_BR).strftime("%d/%m/%Y às %H:%M")

    nfl_html = bloco_nfl_defesa(
        "Piores defesas de corrida (2025) — alvo pra RB/prop de corrida",
        nfl["defesa_corrida"], "Jardas/jogo cedidas"
    ) + bloco_nfl_defesa(
        "Piores defesas de passe (2025) — alvo pra WR/TE",
        nfl["defesa_passe"], "Jardas/jogo cedidas"
    )

    futebol_html = "".join(bloco_futebol(liga, linhas) for liga, linhas in futebol.items())

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ivaan Tips — atualizado automaticamente</title>
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="theme-color" content="#0e1410">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Ivaan Tips">
<script>
  if ("serviceWorker" in navigator) {{
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {{}}));
  }}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#eef1ea; --surface:#e2e7db; --text:#16201a; --text-muted:#57614f;
    --accent:#8a6314; --border:#c7cebc;
    --font-display:'Newsreader',Georgia,serif; --font-body:'IBM Plex Sans',sans-serif; --font-mono:'IBM Plex Mono',monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#0e1410; --surface:#161e18; --text:#e9ece4; --text-muted:#97a08d; --accent:#d2a94a; --border:#2a342c;
    }}
  }}
  :root[data-theme="dark"] {{ --bg:#0e1410; --surface:#161e18; --text:#e9ece4; --text-muted:#97a08d; --accent:#d2a94a; --border:#2a342c; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:var(--font-body); line-height:1.55; }}
  main {{ max-width:820px; margin:0 auto; padding:3rem 1.4rem 5rem; }}
  h1 {{ font-family:var(--font-display); font-weight:600; font-size:1.7rem; margin-bottom:0.3rem; }}
  .meta {{ color:var(--text-muted); font-size:0.9rem; margin-bottom:2.6rem; }}
  h2 {{ font-family:var(--font-display); font-weight:600; font-size:1.35rem; border-bottom:1px solid var(--border); padding-bottom:0.5rem; margin-top:2.6rem; }}
  h3 {{ font-size:0.95rem; font-weight:600; margin:1.8rem 0 0.6rem; }}
  .table-wrap {{ overflow-x:auto; border-bottom:1px solid var(--border); }}
  table {{ border-collapse:collapse; width:100%; font-size:0.88rem; min-width:420px; }}
  th, td {{ text-align:left; padding:0.45rem 0.8rem 0.45rem 0; white-space:nowrap; border-bottom:1px solid var(--border); }}
  th {{ color:var(--text-muted); font-size:0.75rem; }}
  td.num, th.num {{ font-family:var(--font-mono); text-align:right; }}
  p.indisponivel {{ color:var(--text-muted); font-size:0.85rem; font-style:italic; }}
  footer {{ margin-top:3rem; padding-top:1rem; border-top:1px solid var(--border); color:var(--text-muted); font-size:0.8rem; }}
</style>
</head>
<body>
<main>
  <h1>Ivaan Tips</h1>
  <div class="meta">Atualizado automaticamente todo dia · última atualização: {agora} (Brasília)</div>

  <h2>NFL — matchups da defesa</h2>
  {nfl_html}

  <h2>Futebol — chutes por jogo (camada experimental)</h2>
  {futebol_html}

  <h2>Basquete</h2>
  {bloco_basquete()}

  <footer>Gerado automaticamente. Blocos com "indisponível" indicam que a fonte mudou e o script precisa de ajuste — não é erro seu.</footer>
</main>
</body>
</html>"""


def main():
    resultado_ia = None
    try:
        from coleta_ia import coletar_via_ia
        resultado_ia = coletar_via_ia()
    except Exception as e:
        print(f"[AVISO] Módulo de IA indisponível, usando modo gratuito: {e}")

    if resultado_ia:
        print("[INFO] Usando coleta via IA (Claude).")
        nfl, futebol = resultado_ia
    else:
        print("[INFO] Usando coleta gratuita (scraping direto).")
        nfl = coletar_nfl()
        futebol = coletar_futebol()

    html = gerar_html(nfl, futebol)

    import os
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    # log simples de diagnóstico (aparece nos logs do GitHub Actions, não no site)
    resumo = {
        "nfl_defesa_corrida_ok": bool(nfl["defesa_corrida"]),
        "nfl_defesa_passe_ok": bool(nfl["defesa_passe"]),
        **{f"futebol_{k}_ok": bool(v) for k, v in futebol.items()},
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
