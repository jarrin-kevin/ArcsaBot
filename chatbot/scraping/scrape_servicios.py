#!/usr/bin/env python3
"""
scrape_servicios.py

Scraper con Playwright para el portal de Servicios de ARCSA
(https://www.controlsanitario.gob.ec/servicios/) que reemplaza la versión
anterior (proyecto arcsaPlayright) con una mejora puntual: captura de forma
explícita la jerarquía de secciones y subsecciones de cada página, en vez
de un simple par plano (root_section_id, parent_id).

Hallazgo clave del sitio en vivo (verificado el 2026-08-26, ver reporte):
la página /servicios/ NO expone los títulos de sus 3 agrupaciones visuales
("PRODUCTOS Y SERVICIOS", "ESTABLECIMIENTOS", "OTROS SERVICIOS") como texto
accesible en el DOM: son imágenes banner sin atributo alt/title, y tampoco
hay encabezados <h2>/<h3> ni texto en los enlaces (también son imágenes).
Por lo tanto:

  1. Los LÍMITES de cada grupo sí se detectan de forma 100% estructural,
     a partir del orden de las tablas de nivel superior dentro de
     #postcontent: una tabla que contiene una única imagen sin enlace, o
     con un enlace que apunta a su propia imagen (banner autorreferenciado),
     se interpreta como un separador/encabezado de grupo; cualquier otra
     tabla con enlaces reales aporta miembros al grupo vigente.
  2. El TÍTULO humano de cada grupo no puede extraerse del DOM (no existe
     como texto en ningún lado). Se usa una tabla de etiquetas verificada
     visualmente mediante captura de pantalla de la página en vivo
     (KNOWN_GROUP_LABELS). Si la cantidad de grupos detectados no coincide
     con la cantidad esperada, el scraper NO inventa un título: registra
     una advertencia y usa una etiqueta genérica ("Sección N sin título
     accesible") para que quede visible que la página cambió y hay que
     revisar la tabla de etiquetas a mano.

El breadcrumb de WordPress (clase .breadcrumb) existe en las páginas hijas,
pero su taxonomía de "categoría" está mal mantenida en el sitio real (valores
como "Sin categoría" o "servicios" que no coinciden con la agrupación visual),
así que se guarda solo como dato informativo (breadcrumb_categoria) y NO se
usa como fuente de section_path.

Hallazgo adicional (verificado el 2026-08-26 con una muestra de 14 páginas):
las 29 páginas "semilla" descubiertas en /servicios/ NO son hojas del árbol.
Cada una es en realidad una página-índice de un grupo de trámites (p. ej.
"Alimentos procesados" enlaza a ~25 trámites distintos como "Inscripción de
Notificación Sanitaria Nacional"), lo que explica que el proyecto anterior
(arcsaPlayright) haya llegado a 182 páginas partiendo de solo 4 secciones
raíz. Por eso este scraper es RECURSIVO (ver `crawl()`), con dos resguardos
explícitos porque el grafo real NO es un árbol limpio:

  1. Es un grafo, no un árbol: páginas hermanas se enlazan entre sí (p. ej.
     dos trámites de "Alimentos procesados" se referencian mutuamente, y
     "Certificado de Requerimiento..." aparece enlazado desde varias
     categorías distintas). Se deduplica por URL canónica con un conjunto
     `visited` global; la PRIMERA vez que se descubre una URL (siguiendo el
     orden de aparición en /servicios/) fija su `section_path` definitivo.
  2. Es fácil salirse de /servicios/ sin darse cuenta: el sitio no usa rutas
     anidadas por sección (todas las páginas son slugs planos bajo el
     dominio raíz), así que un trámite puede enlazar a páginas de otras
     áreas completamente distintas del sitio (se observó un enlace directo
     a /documentos-vigentes/, que es la biblioteca normativa, fuera de
     alcance de este scraper). Se usa una lista de exclusión explícita
     (SCOPE_EXCLUDE_SLUGS) para no seguir esos enlaces, además de un límite
     de profundidad configurable (--max-depth, por defecto 2).

Uso:
  python scrape_servicios.py --max-pages 10 --max-depth 2 --headless true
  python scrape_servicios.py --max-pages 500 --confirm-full-crawl --headless true
"""

import argparse
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

try:
    import yaml
    from bs4 import BeautifulSoup, Comment, Tag
    import markdownify
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright
except ImportError as e:
    sys.exit(f"[ERROR] Dependencia no encontrada: {e}. Instala las dependencias de chatbot/requirements.txt.")


# --------------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------------

BASE_URL = "https://www.controlsanitario.gob.ec/servicios/"
ROOT_LABEL = "Servicios"

