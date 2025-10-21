# agent_service/router.py
from typing import Dict, Any


def _detect_locale(text: str, default="ru") -> str:
    if not text:
        return default
    ru = sum('а' <= ch.lower() <= 'я' or ch.lower() == 'ё' for ch in text)
    en = sum('a' <= ch.lower() <= 'z' for ch in text)
    if ru > en: return "ru"
    if en > ru: return "en"
    return default

def need_retrieval(user_text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    routing = cfg.get("routing", {})
    mode = routing.get("mode", "precheck")
    if mode != "precheck":
        # If model-call, we let the model decide tool usage later
        return {"need": False}

    t = user_text.lower()
    if len(t) < 12:
        return {"need": False}
    
    locale = _detect_locale(t, cfg.get("i18n", {}).get("defaultLocale", "ru"))
    cfg_map = (routing.get("forceSearchKeywords") or {})
    kw = set(cfg_map.get(locale, []))

    if any(k in t for k in kw):
        return {
            "need": True,
            "k": routing.get("defaultK", 6),
            "top_n": routing.get("topN", 6),
            "rerank": routing.get("allowRerank", "auto"),
            "locale": locale,
        }
    return {"need": False, "locale": locale}
