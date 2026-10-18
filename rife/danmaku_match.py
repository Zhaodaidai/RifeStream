"""Conservative Bilibili fallback for playlist items without an explicit olink.

Only an exact show title and an unambiguous episode may be attached. This is
read-only: it never changes the playlist, video source, or playback error state.
"""
from collections import OrderedDict
from dataclasses import dataclass
import html
import json
import re
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from rife.danmaku import _bilibili_read, load_danmaku, parse_danmaku


@dataclass(frozen=True)
class MediaQuery:
    title: str
    episode: int | None = None
    season: int | None = None


_NUM = r"[0-9零〇一二两三四五六七八九十百千]+"
_VIDEO_EXT = r"\.(?:mp4|mkv|avi|mov|webm|flv|m4v|ts|m2ts|wmv|m3u8)$"


def _number(text: str) -> int:
    if text.isascii() and text.isdigit():
        return int(text)
    digits = dict(zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if not any(ch in text for ch in "十百千"):
        return int("".join(str(digits[ch]) for ch in text))
    total = part = 0
    for ch in text:
        if ch in digits:
            part = digits[ch]
        else:
            total += (part or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            part = 0
    return total + part


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKC", html.unescape(re.sub(r"<[^>]*>", "", text))).strip()


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", _plain(text)).casefold()


def _name(text: str) -> str:
    # Do not send directory names, URL query tokens, or full filesystem paths.
    text = unquote(urlsplit(text).path if "://" in text else text).replace("\\", "/").rsplit("/", 1)[-1]
    text = _plain(re.sub(_VIDEO_EXT, "", text, flags=re.I))
    text = re.split(r"[-_]?(?:国创|番剧|高清独家在线观看|bilibili|哔哩哔哩)(?:[-_]|$)", text, maxsplit=1, flags=re.I)[0]
    # Bracketed release/codec/group annotations are not the programme name.
    text = re.sub(r"\[[^\]]*\]|【[^】]*】|\([^)]*(?:1080|2160|720|x26[45]|HEVC|WEB.?DL|字幕)[^)]*\)", " ", text, flags=re.I)
    return text.strip(" ._-—")[:240]


def parse_media_query(title: str, source: str = "") -> MediaQuery | None:
    """Recognise 第N集/话, SxxExx, EPxx and release-style 'name - 02'."""
    candidates = []
    for value in (title, source):
        text = _name(str(value or ""))
        if not text:
            continue
        if re.search(r"预告|解说|混剪|花絮|片段|盘点|特别篇|番外|(?i:\b(?:PV|OVA|OAD|SP)(?:[0-9]+)?\b|\breaction\b)", text):
            continue
        season = None
        sm = re.search(rf"第\s*({_NUM})\s*季", text)
        if sm:
            season = _number(sm[1])
            text = text[:sm.start()] + text[sm.end():]
        match = re.search(r"(?i)(?<![A-Za-z0-9])S([0-9]{1,2})[ ._-]*E([0-9]{1,4})(?![0-9])", text)
        if match:
            season, episode = int(match[1]), int(match[2])
        else:
            match = re.search(rf"第\s*({_NUM})\s*[集话話回]", text)
            if match:
                episode = _number(match[1])
            else:
                match = re.search(r"(?i)(?:^|[ ._-])(?:EP?|Episode)[ ._-]*([0-9]{1,4})(?![0-9])", text)
                if not match:
                    match = re.search(r"(?:\s+-\s*|\s+)([0-9]{1,3})(?:\s|$)", text)
                episode = int(match[1]) if match else None
        name = (text[:match.start()] if match else text).strip(" ._-—")
        if len(_key(name)) < 2 or name.isdigit() or not name:
            continue
        # A URL/filename with no meaningful title must not become a search term.
        if _key(name) in {"video", "index", "playlist", "movie", "unknown"}:
            continue
        if episode is not None and not 1 <= episode <= 9999:
            continue
        if season is not None and not 1 <= season <= 99:
            continue
        candidates.append(MediaQuery(name, episode, season))
    # Prefer an identifiable episode in the filename over a generic UI title.
    return next((q for q in candidates if q.episode is not None), candidates[0] if candidates else None)


def _json(url: str) -> dict:
    try:
        payload = json.loads(_bilibili_read(url))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Bilibili 返回无效的 JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ValueError("Bilibili 搜索/分集接口暂不可用")
    return payload


def _show_matches(title: str, query: MediaQuery) -> bool:
    title = _plain(title)
    season = re.search(rf"第\s*({_NUM})\s*季", title)
    number = _number(season[1]) if season else None
    base = title[:season.start()] + title[season.end():] if season else title
    if _key(base) != _key(query.title):
        return False
    if query.season is None:
        return number in (None, 1)
    return number == query.season or (query.season == 1 and number is None)


def _episode_number(value: str) -> int | None:
    value = _plain(str(value))
    match = re.fullmatch(rf"(?:第\s*)?({_NUM})(?:\s*[集话話回])?", value)
    return _number(match[1]) if match else None


def _find_episode(query: MediaQuery) -> dict | None:
    keyword = query.title + (f" 第{query.season}季" if query.season else "")
    payload = _json("https://api.bilibili.com/x/web-interface/search/all/v2?keyword=" + quote(keyword, safe=""))
    groups = payload.get("data", {}).get("result", [])
    if not isinstance(groups, list):
        raise ValueError("Bilibili 搜索响应格式错误")
    shows = {}
    for group in groups:
        if not isinstance(group, dict) or group.get("result_type") not in {"media_bangumi", "media_ft"}:
            continue
        for item in group.get("data") or []:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str):
                continue
            season_id = item.get("season_id")
            if isinstance(season_id, int) and not isinstance(season_id, bool) and season_id > 0 and _show_matches(item["title"], query):
                shows[season_id] = item
    # Do not pick the first search result when different editions match equally.
    if len(shows) != 1:
        return None
    season_id, show = next(iter(shows.items()))
    payload = _json(f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}")
    episodes = payload.get("result", {}).get("episodes", [])
    if not isinstance(episodes, list):
        raise ValueError("Bilibili 分集响应格式错误")
    episodes = [e for e in episodes if isinstance(e, dict)]
    if query.episode is None:
        matches = episodes if len(episodes) == 1 else []
    else:
        matches = [e for e in episodes if _episode_number(e.get("title", "")) == query.episode]
    if len(matches) != 1:
        return None
    episode = matches[0]
    cid, ep_id = episode.get("cid"), episode.get("id")
    if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in (cid, ep_id)):
        raise ValueError("Bilibili 分集缺少有效 cid/ep_id")
    return {"cid": cid, "ep_id": ep_id, "title": _plain(show["title"]),
            "episode": query.episode, "episode_title": str(episode.get("long_title") or episode.get("title") or "")}