PROJECT_DIR = Path(__file__).resolve().parent
PAGES_DIR = PROJECT_DIR / "pages"
STRUCTURE_FILE = PROJECT_DIR / "estructura_servicios.json"
LOG_FILE = PROJECT_DIR / "scraper.log"

# User-Agent descriptivo: identifica el propósito del scraper ante el sitio
# (buena práctica al recolectar datos de un sitio gubernamental real).
USER_AGENT = (
    "Mozilla/5.0 (compatible; ARCSA-RAG-Chatbot-Scraper/1.0; "
    "uso interno de indexacion documental para chatbot regulatorio; "
    "+https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Etiquetas de grupo verificadas visualmente sobre la página en vivo el
# 2026-08-26 (ver docstring del módulo). Clave = índice de grupo (1-based)
# en el orden en que aparecen los separadores en el DOM.
KNOWN_GROUP_LABELS: Dict[int, str] = {
    1: "Productos y servicios",
    2: "Establecimientos",
    3: "Otros servicios",
}
EXPECTED_GROUP_COUNT = len(KNOWN_GROUP_LABELS)

# Tope duro de niveles en section_path, independiente de --max-depth (que
# limita el BFS, no la longitud de la ruta). Es una segunda red de seguridad
# defensiva contra el mismo bug de encadenamiento degenerado: aunque
# --max-depth se configure muy alto, la ruta jerárquica nunca crece más allá
# de esto, sin importar cuántas páginas rotas se encadenen.
MAX_SECTION_PATH_DEPTH = 6

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".csv"}

# Subdominios/rutas de sistemas externos o transaccionales (no se capturan
# como contenido de página, se registran solo como referencia).
EXTERNAL_SYSTEM_PATTERNS = [
    "permisosfuncionamiento.controlsanitario.gob.ec",
    "aplicaciones.controlsanitario.gob.ec",
    "aplicativos.arcsa.gob.ec",
    "login",
    "autenticacion",
]

# Primer segmento de ruta de OTRAS áreas del sitio (fuera del alcance de
# /servicios/) a las que un trámite puede enlazar por error de navegación
# cruzada. El sitio no anida sus URLs por sección (todo es un slug plano
# bajo el dominio raíz), así que esta es la única forma de no seguir el
# rastro hacia, por ejemplo, la biblioteca normativa completa.
SCOPE_EXCLUDE_SLUGS = {
    "servicios", "documentos-vigentes", "biblioteca", "transparencia",
    "noticias", "la-institucion", "contacto", "category", "feed",
    "wp-json", "wp-content", "wp-admin", "tag", "author",
}


def is_out_of_scope(abs_url: str) -> bool:
    """Determina si una URL interna cae fuera del subárbol de /servicios/."""
    path = urlparse(abs_url).path.strip("/")
    first_segment = path.split("/", 1)[0] if path else ""
    return first_segment in SCOPE_EXCLUDE_SLUGS


# Patrones de URL típicos de "trampas de crawl" (paginación, archivos por
# fecha/calendario, parámetros de página) que en un WordPress genérico
# podrían generar una cantidad de páginas nuevas que nunca converge a cero.
# No se observaron en la muestra de 14 páginas ya validada, pero se filtran
# de forma preventiva antes de un crawl completo sin profundidad artificial.
TRAP_URL_PATTERNS = [
    re.compile(r"/\d{4}/\d{1,2}(/|$)"),  # archivos tipo /2024/05/
    re.compile(r"/page/\d+/?$"),
    re.compile(r"[?&]paged=\d+"),
    re.compile(r"[?&]page=\d+"),
    re.compile(r"/calendar/?"),
    re.compile(r"/tag/"),
    re.compile(r"/author/"),
]


def is_probable_crawl_trap_url(url: str) -> bool:
    """Detecta patrones de URL típicos de trampas de crawl (ver arriba)."""
    return any(p.search(url) for p in TRAP_URL_PATTERNS)

MAIN_CONTENT_SELECTORS = ["#postcontent", "main", "#main", "#content", ".entry-content", "article"]

EXCLUDED_DOM_SELECTORS = [
    "header", "footer", "nav", "aside", ".menu", ".site-header", ".site-footer",
    ".breadcrumb", ".social", ".share", ".cookie", "script", "style", "noscript", "iframe",
]

ACCORDION_SELECTORS = [
    '[aria-expanded="false"]',
    ".elementor-accordion-title",
    ".elementor-tab-title",
    ".toggle-title",
]


