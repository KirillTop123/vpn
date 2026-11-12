"""Перебор вариантов запроса: синонимы ниши и районы города."""
from __future__ import annotations

import config


def _norm(text: str) -> str:
    return (text or "").strip().lower().replace("ё", "е")


def expand_niche(niche: str) -> list[str]:
    """Ниша + синонимы из data/synonyms.json. Сама ниша всегда первая."""
    niche = (niche or "").strip()
    if not niche:
        return []
    result = [niche]
    wanted = _norm(niche)
    for key, values in config.load_json_config("synonyms.json").items():
        if key.startswith("_"):
            continue
        variants = [_norm(key)] + [_norm(v) for v in values]
        if wanted in variants or _norm(key) in wanted or wanted in _norm(key):
            for value in values:
                if _norm(value) not in [_norm(r) for r in result]:
                    result.append(value)
    return result


def city_info(city: str) -> dict:
    wanted = _norm(city)
    for name, info in config.load_json_config("cities.json").items():
        if not name.startswith("_") and _norm(name) == wanted:
            return info
    return {}


def districts(city: str) -> list[str]:
    return list(city_info(city).get("districts") or [])


def known_cities() -> list[str]:
    return [name for name in config.load_json_config("cities.json") if not name.startswith("_")]
