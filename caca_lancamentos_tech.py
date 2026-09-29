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

            publicado_em = entrada.get("published_parsed") or entrada.get("updated_parsed")
            if not publicado_em:
                continue
            data_pub = datetime(*publicado_em[:6], tzinfo=timezone.utc)
            if data_pub < limite:
                continue

            candidatos.append({
                "titulo": entrada.get("title", ""),
                "link": link,
                "resumo": entrada.get("summary", "")[:500],
                "fonte": feed.feed.get("title", url_feed),
                "publicado_em": data_pub.isoformat(),
            })

    candidatos.sort(key=lambda c: c["publicado_em"], reverse=True)
    return candidatos[:MAX_CANDIDATOS_POR_RUN]


# ---------------------------------------------------------------------------
# 2) AGENTE REDATOR SEO
# ---------------------------------------------------------------------------
def agente_redator(candidato: dict, feedback_anterior: str | None = None) -> dict:
    system = f"""You are the SEO writer for "{SITE_CONFIG['nome']}", a tech launch
news site. Tone: {SITE_CONFIG['tom_de_voz']}

Given a news item, write a launch-day article. Respond STRICTLY as JSON:
{{
  "titulo_seo": "clickable but accurate title, under 65 chars",
  "meta_descricao": "under 155 chars, includes the product name",
  "corpo_html": "the article body as HTML (use <p>, <h2>, <ul> where useful), 350-500 words",
  "tags": ["tag1", "tag2", "tag3"]
}}
No text outside the JSON. No markdown code fences."""

    user_msg = (
        f"SOURCE TITLE: {candidato['titulo']}\n"
        f"SOURCE SUMMARY: {candidato['resumo']}\n"
        f"SOURCE LINK (cite as origin, do not copy text verbatim): {candidato['link']}"
    )
    if feedback_anterior:
        user_msg += f"\n\nPREVIOUS DRAFT WAS REJECTED. Fix this:\n{feedback_anterior}"

    resposta = rodar_agente(system, user_msg)
    return _parse_json_seguro(resposta)


def _parse_json_seguro(texto: str) -> dict:
    limpo = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        return {"erro": f"JSON inválido: {texto[:300]}"}


# ---------------------------------------------------------------------------
# 3) AGENTE EDITOR / QA — único portão de qualidade em modo automático
# ---------------------------------------------------------------------------
def agente_editor(artigo: dict) -> dict:
    system = """You are the Quality/Compliance editor for a tech news site.
You are the FINAL gate before publication — no human reviews this after you.
Reject if: the title is misleading/clickbait beyond the facts, the body reads
like a copy-paste of a press release, factual claims sound fabricated or
unverifiable, length is under 300 words, or tone doesn't match a
professional tech blog. Be strict. Respond STRICTLY as JSON:
{"aprovado": true or false, "motivo": "short reason, or 'ok' if approved"}"""

    conteudo = json.dumps(artigo, ensure_ascii=False)
    resposta = rodar_agente(system, conteudo, max_tokens=300)
    resultado = _parse_json_seguro(resposta)
    return resultado if "erro" not in resultado else {"aprovado": False, "motivo": "parse error"}


# ---------------------------------------------------------------------------
# 4) APROVAÇÃO — automática (CI) ou terminal (local)
# ---------------------------------------------------------------------------
def decidir_publicacao(artigo: dict, candidato: dict, aprovado_pelo_editor: bool) -> bool:
    if MODO_AUTOMATICO:
        # Sem terminal disponível (rodando no GitHub Actions) — o Editor já decidiu.
        return aprovado_pelo_editor

    print("\n" + "=" * 70)
    print(f"CANDIDATO A PUBLICAÇÃO — fonte: {candidato['fonte']}")
    print("=" * 70)
    print(f"Título SEO: {artigo.get('titulo_seo')}")
    print(f"Meta descrição: {artigo.get('meta_descricao')}")
    print(f"Tags: {artigo.get('tags')}")
    print("-" * 70)
    print(artigo.get("corpo_html", "")[:1500])
    print("-" * 70)
    resposta = input("Aprovar e publicar este artigo? [s/n]: ").strip().lower()
    return resposta == "s"


