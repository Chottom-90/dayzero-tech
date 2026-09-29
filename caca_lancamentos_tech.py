"""
CAÇA-LANÇAMENTOS TECH — Pipeline autônomo de conteúdo para site de nicho
==========================================================================

Modo automático (rodando via GitHub Actions, sem ninguém olhando):
    O Agente Editor/QA é o único portão de qualidade. Se aprovar
    internamente, publica sozinho. Ativado com a variável de ambiente
    MODO_AUTOMATICO=true (o workflow do GitHub Actions já seta isso).

Modo manual (rodando no seu computador):
    Sem essa variável de ambiente, o script volta a te perguntar no
    terminal antes de publicar cada artigo — útil pra testar/ajustar
    o tom antes de soltar 100% sozinho.

Fluxo:

    Orquestrador (roda 1x/dia via GitHub Actions)
        |
        v
    1) Agente Scanner       -> lê feeds RSS de tech, acha lançamentos das últimas 48h
        |
        v
    2) Agente Redator SEO   -> escreve o artigo em inglês (título, meta, corpo, tags)
        |
        v
    3) Agente Editor/QA     -> revisa qualidade (loop de correção)
        |
        v
    4) Aprovação            -> automática (modo CI) OU terminal (modo local)
        |
        v
    5) Agente Publicador    -> escreve o arquivo HTML em docs/ e atualiza o índice
                                (GitHub Actions faz o commit + push sozinho depois)
"""

import os
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
from anthropic import Anthropic

client = Anthropic()
MODEL = "claude-sonnet-4-6"

MODO_AUTOMATICO = os.environ.get("MODO_AUTOMATICO", "false").lower() == "true"

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DO SITE
# ---------------------------------------------------------------------------
SITE_CONFIG = {
    "nome": "DayZero Tech",
    "tagline": "First takes on the newest tech, the day it drops.",
    "idioma": "en",
    "tom_de_voz": (
        "Direct, enthusiast but not hype-y. Writes like someone who actually "
        "tested a lot of gadgets, not a press-release rewriter. Short "
        "paragraphs, scannable structure, no fluff intro."
    ),
    "disclosure": "This post may include affiliate links. We may earn a "
                  "commission at no extra cost to you.",
}

FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.engadget.com/rss.xml",
]

JANELA_HORAS = 48
MAX_CANDIDATOS_POR_RUN = 3
MAX_REVISOES = 2

SITE_DIR = Path("docs")          # GitHub Pages reconhece essa pasta nativamente
POSTS_DIR = SITE_DIR / "posts"
PUBLICADOS_PATH = Path("publicados.json")


# ---------------------------------------------------------------------------
# UTILITÁRIOS
# ---------------------------------------------------------------------------
def carregar_publicados() -> set:
    if PUBLICADOS_PATH.exists():
        return set(json.loads(PUBLICADOS_PATH.read_text()))
    return set()


def salvar_publicado(link: str):
    publicados = carregar_publicados()
    publicados.add(link)
    PUBLICADOS_PATH.write_text(json.dumps(sorted(publicados), indent=2))


def slugify(texto: str) -> str:
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:80]


def rodar_agente(system_prompt: str, user_message: str, max_tokens: int = 1200) -> str:
    resposta = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(b.text for b in resposta.content if b.type == "text")


# ---------------------------------------------------------------------------
# 1) AGENTE SCANNER
# ---------------------------------------------------------------------------
def agente_scanner() -> list[dict]:
    publicados = carregar_publicados()
    limite = datetime.now(timezone.utc) - timedelta(hours=JANELA_HORAS)
    candidatos = []

    for url_feed in FEEDS:
        feed = feedparser.parse(url_feed)
        for entrada in feed.entries:
            link = entrada.get("link")
            if not link or link in publicados:
                continue
