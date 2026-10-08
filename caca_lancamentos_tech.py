"""Vantage — radar editorial RSS (v1.0).

Somente leitura de fontes públicas e geração de relatórios locais.
Não publica artigos, não modifica docs/ e não utiliza serviços de IA pagos.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser

FEEDS = {
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "Engadget": "https://www.engadget.com/rss.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
}

MARCAS = {
    "Apple": ("apple", "iphone", "ipad", "macbook", "airpods", "apple watch"),
    "Samsung": ("samsung", "galaxy"),
    "Motorola": ("motorola", "moto g", "moto edge", "razr"),
    "Google": ("google pixel", "pixel phone", "pixel watch", "pixel buds"),
    "Xiaomi": ("xiaomi", "redmi", "poco"),
    "OnePlus": ("oneplus",),
    "Nothing": ("nothing phone", "nothing ear", "cmf"),
    "Honor": ("honor",),
    "Oppo": ("oppo",),
    "Vivo": ("vivo x", "vivo v", "iqoo"),
    "Realme": ("realme",),
    "Huawei": ("huawei",),
}

CATEGORIAS = {
    "smartphones": ("smartphone", "phone", "iphone", "galaxy", "pixel", "android", "handset", "foldable", "razr"),
    "wearables": ("smartwatch", "wearable", "watch", "fitness tracker", "smart ring"),
    "audio": ("headphone", "earbud", "airpods", "audio", "speaker"),
    "tablets": ("tablet", "ipad"),
    "computadores": ("laptop", "notebook", "macbook", "computer", "chromebook"),
    "acessorios": ("case", "charger", "charging", "power bank", "accessory", "accessories"),
}

JANELA_HORAS = 168
MAX_ITENS_POR_FEED = 80
MAX_OPORTUNIDADES = 30
PASTA_RELATORIOS = Path("reports")


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto)


def contem_termo(texto: str, termo: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(normalizar(termo)) + r"(?!\w)", texto))


def limpar_html(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", texto or "")).strip()


def canonicalizar_url(url: str) -> str:
    partes = urlsplit(url.strip())
    parametros = [(k, v) for k, v in parse_qsl(partes.query) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), partes.path.rstrip("/"), urlencode(parametros), ""))


def classificar(titulo: str, resumo: str) -> tuple[list[str], list[str]]:
    texto = normalizar(f"{titulo} {resumo}")
    marcas = [marca for marca, termos in MARCAS.items() if any(contem_termo(texto, termo) for termo in termos)]
    categorias = [cat for cat, termos in CATEGORIAS.items() if any(contem_termo(texto, termo) for termo in termos)]
    return marcas, categorias


def obter_data(entrada) -> datetime | None:
    data = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if not data:
        return None
    try:
        return datetime(*data[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def coletar() -> tuple[list[dict], list[str]]:
    limite = datetime.now(timezone.utc) - timedelta(hours=JANELA_HORAS)
    registros: dict[str, dict] = {}
    avisos: list[str] = []

    for nome, url in FEEDS.items():
        try:
            feed = feedparser.parse(url, agent="VantageEditorialRadar/1.0")
            if getattr(feed, "bozo", False):
                avisos.append(f"{nome}: feed sinalizou problema de leitura; resultados podem estar incompletos")
            if not feed.entries:
                avisos.append(f"{nome}: nenhuma entrada retornada")
            for entrada in feed.entries[:MAX_ITENS_POR_FEED]:
                link = entrada.get("link", "").strip()
                titulo = limpar_html(entrada.get("title", ""))
                data = obter_data(entrada)
                if not link or not titulo or data is None or data < limite:
                    continue
                resumo = limpar_html(entrada.get("summary", ""))[:500]
                marcas, categorias = classificar(titulo, resumo)
                if not marcas and not categorias:
                    continue
                chave = canonicalizar_url(link)
                registros.setdefault(chave, {
                    "titulo": titulo,
                    "url": link,
                    "fonte": nome,
                    "publicado_em": data.isoformat(),
                    "resumo": resumo,
                    "marcas": marcas,
                    "categorias": categorias,
                })
        except Exception as exc:
            avisos.append(f"{nome}: erro na coleta ({type(exc).__name__}: {exc})")

    return sorted(registros.values(), key=lambda item: item["publicado_em"], reverse=True), avisos


def agrupar(registros: list[dict]) -> list[dict]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for item in registros:
        # Agrupamento exploratório por marca e categoria; não afirma que os links
        # tratam do mesmo lançamento ou modelo específico.
        marca = item["marcas"][0] if item["marcas"] else "Sem marca definida"
        categoria = item["categorias"][0] if item["categorias"] else "geral"
        grupos[f"{marca} | {categoria}"].append(item)

    oportunidades = []
    for assunto, itens in grupos.items():
        fontes = sorted({item["fonte"] for item in itens})
        score = min(100, 15 + 12 * len(fontes) + 4 * min(len(itens), 8))
        oportunidades.append({
            "assunto_exploratorio": assunto,
            "pontuacao_triagem": score,
            "quantidade_publicacoes": len(itens),
            "quantidade_fontes": len(fontes),
            "fontes": fontes,
            "links": [{"titulo": i["titulo"], "url": i["url"], "fonte": i["fonte"], "publicado_em": i["publicado_em"]} for i in itens[:12]],
            "status": "pesquisa_pendente",
        })
    return sorted(oportunidades, key=lambda o: (o["pontuacao_triagem"], o["quantidade_publicacoes"]), reverse=True)[:MAX_OPORTUNIDADES]


def salvar_relatorios(registros: list[dict], oportunidades: list[dict], avisos: list[str]) -> None:
    PASTA_RELATORIOS.mkdir(parents=True, exist_ok=True)
    relatorio = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "modo": "somente_descoberta_sem_publicacao",
        "janela_horas": JANELA_HORAS,
        "total_registros": len(registros),
        "total_oportunidades": len(oportunidades),
        "avisos": avisos,
        "oportunidades": oportunidades,
        "registros": registros,
    }
    (PASTA_RELATORIOS / "radar.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    linhas = ["# Vantage — Radar editorial", "", f"Gerado em UTC: {relatorio['gerado_em_utc']}", f"Publicações relevantes: {len(registros)}", f"Grupos exploratórios: {len(oportunidades)}", "", "**Atenção:** grupos não são consensos nem dossiês verificados. Nenhum artigo foi produzido.", ""]
    if avisos:
        linhas += ["## Avisos", ""] + [f"- {aviso}" for aviso in avisos] + [""]
    for posicao, op in enumerate(oportunidades, 1):
        linhas += [f"## {posicao}. {op['assunto_exploratorio']}", f"Pontuação de triagem: {op['pontuacao_triagem']}/100 · Fontes: {op['quantidade_fontes']} · Publicações: {op['quantidade_publicacoes']}", ""]
        linhas += [f"- [{link['titulo']}]({link['url']}) — {link['fonte']}" for link in op["links"]]
        linhas.append("")
    (PASTA_RELATORIOS / "radar.md").write_text("\n".join(linhas), encoding="utf-8")


def main() -> None:
    print("[Vantage] Iniciando radar editorial em modo seguro (sem publicação).")
    registros, avisos = coletar()
    oportunidades = agrupar(registros)
    salvar_relatorios(registros, oportunidades, avisos)
    print(f"[Vantage] Publicações relevantes: {len(registros)}")
    print(f"[Vantage] Grupos exploratórios: {len(oportunidades)}")
    print(f"[Vantage] Avisos de feeds: {len(avisos)}")
    print("[Vantage] Relatórios gerados: reports/radar.json e reports/radar.md")
    print("[Vantage] Nenhum arquivo em docs/ foi modificado; nenhuma publicação realizada.")


if __name__ == "__main__":
    main()