def setup_logger() -> logging.Logger:
    """Configura el logger del scraper para escribir en archivo y consola."""
    logger = logging.getLogger("arcsa_servicios_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


logger = setup_logger()


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

# Normalizado (espacios múltiples colapsados) desde el inicio, porque el
# título real observado en el sitio trae un doble espacio ("Control  y")
# que rompía la comparación de igualdad si no se normalizaban ambos lados
# por igual (bug encontrado y corregido durante las pruebas de este fix).
GENERIC_SITE_TITLE = " ".join("Agencia Nacional de Regulación, Control  y Vigilancia Sanitaria".split())
TITULO_SIN_DATOS = "(sin título propio)"


def strip_site_name_suffix(title: str) -> str:
    """
    Quita el sufijo "– Nombre del sitio" que el plugin SEO de WordPress
    agrega al <title> de las páginas que no tienen su propio <h1> (ver
    docstring del módulo: sin este recorte, ese sufijo se arrastra a cada
    nivel más profundo de section_path al usarse como título del padre).

    Bug real encontrado en el crawl de 500 páginas (ver reporte): algunas
    páginas rotas tienen un <title> que es EXACTAMENTE el nombre del sitio,
    sin separador que recortar. Sin este resguardo, ese título genérico se
    reutilizaba como section_path de sus hijos, y si un hijo también estaba
    roto con el mismo título genérico, la ruta crecía con el mismo segmento
    repetido en cada nivel hasta superar el límite de 260 caracteres de
    Windows (MAX_PATH) y tumbar el crawl completo con un FileNotFoundError.
    """
    normalized = " ".join(title.split())
    for marker in (" – ", " — ", " | ", " - "):
        if marker in title:
            head, _, _tail = title.rpartition(marker)
            head_normalized = " ".join(head.split())
            if head_normalized and head_normalized != GENERIC_SITE_TITLE:
                return head.strip()
    if normalized == GENERIC_SITE_TITLE:
        return TITULO_SIN_DATOS
    return title.strip()


def slugify(text: str, max_length: int = 60) -> str:
    """Genera un slug URL-safe y apto para nombres de carpeta/archivo."""
    if not text:
        return "sin-titulo"
    text = text.lower().strip()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text or "pagina"


def canonical_url(url: str) -> str:
    """Normaliza una URL quitando fragmento y barra final redundante."""
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") if parsed.path not in ("", "/") else parsed.path
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def stable_id(url: str, title: str) -> str:
    """Genera un id determinista y estable para una página capturada."""
    base_slug = slugify(title, max_length=40)
    url_hash = hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:8]
    return f"{base_slug}-{url_hash}"


def classify_link(href: str, current_url: str) -> Tuple[str, str]:
    """Clasifica un href detectado en la página. Retorna (tipo, url_absoluta)."""
    if not href:
        return "unknown", ""
    href_clean = href.strip()
    if href_clean.startswith(("mailto:", "tel:", "javascript:", "#")):
        return "no_navegable", href_clean

    abs_url = urljoin(current_url, href_clean)
    parsed = urlparse(abs_url)
    _, ext = os.path.splitext(parsed.path.lower())

    if ext in IMAGE_EXTENSIONS:
        return "imagen", abs_url
    if ext in FILE_EXTENSIONS:
        return "archivo", abs_url

    netloc = parsed.netloc.lower()
    for pattern in EXTERNAL_SYSTEM_PATTERNS:
        if pattern in abs_url.lower():
            return "sistema_externo", abs_url

    if "controlsanitario.gob.ec" in netloc:
        return "pagina_interna", abs_url
    return "enlace_externo", abs_url


# --------------------------------------------------------------------------
# Descubrimiento de la jerarquía de secciones (Paso 1)
# --------------------------------------------------------------------------

@dataclass
class SectionGroup:
    """Un grupo visual detectado en /servicios/ (nivel 2 de section_path)."""
    orden: int
    seccion: str
    detectado_por: str
    members: List[Dict[str, str]] = field(default_factory=list)


def is_group_marker_table(table: Tag, base_url: str) -> bool:
    """
    Determina si una tabla de nivel superior es un separador/encabezado de
    grupo (imagen banner decorativa) en lugar de una tabla con enlaces de
    contenido real. Ver docstring del módulo para el razonamiento completo.
    """
    imgs = table.find_all("img")
    links = table.find_all("a", href=True)

    if not imgs:
        return False  # tabla vacía usada como espaciador visual

    if not links:
        return True  # imagen decorativa sin enlace -> separador de grupo

    if len(links) == 1:
        abs_url = urljoin(base_url, links[0]["href"].strip())
        _, ext = os.path.splitext(urlparse(abs_url).path.lower())
        if ext in IMAGE_EXTENSIONS:
            return True  # banner que enlaza a su propia imagen -> separador

    return False


