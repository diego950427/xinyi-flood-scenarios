"""Offline, data-only comparison viewer. This module never runs a model.

The payload contract is implemented by comparison_data.build_comparison. Terrain
is the native 20 m cell height; result fields color that terrain, never an invented
instantaneous water surface. All third-party bytes are vendored with their license.
"""
from functools import lru_cache
from html import escape
import json
from pathlib import Path
import re

ASSETS = Path(__file__).resolve().parent / "comparison_assets"


@lru_cache(maxsize=8)
def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _script(value: str) -> str:
    # HTML parses a closing script tag even inside a JavaScript string/comment.
    return re.sub(r"</script", r"<\\/script", value, flags=re.IGNORECASE)


def comparison_html(payload: dict) -> str:
    """Return one self-contained HTML document suitable for components.html.

    Recommend iframe height=830; the document scrolls internally on narrow screens.
    No remote requests, fonts, event collection, or external runtime are required.
    Labels/metadata stay JSON data and are inserted through textContent.
    """
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("比較資料版本不支援，請重新建立比較圖。")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    # three.cjs is the official standalone build; its exports are captured locally.
    vendor = "const THREE=(()=>{const exports={};\n" + _asset("three-0.180.0.cjs") + "\nreturn exports;})();"
    title = escape(str(payload.get("field", {}).get("label", "情境比較")))
    values = {"__TITLE__": title, "__STYLE__": _asset("viewer.css"),
              "__PAYLOAD__": data, "__THREE__": _script(vendor),
              "__VIEWER__": _script(_asset("viewer.js")),
              "__LICENSE__": escape(_asset("LICENSE-THREE.txt"))}
    # One substitution pass prevents user labels resembling a template marker
    # from being interpreted as another substitution instruction.
    return re.sub(r"__(?:TITLE|STYLE|PAYLOAD|THREE|VIEWER|LICENSE)__",
                  lambda match: values[match.group()], _asset("viewer.html"))
