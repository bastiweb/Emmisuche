from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from app.models import ParsedRecipe

logger = logging.getLogger(__name__)

NOISE_SELECTORS = [
    "nav",
    "footer",
    "aside",
    "#comments",
    ".comments",
    ".comment-list",
    ".comment-respond",
    ".author-box",
    ".author-bio",
    ".post-author",
    ".newsletter",
    ".newsletter-box",
    ".newsletter-signup",
    ".related-posts",
    ".related-recipes",
    ".popular-posts",
    ".popular-recipes",
    ".social-share",
    ".share-buttons",
    ".site-footer",
    ".post-footer",
    ".widget-area",
]

NOISE_TEXT_FRAGMENTS = [
    "newsletter",
    "kommentar",
    "kommentare",
    "author",
    "autor",
    "related recipe",
    "related post",
    "beliebte rezepte",
    "beliebte beiträge",
    "jetzt abonnieren",
    "folgt mir",
    "folge mir",
    "teilen",
    "share",
    "datenschutz",
    "impressum",
]

DOM_TITLE_SELECTORS = [
    ".wprm-recipe-name",
    "[itemprop='name']",
    "article h1.entry-title",
    "article h1",
    "h1",
]

DOM_INTRO_SELECTORS = [
    "article .entry-content > p",
    "article .post-content > p",
    "article .entry-content p",
]

DOM_INGREDIENT_SELECTORS = [
    ".wprm-recipe-ingredient",
    ".wprm-recipe-ingredients li",
    "[itemprop='recipeIngredient']",
    ".recipe-ingredients li",
]

DOM_INSTRUCTION_SELECTORS = [
    ".wprm-recipe-instruction-text",
    ".wprm-recipe-instructions li",
    "[itemprop='recipeInstructions']",
    ".recipe-instructions li",
]

DOM_SERVINGS_SELECTORS = [
    ".wprm-recipe-servings",
    ".wprm-recipe-servings-container .wprm-recipe-meta-value",
    "[itemprop='recipeYield']",
]

DOM_PREP_TIME_SELECTORS = [
    ".wprm-recipe-prep_time",
    ".wprm-recipe-prep-time",
    ".wprm-recipe-prep-time-container .wprm-recipe-meta-value",
    "[itemprop='prepTime']",
]

DOM_COOK_TIME_SELECTORS = [
    ".wprm-recipe-cook_time",
    ".wprm-recipe-cook-time",
    ".wprm-recipe-cook-time-container .wprm-recipe-meta-value",
    "[itemprop='cookTime']",
]

DOM_TOTAL_TIME_SELECTORS = [
    ".wprm-recipe-total_time",
    ".wprm-recipe-total-time",
    ".wprm-recipe-total-time-container .wprm-recipe-meta-value",
    "[itemprop='totalTime']",
]

DOM_NUTRITION_SELECTORS = [
    ".wprm-recipe-nutrition-container",
    ".wprm-recipe-nutrition",
    ".wprm-nutrition-container",
]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_clean_text(part) for part in value if _clean_text(part))
    text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _text_is_noise(value: str) -> bool:
    lowered = _clean_text(value).lower()
    if not lowered:
        return True
    return any(fragment in lowered for fragment in NOISE_TEXT_FRAGMENTS)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_image_url(image_field: Any) -> str | None:
    if image_field is None:
        return None
    if isinstance(image_field, str):
        return image_field.strip() or None
    if isinstance(image_field, dict):
        if "url" in image_field:
            return _clean_text(image_field["url"]) or None
        return None
    if isinstance(image_field, list):
        for item in image_field:
            url = _extract_image_url(item)
            if url:
                return url
    return None