# Bounded process-local cache. Identical concurrent requests share one fetch.
# No-match results expire sooner; transient errors have a short retry backoff.
_CACHE = OrderedDict()
_PENDING = {}
_LOCK = threading.Lock()
_CACHE_BYTES = 0
_CACHE_LIMIT = 24 * 1024 * 1024


def _cached_auto(query: MediaQuery) -> dict:
    global _CACHE_BYTES
    while True:
        with _LOCK:
            entry = _CACHE.get(query)
            if entry and entry[0] > time.monotonic():
                _CACHE.move_to_end(query)
                if isinstance(entry[1], str):
                    raise ValueError(entry[1])
                return entry[1]
            if query not in _PENDING:
                event = _PENDING[query] = threading.Event()
                break
            event = _PENDING[query]
        if not event.wait(35):
            raise ValueError("Bilibili 自动匹配等待超时，可重新开启弹幕重试")
    result, ttl = None, 60
    try:
        episode = _find_episode(query)
        if episode:
            comments = parse_danmaku(_bilibili_read(f"https://comment.bilibili.com/{episode['cid']}.xml"))
            label = "Bilibili 自动匹配 · " + episode["title"]
            if episode["episode"] is not None:
                label += f" 第{episode['episode']}集"
            result = {"comments": comments, "source": label,
                      "source_url": f"https://www.bilibili.com/bangumi/play/ep{episode['ep_id']}",
                      "match": episode}
            if not comments:
                result["message"] = label + " · 当前接口未返回弹幕"
            ttl = 600
        else:
            result = {"comments": [], "source": "Bilibili 自动匹配",
                      "message": "Bilibili 未找到片名与集数均明确匹配的弹幕（不会自动套用其他集）"}
            ttl = 120
        return result
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        result = "Bilibili 自动匹配失败：" + str(exc)
        raise ValueError(result) from exc
    finally:
        with _LOCK:
            if result is not None:
                size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                previous = _CACHE.pop(query, None)
                if previous:
                    _CACHE_BYTES -= previous[2]
                if size <= _CACHE_LIMIT:
                    _CACHE[query] = (time.monotonic() + ttl, result, size)
                    _CACHE_BYTES += size
                while _CACHE and (len(_CACHE) > 32 or _CACHE_BYTES > _CACHE_LIMIT):
                    _, removed = _CACHE.popitem(last=False)
                    _CACHE_BYTES -= removed[2]
            _PENDING.pop(query).set()


def load_item_danmaku(item: dict) -> dict:
    """Explicit sources take priority; only absent sources trigger auto search."""
    if item.get("olink"):
        return {"comments": load_danmaku(item["olink"]), "source": "自带弹幕", "source_url": item["olink"]}
    query = parse_media_query(item.get("title", ""), item.get("source", ""))
    if query is None:
        return {"comments": [], "source": "Bilibili 自动匹配", "message": "无法从文件名识别片名和集数，已跳过自动匹配"}
    return _cached_auto(query)
