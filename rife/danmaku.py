"""Bounded XML/JSON danmaku loading, without forwarding browser credentials."""
import json
import math
import re
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

MAX_BYTES = 8 * 1024 * 1024
MAX_COMMENTS = 50000
DANMAKU_RESOLVER = "https://jx.1ljx.com/dan/@lirose_tv/?ac=dm&web&url="


def validate_source(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("弹幕地址必须为不含账号密码的 HTTP/HTTPS 地址")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize(time, text, mode=1, color=16777215):
    try:
        time, mode, color = float(time), int(mode), int(color)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(time) or time < 0 or not isinstance(text, str) or not text.strip():
        return None
    # Source emoji/images are HTML snippets, but our renderer is text-only.
    # Match quoted attribute values so a '>' inside src does not leak tag fragments.
    text = re.sub(r'''<img\b(?:[^'">]|"[^"]*"|'[^']*')*>''', "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None
    return {"time": time, "text": text[:300], "mode": mode if mode in (4, 5) else 1,
            "color": max(0, min(16777215, color))}


def parse_danmaku(data: bytes) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise ValueError("弹幕文件超过 8 MiB 限制")
    # Decode UTF-8/BOM and reject DTD/entity expansion before parsing XML.
    try:
        text = data.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("弹幕文件必须为 UTF-8 XML/JSON") from exc
    comments = []
    if text.startswith("<"):
        if re.search(r"<!DOCTYPE\s+html\b|<html\b", text, re.IGNORECASE):
            raise ValueError("olink 返回的是 HTML 网页，不是弹幕文件；需要该站点的实际弹幕 XML/JSON 接口")
        # A plain document declaration is metadata, not an entity definition.
        # Strip recognized i declarations without ever resolving their external URLs.
        quoted = r'''(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')'''
        declaration = r"<!DOCTYPE\s+i(?:\s+SYSTEM\s+" + quoted + r"|\s+PUBLIC\s+" + quoted + r"\s+" + quoted + r")?\s*>"
        text = re.sub(declaration, "", text, flags=re.IGNORECASE)
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("不支持包含内部 DTD/自定义实体定义的弹幕文件")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise ValueError("XML 弹幕格式错误；若 olink 是网页，请提供实际弹幕 XML/JSON") from exc
        if root.tag != "i":
            raise ValueError("olink 返回的是网页或不支持的 XML，请提供实际弹幕 XML/JSON")
        entries = list(root.iter("d"))
        if len(entries) > MAX_COMMENTS:
            raise ValueError("弹幕数量超过 50000 条限制")
        for node in entries:
            p = node.get("p", "").split(",")
            if len(p) >= 4:
                item = normalize(p[0], "".join(node.itertext()), p[1], p[3])
                if item:
                    comments.append(item)
    else:
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ValueError("olink 未返回弹幕 XML/JSON；网页地址需要对应站点的弹幕接口") from exc
        resolver_format = isinstance(payload, dict) and "danmuku" in payload
        entries = payload.get("danmuku" if resolver_format else "comments") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ValueError("JSON 弹幕需为数组或包含 comments 数组")
        if len(entries) > MAX_COMMENTS:
            raise ValueError("弹幕数量超过 50000 条限制")
        for node in entries:
            if resolver_format:
                if not isinstance(node, list) or len(node) < 5:
                    continue
                color = node[2]
                if isinstance(color, str):
                    try:
                        color = int(color.lstrip("#"), 16)
                    except ValueError:
                        continue
                item = normalize(node[0], node[4], {"top": 5, "bottom": 4}.get(node[1], 1), color)
                if item:
                    comments.append(item)
                continue
            if not isinstance(node, dict):
                continue
            if "p" in node and isinstance(node["p"], str):
                p = node["p"].split(",")
                if len(p) < 3:
                    continue
                item = normalize(p[0], node.get("m"), p[1], p[2])
            else:
                item = normalize(node.get("time"), node.get("text"), node.get("mode", 1), node.get("color", 16777215))
            if item:
                comments.append(item)
    return sorted(comments, key=lambda item: item["time"])


def load_danmaku(url: str) -> list[dict]:
    validate_source(url)
    # olink is a source-page URL. Encode it as one query value, including &, ? and #.
    parsed = urlsplit(url)
    already_resolved = parsed.hostname == "jx.1ljx.com" and parsed.path.rstrip("/") == "/dan/@lirose_tv"
    target = url if already_resolved else DANMAKU_RESOLVER + quote(url, safe="")
    request = Request(target, headers={"User-Agent": "RifeWebUI/1.0", "Accept": "application/json,application/xml,text/xml"})
    with build_opener(SafeRedirect()).open(request, timeout=10) as response:
        validate_source(response.url)
        data = response.read(MAX_BYTES + 1)
    return parse_danmaku(data)