def _extract_duration_text(value: Any) -> str | None:
    raw = _clean_text(value)
    if not raw:
        return None

    iso_match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?",
        raw,
    )
    if not iso_match:
        return raw

    parts: list[str] = []
    days = iso_match.group("days")
    hours = iso_match.group("hours")
    minutes = iso_match.group("minutes")
    if days:
        parts.append(f"{int(days)} d")
    if hours:
        parts.append(f"{int(hours)} h")
    if minutes:
        parts.append(f"{int(minutes)} min")
    return " ".join(parts) if parts else raw


def _strip_html(value: str) -> str:
    if "<" not in value and ">" not in value:
        return _clean_text(value)
    soup = BeautifulSoup(value, "lxml")
    return _clean_text(soup.get_text(" ", strip=True))


def _remove_noise_blocks(soup: BeautifulSoup) -> None:
    for selector in NOISE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()


def _extract_first_text(
    node: BeautifulSoup | Tag,
    selectors: list[str],
    *,
    min_length: int = 1,
) -> str | None:
    for selector in selectors:
        for element in node.select(selector):
            text = _clean_text(element.get_text(" ", strip=True))
            if len(text) < min_length:
                continue
            if _text_is_noise(text):
                continue
            return text
    return None


def _extract_text_list(node: BeautifulSoup | Tag, selectors: list[str]) -> list[str]:
    values: list[str] = []
    for selector in selectors:
        for element in node.select(selector):
            text = _strip_html(_clean_text(element.get_text(" ", strip=True)))
            if not text:
                continue
            if _text_is_noise(text):
                continue
            values.append(text)
    return _dedupe(values)


def _find_recipe_dom_root(soup: BeautifulSoup) -> BeautifulSoup | Tag:
    recipe_root = (
        soup.select_one(".wprm-recipe-container")
        or soup.select_one(".wprm-recipe")
        or soup.select_one("[itemtype*='Recipe']")
        or soup.select_one("article")
    )
    return recipe_root if recipe_root is not None else soup


def _is_type(node: dict[str, Any], expected: str) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, str):
        return node_type.lower() == expected.lower()
    if isinstance(node_type, list):
        return any(str(item).lower() == expected.lower() for item in node_type)
    return False


