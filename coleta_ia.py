#!/usr/bin/env python3
"""
Coleta via IA (Claude) — modo opcional e mais caro, porém muito mais confiável.
=================================================================================
Só roda se existir a variável de ambiente ANTHROPIC_API_KEY (uma "chave" que você
mesmo gera em console.anthropic.com e cola nas configurações do GitHub, como
"Secret" — nunca fica visível publicamente).

O que faz: manda o Claude pesquisar na internet, agora mesmo, os dados de touchdown/
defesa da NFL e chutes por jogo nas ligas de futebol, e devolver isso já organizado.
Substitui o scraping por regex do scraper.py — não precisa das duas coisas rodando,
o scraper.py escolhe sozinho qual usar (ver função escolher_coleta() em scraper.py).

Custo: cada execução faz várias buscas na web + processa um volume razoável de texto.
Estimativa: algo entre US$0,15 e US$0,35 por execução, ou seja, por volta de
US$5–10/mês rodando uma vez por dia. Isso é cobrado pela Anthropic direto no seu
cartão vinculado ao console.anthropic.com — não tem relação com este repositório.

Se algo der errado aqui (chave inválida, formato de resposta inesperado, etc), a
função devolve None e o scraper.py cai automaticamente pro modo gratuito (regex).
"""

import os
import re
import json

LIGAS_FUTEBOL_ALVO = [
    "Brasileirão Série A",
    "Brasileirão Série B",
    "Liga MX",
    "MLS",
    "Championship (Inglaterra)",
    "Bundesliga",
    "Copa Libertadores",
]

PROMPT = f"""Você é um analista esportivo profissional preparando dados para apostas.
Pesquise na web AGORA MESMO — não use conhecimento antigo — e monte um relatório
com os dados mais atuais disponíveis. Onde a temporada já estiver avançada, use
os dados da temporada atual; onde a temporada mal começou ou não começou, procure
os dados da última temporada completa e não deixe a categoria vazia por causa disso.

Responda APENAS com um JSON válido, sem nenhum texto antes ou depois, sem marcação
de bloco de código, exatamente neste formato:

{{
  "nfl": {{
    "defesa_corrida": [{{"time": "Nome do time", "jardas_jogo": 000.0, "td_permitidos": 00}}, ...],
    "defesa_passe": [{{"time": "Nome do time", "jardas_jogo": 000.0, "td_permitidos": 00}}, ...]
  }},
  "futebol": {{
    {", ".join(f'"{liga}": [{{"time": "Nome", "chutes_jogo": 00.0}}, ...]' for liga in LIGAS_FUTEBOL_ALVO)}
  }}
}}

Regras importantes:
- "defesa_corrida" e "defesa_passe": até 10 times cada, ORDENADOS DA PIOR DEFESA PRA
  MELHOR (quem mais cede jardas primeiro) — são as defesas mais fracas que interessam
  pra apostas de ataque.
- Cada liga de futebol: até 8 times, ordenados do MAIOR número de chutes por jogo
  pro menor.
- Se não conseguir achar dado confiável pra alguma liga específica, retorne uma
  lista vazia [] pra ela. NUNCA invente número — isso vai ser usado pra apostas reais.
- Não escreva nada fora do JSON.
"""


def coletar_via_ia():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None  # modo IA desligado — scraper.py usa o modo gratuito

    try:
        from anthropic import Anthropic
    except ImportError:
        print("[AVISO] pacote 'anthropic' não instalado — rode 'pip install anthropic'.")
        return None

    try:
        client = Anthropic(api_key=api_key)

        resposta = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=6000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": PROMPT}],
        )

        texto = "".join(
            bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"
        )

        # o modelo às vezes envolve o JSON em ```json ... ``` mesmo quando pedimos pra não fazer isso —
        # essa extração pega só o trecho entre a primeira { e a última } como rede de segurança.
        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio == -1 or fim == -1:
            print("[AVISO] Resposta da IA não continha JSON reconhecível.")
            print(texto[:500])
            return None

        dados = json.loads(texto[inicio : fim + 1])
        return dados.get("nfl"), dados.get("futebol")

    except Exception as e:
        print(f"[AVISO] Coleta via IA falhou, caindo pro modo gratuito: {e}")
        return None