def discover_section_tree(page: Any) -> List[SectionGroup]:
    """
    Navega a /servicios/ y reconstruye la jerarquía de grupos + páginas
    miembro a partir del orden real de las tablas en el DOM (ver docstring
    del módulo: los títulos de grupo no son texto accesible, así que se
    detectan los LÍMITES por estructura y se etiquetan con
    KNOWN_GROUP_LABELS, con degradación explícita si la forma cambia).
    """
    logger.info(f"Descubriendo estructura de secciones en: {BASE_URL}")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)

    soup = BeautifulSoup(page.content(), "lxml")
    main_container, used_selector = extract_main_container(soup)
    if main_container is None:
        raise RuntimeError("No se pudo localizar el contenedor principal de /servicios/.")
    logger.info(f"Contenedor principal detectado con selector: {used_selector}")

    tables = main_container.find_all("table", recursive=False)
    logger.info(f"Se encontraron {len(tables)} tablas de nivel superior en el contenedor principal.")

    groups: List[SectionGroup] = []
    current_group: Optional[SectionGroup] = None
    group_index = 0
    seen_urls = set()

    for table in tables:
        if is_group_marker_table(table, BASE_URL):
            group_index += 1
            label = KNOWN_GROUP_LABELS.get(group_index)
            detectado_por = "posicion_dom_tabla+etiqueta_verificada_manualmente"
            if label is None:
                label = f"Sección {group_index} (sin título accesible)"
                detectado_por = "posicion_dom_tabla+SIN_etiqueta_verificada"
                logger.warning(
                    f"Grupo #{group_index} detectado sin etiqueta conocida en KNOWN_GROUP_LABELS. "
                    "El sitio pudo haber cambiado de estructura; revisar manualmente."
                )
            current_group = SectionGroup(orden=group_index, seccion=label, detectado_por=detectado_por)
            groups.append(current_group)
            continue

        links = table.find_all("a", href=True)
        if not links:
            continue  # tabla vacía / espaciadora sin contenido

        if current_group is None:
            # No debería ocurrir en la estructura verificada, pero se cubre
            # explícitamente en vez de fallar o perder enlaces silenciosamente.
            current_group = SectionGroup(
                orden=0,
                seccion="Sin agrupar (antes del primer separador)",
                detectado_por="posicion_dom_tabla+sin_marcador_previo",
            )
            groups.insert(0, current_group)
            logger.warning("Se encontraron enlaces antes de cualquier separador de grupo.")

        for position, a_tag in enumerate(links, start=1):
            href = a_tag.get("href", "").strip()
            link_type, abs_url = classify_link(href, BASE_URL)
            url_canon = canonical_url(abs_url)
            if link_type not in ("pagina_interna", "sistema_externo") or url_canon in seen_urls:
                continue
            seen_urls.add(url_canon)
            current_group.members.append({
                "orden": len(current_group.members) + 1,
                "url": abs_url,
                "tipo": link_type,
            })

    if group_index != EXPECTED_GROUP_COUNT:
        logger.warning(
            f"Se detectaron {group_index} grupo(s) pero se esperaban {EXPECTED_GROUP_COUNT} "
            f"según KNOWN_GROUP_LABELS. Verificar si /servicios/ cambió de estructura."
        )

    total_members = sum(len(g.members) for g in groups)
    logger.info(f"Estructura descubierta: {len(groups)} grupo(s), {total_members} página(s) miembro en total.")
    return groups


def save_structure_manifest(groups: List[SectionGroup]) -> None:
    """Guarda la jerarquía descubierta en estructura_servicios.json (ver
    estructura_arcsa.json del proyecto anterior como referencia de formato,
    mejorado aquí con url y método de detección por sección)."""
    manifest = {
        "source_url": BASE_URL,
        "root_label": ROOT_LABEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_group_count": EXPECTED_GROUP_COUNT,
        "sections": [
            {
                "orden": g.orden,
                "seccion": g.seccion,
                "detectado_por": g.detectado_por,
                "subsecciones": [
                    {"orden": m["orden"], "url": m["url"], "tipo": m["tipo"]}
                    for m in g.members
                ],
            }
            for g in groups
        ],
    }
    STRUCTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STRUCTURE_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info(f"Manifest de estructura guardado en: {STRUCTURE_FILE}")


# --------------------------------------------------------------------------
# Captura de página individual (Paso 2)
# --------------------------------------------------------------------------

@dataclass
class PageCapture:
    id: str
    title: str
    section_path: List[str]
    source_url: str
    final_url: Optional[str] = None
    captured_at: Optional[str] = None
    http_status: Optional[int] = None
    content_hash: Optional[str] = None
    capture_status: str = "pending"
    breadcrumb_categoria: Optional[str] = None
    error: Optional[str] = None


def extract_main_container(soup: BeautifulSoup) -> Tuple[Optional[Tag], Optional[str]]:
    """Prueba selectores candidatos en orden hasta aislar el contenido principal."""
    for selector in MAIN_CONTENT_SELECTORS:
        if selector.startswith("#"):
            container = soup.find(id=selector[1:])
        elif selector.startswith("."):
            container = soup.find(class_=selector[1:])
        else:
            container = soup.find(selector)
        if container and isinstance(container, Tag):
            return container, selector
    return soup.body, "body"


