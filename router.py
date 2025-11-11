# agent_service/router.py
from typing import Dict, Any
from utils.logger import get_logger
logger = get_logger()

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
    t = (user_text or "").lower()

    if mode != "precheck":
        logger.debug("router: mode=%s → need=False", mode)
        return {"need": False}

    if len(t) < 12:
        logger.debug("router: short text (len=%d) → need=False", len(t))
        return {"need": False}

    locale = _detect_locale(t, cfg.get("i18n", {}).get("defaultLocale", "ru"))

    kw_search = set((routing.get("forceSearchKeywords") or {}).get(locale, []))
    kw_rerank = set((routing.get("rerankKeywords") or {}).get(locale, []))
    escalate  = bool(routing.get("escalateIfRerankTriggers", True))

    hit_search = next((w for w in kw_search if w in t), None)
    hit_rerank = next((w for w in kw_rerank if w in t), None)

    need = bool(hit_search) or (escalate and bool(hit_rerank))

    logger.debug(
        "router: locale=%s need=%s hit_search=%s hit_rerank=%s escalate=%s k=%s topN=%s",
        locale, need, hit_search, hit_rerank, escalate,
        routing.get("defaultK", 6), routing.get("topN", 6)
    )

    if need:
        return {
            "need": True,
            "k": routing.get("defaultK", 6),
            # NOTE: we no longer force top_n here (chain will add it only if rerank=True)
            "rerank": routing.get("allowRerank", "auto"),
            "locale": locale,
        }
    return {"need": False, "locale": locale}