def _flatten_json_ld(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        nodes.append(payload)
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                nodes.extend(_flatten_json_ld(node))
        elif isinstance(graph, dict):
            nodes.extend(_flatten_json_ld(graph))
        return nodes

    if isinstance(payload, list):
        for item in payload:
            nodes.extend(_flatten_json_ld(item))
    return nodes


def _extract_json_ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        content = script.string or script.get_text(strip=True)
        if not content:
            continue

        text = content.strip()
        if text.startswith("<!--"):
            text = text.removeprefix("<!--").removesuffix("-->").strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        nodes.extend(_flatten_json_ld(payload))
    return nodes


def _extract_breadcrumb_categories(nodes: Iterable[dict[str, Any]]) -> list[str]:
    categories: list[str] = []
    for node in nodes:
        if not _is_type(node, "BreadcrumbList"):
            continue

        for item in _as_list(node.get("itemListElement")):
            if not isinstance(item, dict):
                continue

            candidate = item.get("name")
            if candidate is None and isinstance(item.get("item"), dict):
                candidate = item["item"].get("name")
            text = _clean_text(candidate)
            if text and text.lower() not in {"home", "startseite"}:
                categories.append(text)
    return categories


def _extract_instructions(value: Any) -> list[str]:
    steps: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            cleaned = _clean_text(_strip_html(item))
            if cleaned and not _text_is_noise(cleaned):
                steps.append(cleaned)
            continue

        if not isinstance(item, dict):
            continue

        if _is_type(item, "HowToSection"):
            section_name = _clean_text(item.get("name"))
            if section_name and not _text_is_noise(section_name):
                steps.append(section_name)
            steps.extend(_extract_instructions(item.get("itemListElement")))
            continue

        text = _clean_text(item.get("text") or item.get("name"))
        if text and not _text_is_noise(text):
            steps.append(_strip_html(text))
    return steps


def _extract_servings(value: Any) -> str | None:
    if isinstance(value, list):
        cleaned = [_clean_text(item) for item in value if _clean_text(item)]
        if not cleaned:
            return None
        return max(
            cleaned,
            key=lambda item: (
                bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", item)),
                len(item),
            ),
        )
    text = _clean_text(value)
    return text or None


def _extract_nutrition_summary(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = _clean_text(value)
        return text or None
    if not isinstance(value, dict):
        return None

    parts: list[str] = []
    for key, raw_value in value.items():
        if key.startswith("@"):
            continue
        text = _clean_text(raw_value)
        if not text:
            continue
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", key).replace("_", " ").strip()
        if label.lower().endswith("content"):
            label = label[: -len("content")].strip()
        parts.append(f"{label}: {text}")
    return "; ".join(parts) if parts else None


def _first_paragraph_intro(soup: BeautifulSoup | Tag) -> str | None:
    for selector in DOM_INTRO_SELECTORS:
        for paragraph in soup.select(selector):
            text = _clean_text(paragraph.get_text(" ", strip=True))
            if len(text) < 40:
                continue
            if _text_is_noise(text):
                continue
            return text
    return None


def _extract_nutrition_from_dom(root: BeautifulSoup | Tag) -> str | None:
    labels = root.select(".wprm-nutrition-label, .wprm-recipe-nutrition-label")
    values = root.select(".wprm-nutrition-value, .wprm-recipe-nutrition-value")
    if labels and len(labels) == len(values):
        pairs: list[str] = []
        for label_el, value_el in zip(labels, values):
            label = _clean_text(label_el.get_text(" ", strip=True)).rstrip(":")
            value = _clean_text(value_el.get_text(" ", strip=True))
            if not label or not value:
                continue
            pairs.append(f"{label}: {value}")
        if pairs:
            return "; ".join(_dedupe(pairs))

    for selector in DOM_NUTRITION_SELECTORS:
        nutrition = root.select_one(selector)
        if nutrition:
            text = _clean_text(nutrition.get_text(" ", strip=True))
            if text and not _text_is_noise(text):
                return text
    return None


@dataclass(slots=True)
class ParseResult:
    recipe: ParsedRecipe | None
    is_recipe_page: bool


class RecipeParser:
    def parse(
        self, html: str, source_url: str, sitemap_lastmod: str | None = None
    ) -> ParseResult:
        soup = BeautifulSoup(html, "lxml")
        _remove_noise_blocks(soup)
        recipe_root = _find_recipe_dom_root(soup)
        nodes = _extract_json_ld_nodes(soup)
        recipe_nodes = [node for node in nodes if _is_type(node, "Recipe")]

        if not recipe_nodes:
            logger.debug(
                "parse.no_recipe_schema",
                extra={"event": "parse.no_recipe_schema", "url": source_url},
            )
            return ParseResult(recipe=None, is_recipe_page=False)

        recipe_node = max(
            recipe_nodes,
            key=lambda node: (
                len(_as_list(node.get("recipeIngredient")))
                + len(_as_list(node.get("recipeInstructions")))
                + int(bool(_clean_text(node.get("name"))))
            ),
        )

        title = _clean_text(recipe_node.get("name"))
        if not title:
            title = _extract_first_text(recipe_root, DOM_TITLE_SELECTORS) or ""
        if not title:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            title = _clean_text(og_title.get("content") if og_title else "")
        if not title:
            logger.warning(
                "parse.missing_title",
                extra={"event": "parse.missing_title", "url": source_url},
            )
            return ParseResult(recipe=None, is_recipe_page=True)

        description = _clean_text(recipe_node.get("description"))
        meta_tag = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
            "meta", attrs={"name": "description"}
        )
        meta_description = _clean_text(meta_tag.get("content") if meta_tag else "")
        intro = description or meta_description or _first_paragraph_intro(recipe_root)
        if intro:
            intro = _strip_html(intro)
            if _text_is_noise(intro):
                intro = None

        image_url = _extract_image_url(recipe_node.get("image"))
        if not image_url:
            image_meta = soup.find("meta", attrs={"property": "og:image"})
            image_url = _clean_text(image_meta.get("content") if image_meta else "") or None
        if image_url:
            image_url = urljoin(source_url, image_url)

        categories = []
        categories.extend([_clean_text(x) for x in _as_list(recipe_node.get("recipeCategory"))])
        categories.extend([_clean_text(x) for x in _as_list(recipe_node.get("keywords"))])
        categories.extend(_extract_breadcrumb_categories(nodes))
        categories = [value for value in _dedupe(categories) if not _text_is_noise(value)]

        ingredients = []
        for item in _as_list(recipe_node.get("recipeIngredient")):
            text = _strip_html(_clean_text(item))
            if text and not _text_is_noise(text):
                ingredients.append(text)
        if not ingredients:
            ingredients = _extract_text_list(recipe_root, DOM_INGREDIENT_SELECTORS)
        ingredients = _dedupe(ingredients)

        instructions = _extract_instructions(recipe_node.get("recipeInstructions"))
        if not instructions:
            instructions = _extract_text_list(recipe_root, DOM_INSTRUCTION_SELECTORS)
        instructions = [step for step in _dedupe(instructions) if step]

        nutrition_summary = _extract_nutrition_summary(
            recipe_node.get("nutrition")
        ) or _extract_nutrition_from_dom(recipe_root)
        published_date = _clean_text(
            recipe_node.get("datePublished")
            or recipe_node.get("dateCreated")
            or recipe_node.get("dateModified")
        ) or None
        if not published_date:
            meta_published = soup.find(
                "meta", attrs={"property": "article:published_time"}
            )
            published_date = _clean_text(meta_published.get("content") if meta_published else "") or None

        prep_time = _extract_duration_text(recipe_node.get("prepTime")) or _extract_duration_text(
            _extract_first_text(recipe_root, DOM_PREP_TIME_SELECTORS)
        )
        cook_time = _extract_duration_text(recipe_node.get("cookTime")) or _extract_duration_text(
            _extract_first_text(recipe_root, DOM_COOK_TIME_SELECTORS)
        )
        total_time = _extract_duration_text(recipe_node.get("totalTime")) or _extract_duration_text(
            _extract_first_text(recipe_root, DOM_TOTAL_TIME_SELECTORS)
        )
        servings = _extract_servings(recipe_node.get("recipeYield")) or _extract_first_text(
            recipe_root, DOM_SERVINGS_SELECTORS
        )

        if not ingredients and not instructions:
            logger.warning(
                "parse.missing_recipe_body",
                extra={"event": "parse.missing_recipe_body", "url": source_url},
            )
            return ParseResult(recipe=None, is_recipe_page=True)

        searchable_text = " ".join(
            part
            for part in [
                title,
                intro or "",
                " ".join(categories),
                " ".join(ingredients),
                " ".join(instructions),
            ]
            if part
        )

        recipe = ParsedRecipe(
            source_url=source_url,
            title=title,
            intro=intro,
            image_url=image_url,
            categories=categories,
            published_date=published_date,
            prep_time=prep_time,
            cook_time=cook_time,
            total_time=total_time,
            servings=servings,
            ingredients=ingredients,
            instructions=instructions,
            nutrition_summary=nutrition_summary,
            searchable_text=searchable_text,
            last_sitemap_mod=sitemap_lastmod,
        )
        logger.debug(
            "parse.success",
            extra={
                "event": "parse.success",
                "url": source_url,
                "title": recipe.title,
                "ingredients_count": len(recipe.ingredients),
                "instructions_count": len(recipe.instructions),
            },
        )
        return ParseResult(recipe=recipe, is_recipe_page=True)