def clean_dom_tree(container: Tag) -> None:
    """Elimina elementos no deseados (nav, header, scripts, etc.) del contenedor."""
    for comment in container.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    for selector in EXCLUDED_DOM_SELECTORS:
        if selector.startswith("."):
            for el in container.find_all(class_=selector[1:]):
                el.decompose()
        else:
            for el in container.find_all(selector):
                el.decompose()


def expand_accordions(page: Any) -> None:
    """Expande acordeones/tabs visibles (best-effort, hasta 2 ciclos)."""
    for _ in range(2):
        expanded = 0
        for selector in ACCORDION_SELECTORS:
            try:
                for el in page.query_selector_all(selector):
                    try:
                        if el.is_visible() and el.get_attribute("aria-expanded") != "true":
                            el.click(timeout=800)
                            expanded += 1
                            page.wait_for_timeout(200)
                    except Exception:
                        continue
            except Exception:
                continue
        if expanded == 0:
            break


def extract_breadcrumb_categoria(soup: BeautifulSoup) -> Optional[str]:
    """
    Extrae el segmento intermedio del breadcrumb nativo de WordPress, solo
    como dato informativo de trazabilidad (ver docstring: su taxonomía real
    NO coincide con la agrupación visual del sitio, por eso no se usa para
    construir section_path).
    """
    bc = soup.find(class_="breadcrumb")
    if not bc:
        return None
    links = bc.find_all("a")
    if len(links) >= 2:
        return links[1].get_text(strip=True) or None
    return None


def build_front_matter(capture: PageCapture) -> str:
    """Construye el front matter YAML + cuerpo Markdown de una página capturada."""
    metadata = {
        "id": capture.id,
        "title": capture.title,
        "section_path": capture.section_path,
        "source_url": capture.source_url,
        "final_url": capture.final_url,
        "captured_at": capture.captured_at,
        "http_status": capture.http_status,
        "content_hash": capture.content_hash,
        "source_type": "web_page",
        "capture_status": capture.capture_status,
        "breadcrumb_categoria": capture.breadcrumb_categoria,
    }
    yaml_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_text}---\n"


def extract_child_links(container: Tag, current_url: str) -> List[Tuple[str, str]]:
    """
    Extrae los enlaces internos descubiertos dentro del contenedor ya limpio
    de una página capturada, para permitir el crawl recursivo (ver docstring
    del módulo: cada página semilla de /servicios/ es en realidad una
    página-índice con más trámites enlazados). Retorna pares (tipo, url).
    """
    found = []
    for a_tag in container.find_all("a", href=True):
        link_type, abs_url = classify_link(a_tag["href"], current_url)
        if link_type != "pagina_interna" or is_out_of_scope(abs_url):
            continue
        if is_probable_crawl_trap_url(abs_url):
            logger.warning(f"Excluyendo posible URL trampa de crawl: {abs_url}")
            continue
        found.append((link_type, abs_url))
    return found