# ---------------------------------------------------------------------------
# 5) AGENTE PUBLICADOR
# ---------------------------------------------------------------------------
TEMPLATE_POST = """<!DOCTYPE html>
<html lang="{idioma}">
<head>
<meta charset="UTF-8">
<title>{titulo}</title>
<meta name="description" content="{meta}">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<article>
<h1>{titulo}</h1>
<p><em>{disclosure}</em></p>
{corpo}
<p><small>Source: <a href="{fonte_link}">{fonte_nome}</a></small></p>
</article>
<p><a href="../index.html">&larr; Back to {site_nome}</a></p>
</body>
</html>"""

TEMPLATE_INDEX = """<!DOCTYPE html>
<html lang="{idioma}">
<head>
<meta charset="UTF-8">
<title>{site_nome}</title>
<meta name="description" content="{tagline}">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>{site_nome}</h1>
<p>{tagline}</p>
<ul>
{lista_posts}
</ul>
</body>
</html>"""


def agente_publicador(artigo: dict, candidato: dict) -> Path:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(artigo["titulo_seo"])
    caminho_post = POSTS_DIR / f"{slug}.html"

    html_post = TEMPLATE_POST.format(
        idioma=SITE_CONFIG["idioma"],
        titulo=artigo["titulo_seo"],
        meta=artigo["meta_descricao"],
        disclosure=SITE_CONFIG["disclosure"],
        corpo=artigo["corpo_html"],
        fonte_link=candidato["link"],
        fonte_nome=candidato["fonte"],
        site_nome=SITE_CONFIG["nome"],
    )
    caminho_post.write_text(html_post, encoding="utf-8")

    _reconstruir_index()
    salvar_publicado(candidato["link"])
    return caminho_post


def _reconstruir_index():
    itens = []
    for arquivo in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        titulo = arquivo.stem.replace("-", " ").title()
        itens.append(f'<li><a href="posts/{arquivo.name}">{titulo}</a></li>')

    html_index = TEMPLATE_INDEX.format(
        idioma=SITE_CONFIG["idioma"],
        site_nome=SITE_CONFIG["nome"],
        tagline=SITE_CONFIG["tagline"],
        lista_posts="\n".join(itens) if itens else "<li>No posts yet.</li>",
    )
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html_index, encoding="utf-8")


# ---------------------------------------------------------------------------
# ORQUESTRADOR
# ---------------------------------------------------------------------------
def orquestrador():
    modo = "AUTOMÁTICO (sem revisão humana)" if MODO_AUTOMATICO else "MANUAL (aprovação por terminal)"
    print(f"[Orquestrador] Modo: {modo}")
    print(f"[Orquestrador] Buscando lançamentos das últimas {JANELA_HORAS}h...")
    candidatos = agente_scanner()

    if not candidatos:
        print("[Orquestrador] Nenhum lançamento novo encontrado nesta janela. Encerrando.")
        return

    print(f"[Orquestrador] {len(candidatos)} candidato(s) encontrado(s).\n")

    for candidato in candidatos:
        print(f"\n>>> Processando: {candidato['titulo']}")

        feedback = None
        artigo = None
        aprovado_pelo_editor = False
        for tentativa in range(1, MAX_REVISOES + 2):
            print(f"[Redator] Escrevendo (tentativa {tentativa})...")
            artigo = agente_redator(candidato, feedback)
            if "erro" in artigo:
                print(f"[Redator] Erro de geração: {artigo['erro']}")
                break

            print("[Editor] Revisando...")
            resultado = agente_editor(artigo)
            if resultado.get("aprovado"):
                print("[Editor] Aprovado. ✅")
                aprovado_pelo_editor = True
                break
            feedback = resultado.get("motivo")
            print(f"[Editor] Reprovado: {feedback}")
        else:
            print("[Orquestrador] Limite de revisões atingido. Pulando este candidato.\n")
            salvar_publicado(candidato["link"])
            continue

        if "erro" in artigo:
            continue

        if decidir_publicacao(artigo, candidato, aprovado_pelo_editor):
            caminho = agente_publicador(artigo, candidato)
            print(f"[Publicador] Publicado em: {caminho}")
        else:
            print("[Orquestrador] Não publicado.")
            salvar_publicado(candidato["link"])

        time.sleep(1)

    print("\n[Orquestrador] Execução concluída.")


if __name__ == "__main__":
    orquestrador()