def capture_page(
    page: Any,
    url: str,
    section_path: List[str],
    timeout_ms: float,
    retries: int,
) -> Tuple[PageCapture, Optional[str], List[Tuple[str, str]]]:
    """
    Navega a `url`, extrae el contenido principal y lo convierte a Markdown
    con front matter. Retorna (metadatos_de_captura, markdown_o_None,
    enlaces_internos_descubiertos) para permitir que el llamador decida si
    continúa el crawl recursivo desde esta página.
    """
    logger.info(f"Capturando página: {url}  |  section_path={section_path}")
    captured_at = datetime.now(timezone.utc).isoformat()
    capture = PageCapture(id="", title="", section_path=section_path, source_url=url, captured_at=captured_at)

    response = None
    attempts = 0
    while attempts <= retries:
        attempts += 1
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1200)
            break
        except PlaywrightTimeoutError:
            logger.warning(f"Timeout navegando a {url} (intento {attempts}/{retries + 1})")
            if attempts > retries:
                capture.capture_status = "timeout"
                capture.error = "Timeout al cargar la página"
                return capture, None, []
        except PlaywrightError as e:
            logger.warning(f"Error de Playwright navegando a {url}: {e} (intento {attempts}/{retries + 1})")
            if attempts > retries:
                capture.capture_status = "broken"
                capture.error = str(e)
                return capture, None, []

    http_status = response.status if response else None
    capture.http_status = http_status
    capture.final_url = page.url

    if http_status is not None and http_status >= 400:
        capture.capture_status = "broken"
        capture.error = f"HTTP {http_status}"
        return capture, None, []

    expand_accordions(page)
    soup = BeautifulSoup(page.content(), "lxml")

    capture.breadcrumb_categoria = extract_breadcrumb_categoria(soup)

    main_container, _ = extract_main_container(soup)
    if main_container is None:
        capture.capture_status = "manual_review"
        capture.error = "No se pudo identificar el contenedor principal"
        return capture, None, []

    h1 = main_container.find("h1")
    if h1 and h1.get_text(strip=True):
        raw_title = h1.get_text(strip=True)
    elif soup.title and soup.title.string:
        raw_title = strip_site_name_suffix(soup.title.string.strip())
    else:
        raw_title = TITULO_SIN_DATOS
    # El h1 también puede ser literalmente el nombre genérico del sitio (se
    # observó en vivo), no solo el <title>; se normaliza por igual en ambos
    # casos para que el resguardo anti-encadenamiento de section_path
    # (ver más abajo, en el bucle principal) siempre lo detecte.
    capture.title = TITULO_SIN_DATOS if " ".join(raw_title.split()) == GENERIC_SITE_TITLE else raw_title

    clean_dom_tree(main_container)
    child_links = extract_child_links(main_container, capture.final_url or url)

    cleaned_html = str(main_container)
    capture.content_hash = f"sha256:{hashlib.sha256(cleaned_html.encode('utf-8')).hexdigest()}"
    capture.id = stable_id(url, capture.title)

    md_body = markdownify.markdownify(
        cleaned_html, heading_style="ATX", bullets="-", autolinks=False,
    ).strip()
    md_body = re.sub(r"\n{3,}", "\n\n", md_body)

    # Algunas páginas del sitio responden HTTP 200 pero con el contenedor
    # principal vacío (verificado en vivo, p. ej. /calificate-con-arcsa/).
    # Se marca explícitamente en vez de guardarla como si tuviera contenido
    # útil, siguiendo el mismo criterio de "marcar en lugar de eliminar" que
    # usa el proyecto para citas desactualizadas (ver CONTEXT.md).
    if len(md_body.strip()) < 20:
        capture.capture_status = "empty_content"
        capture.error = "El contenedor principal quedó vacío tras la limpieza del DOM (posible defecto del sitio)."
        logger.warning(f"Contenido vacío detectado en {url} (HTTP {http_status}).")
    else:
        capture.capture_status = "captured"

    front_matter = build_front_matter(capture)
    markdown_text = f"{front_matter}\n# {capture.title}\n\n{md_body}\n"
    return capture, markdown_text, child_links


# Límite defensivo de longitud de ruta absoluta. Windows trunca en 260
# caracteres (MAX_PATH) salvo que se use el prefijo extendido \\?\, que no
# todas las herramientas del proyecto soportan de forma consistente; se deja
# margen para el nombre de archivo final.
MAX_SAFE_PATH_LENGTH = 240


def save_page(section_slugs: List[str], page_slug: str, markdown_text: str) -> Path:
    """
    Guarda el Markdown en una carpeta que refleja la jerarquía de secciones.

    Si la ruta resultante superaría el límite seguro de Windows (ver bug real
    documentado en strip_site_name_suffix: un encadenamiento de títulos
    genéricos puede producir una ruta arbitrariamente profunda), se cae a una
    carpeta plana `_rutas_largas/` en vez de fallar el crawl completo por una
    sola página con metadata degenerada. El section_path real de la página
    sigue estando completo dentro de su propio front matter YAML.
    """
    folder = PAGES_DIR.joinpath(*section_slugs)
    file_path = folder / f"{page_slug}.md"

    if len(str(file_path)) > MAX_SAFE_PATH_LENGTH:
        overflow_folder = PAGES_DIR / "_rutas_largas"
        overflow_folder.mkdir(parents=True, exist_ok=True)
        file_path = overflow_folder / f"{page_slug}.md"
        logger.warning(
            f"Ruta de sección demasiado larga ({len(str(folder / (page_slug + '.md')))} caracteres); "
            f"guardando en carpeta plana de respaldo: {file_path}"
        )
    else:
        folder.mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
    except OSError as e:
        # Último resguardo: nunca perder una página capturada por un
        # problema de sistema de archivos con su ruta calculada.
        overflow_folder = PAGES_DIR / "_rutas_largas"
        overflow_folder.mkdir(parents=True, exist_ok=True)
        file_path = overflow_folder / f"{page_slug}.md"
        logger.warning(f"No se pudo escribir en la ruta jerárquica ({e}); usando respaldo: {file_path}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)

    return file_path


# --------------------------------------------------------------------------
# Orquestación principal
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scraper de Playwright para el portal de Servicios de ARCSA, con jerarquía explícita de secciones."
    )
    parser.add_argument(
        "--max-pages", type=int, default=10,
        help="Número máximo de páginas a capturar en esta ejecución (por defecto: 10, para pruebas).",
    )
    parser.add_argument(
        "--confirm-full-crawl", action="store_true",
        help="Requerido para superar 30 páginas en una sola ejecución (evita un crawl completo accidental).",
    )
    parser.add_argument(
        "--max-depth", type=int, default=2,
        help="Profundidad máxima de recursión desde cada página semilla de /servicios/ "
        "(por defecto: 2; ver docstring del módulo: las páginas semilla son índices, no hojas).",
    )
    parser.add_argument("--headless", type=lambda v: v.lower() != "false", default=True)
    parser.add_argument("--delay", type=float, default=2.0, help="Segundos de espera entre cada página (por defecto: 2.0).")
    parser.add_argument("--timeout", type=float, default=45000.0, help="Timeout por página en milisegundos.")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if args.max_pages > 30 and not args.confirm_full_crawl:
        sys.exit(
            "[ERROR] --max-pages > 30 requiere --confirm-full-crawl explícito. "
            "Este scraper por defecto solo corre una muestra pequeña; un crawl completo "
            "del sitio es un paso deliberado y separado."
        )
    return args


def main() -> None:
    args = parse_args()
    logger.info("=== Iniciando scrape_servicios.py (ARCSA) ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": 1440, "height": 1200}, user_agent=USER_AGENT)
        page = context.new_page()
        page.set_default_timeout(args.timeout)

        groups = discover_section_tree(page)
        save_structure_manifest(groups)

        # BFS por NIVELES (no una sola cola plana): se procesa toda la
        # profundidad N antes de pasar a la N+1. Esto permite medir cuántas
        # páginas NUEVAS aparecen en cada nivel y comprobar que la cifra
        # converge a cero en vez de asumir que --max-depth alcanza (pedido
        # explícito del usuario: no confiar en una profundidad fija).
        #
        # `visited` deduplica por URL canónica en TODO el crawl: como el
        # grafo real tiene páginas hermanas que se enlazan entre sí, la
        # primera vez que aparece una URL (siguiendo el orden de /servicios/)
        # fija su section_path definitivo; apariciones posteriores de la
        # misma URL se ignoran en vez de duplicar el archivo o su carpeta.
        visited = set()
        current_level: List[Tuple[str, List[str]]] = []
        for group in groups:
            section_path = [ROOT_LABEL, group.seccion]
            for member in group.members:
                if member["tipo"] != "pagina_interna":
                    logger.info(f"Omitiendo enlace no interno ({member['tipo']}): {member['url']}")
                    continue
                url_canon = canonical_url(member["url"])
                if url_canon in visited:
                    continue
                visited.add(url_canon)
                current_level.append((member["url"], section_path))

        captured = 0
        results = []
        depth = 1
        level_history: List[Dict[str, Any]] = []  # curva de convergencia
        previous_level_size: Optional[int] = None
        trap_detected = False
        stop_reason = None
        crashed = False

        # Se envuelve el bucle completo en try/except: un crawl de cientos de
        # páginas contra un sitio real puede toparse con una página con
        # metadata degenerada que el código no anticipó (ver bug real de
        # encadenamiento de section_path documentado arriba, que tumbó una
        # corrida completa de 322 páginas sin dejar capture_summary.json ni
        # convergence_report.json). Ante CUALQUIER excepción no prevista, se
        # registra el traceback y se garantiza igual la escritura de ambos
        # reportes con lo capturado hasta ese punto, en vez de perder toda la
        # telemetría de la corrida.
        try:
            while current_level and captured < args.max_pages and not trap_detected:
                logger.info(f"=== NIVEL {depth}: {len(current_level)} página(s) nueva(s) por procesar ===")
                next_level: List[Tuple[str, List[str]]] = []
                hit_page_limit_mid_level = False

                for url, section_path in current_level:
                    if captured >= args.max_pages:
                        hit_page_limit_mid_level = True
                        logger.info(f"Se alcanzó --max-pages ({args.max_pages}); deteniendo dentro del nivel {depth}.")
                        break

                    section_slugs = [slugify(s) for s in section_path]
                    time.sleep(args.delay)
                    capture, markdown_text, child_links = capture_page(
                        page, url, section_path, args.timeout, args.retries
                    )
                    captured += 1

                    if markdown_text:
                        page_slug = f"{slugify(capture.title)}-{capture.id.split('-')[-1]}"
                        saved_path = save_page(section_slugs, page_slug, markdown_text)
                        logger.info(
                            f"[N{depth}] Guardado: {saved_path}  |  section_path={capture.section_path}  "
                            f"|  status={capture.capture_status}"
                        )

                        if depth < args.max_depth:
                            # Resguardo contra encadenamiento degenerado: si el
                            # título de esta página no aporta un segmento nuevo
                            # y distinto (p. ej. una página rota que cayó al
                            # placeholder TITULO_SIN_DATOS, o cuyo título coincide
                            # con el segmento inmediato del padre), NO se agrega
                            # otro nivel a section_path para sus hijos. Sin esto,
                            # una cadena de páginas rotas puede crecer la ruta sin
                            # límite (ver bug real documentado más arriba) hasta
                            # superar MAX_PATH en Windows y tumbar el crawl.
                            if (
                                capture.title == TITULO_SIN_DATOS
                                or slugify(capture.title) == slugify(section_path[-1])
                                or len(section_path) >= MAX_SECTION_PATH_DEPTH
                            ):
                                child_section_path = section_path
                            else:
                                child_section_path = section_path + [capture.title]
                            for _, child_url in child_links:
                                child_canon = canonical_url(child_url)
                                if child_canon in visited:
                                    continue
                                visited.add(child_canon)
                                next_level.append((child_url, child_section_path))
                    else:
                        # Página rota/timeout/manual_review: se registra en
                        # results igualmente (no se descarta, ver CONTEXT.md),
                        # pero no aporta enlaces hijos nuevos a next_level.
                        logger.warning(f"[N{depth}] No se guardó Markdown para {url} (status={capture.capture_status})")

                    results.append(asdict(capture))

                new_count = len(next_level)
                level_history.append({"profundidad": depth, "paginas_nuevas_encontradas": new_count})
                logger.info(f"=== NIVEL {depth} completo: {new_count} página(s) NUEVA(S) para el nivel {depth + 1} ===")

                # Resguardo anti-trampa de crawl: en un sitio finito, a partir de
                # cierta profundidad la cantidad de páginas nuevas por nivel
                # debería reducirse hacia cero. Si en cambio vuelve a CRECER a
                # partir del nivel 4 (ya pasado el abanico inicial esperado de
                # los niveles 1-3), se detiene el crawl de inmediato en vez de
                # agotar el presupuesto completo en lo que probablemente sea
                # paginación/calendario/parámetros no capturados por
                # TRAP_URL_PATTERNS, y se reporta la evidencia en vez de seguir.
                if depth >= 4 and previous_level_size is not None and new_count >= 5 and new_count > previous_level_size:
                    trap_detected = True
                    stop_reason = (
                        f"El nivel {depth + 1} tendría {new_count} página(s) nueva(s), más que el nivel "
                        f"{depth} ({previous_level_size}). No converge hacia cero como se espera de un sitio "
                        "finito; posible trampa de crawl. Deteniendo de forma preventiva sin agotar --max-pages."
                    )
                    logger.error(f"[ALERTA] {stop_reason}")
                    break

                if hit_page_limit_mid_level:
                    break

                previous_level_size = new_count
                current_level = next_level
                depth += 1

            if trap_detected:
                logger.error(f"=== Crawl detenido por posible trampa en el nivel {depth}. Ver convergence_report.json ===")
            elif not current_level:
                logger.info(f"=== Convergencia natural: el nivel {depth} no descubrió páginas nuevas. ===")
            elif captured >= args.max_pages:
                logger.info(f"=== Se alcanzó --max-pages ({args.max_pages}) antes de converger naturalmente. ===")
        except Exception:
            crashed = True
            stop_reason = f"Excepción no manejada durante el crawl: {traceback.format_exc()}"
            logger.error(f"[ALERTA] Crawl interrumpido por una excepción no manejada. Ver traceback:\n{traceback.format_exc()}")
            logger.error(
                f"Se preservan las {captured} página(s) ya capturadas y escritas en disco; "
                "no se pierde la corrida completa por este error."
            )

        try:
            browser.close()
        except Exception as e:
            logger.warning(f"No se pudo cerrar el navegador limpiamente (sin impacto en los datos ya guardados): {e}")

    summary_path = PROJECT_DIR / "capture_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    convergence_path = PROJECT_DIR / "convergence_report.json"
    with open(convergence_path, "w", encoding="utf-8") as f:
        json.dump({
            "niveles": level_history,
            "total_paginas_capturadas": captured,
            "profundidad_final": depth,
            "trampa_de_crawl_detectada": trap_detected,
            "crawl_interrumpido_por_excepcion": crashed,
            "motivo_de_detencion": stop_reason,
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Resumen de captura guardado en: {summary_path}")
    logger.info(f"Reporte de convergencia guardado en: {convergence_path}")
    logger.info(f"=== Finalizado. {captured} página(s) procesada(s) hasta el nivel {depth}. ===")

    if crashed:
        sys.exit(1)


if __name__ == "__main__":
    main()
