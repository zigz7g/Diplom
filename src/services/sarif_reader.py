# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

def _as_list(v) -> List[Any]:
    return v if isinstance(v, list) else []

def _sev(level: Optional[str]) -> str:
    m = {"error": "critical", "warning": "medium", "note": "info", "none": "info"}
    return m.get((level or "").lower().strip(), "medium")

def _first_location(res: Dict[str, Any]) -> Dict[str, Any]:
    locs = _as_list(res.get("locations"))
    if not locs:
        locs = _as_list(res.get("relatedLocations"))
    return (locs[0] if locs else {}) or {}

def _region(loc: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], str]:
    phys = (loc or {}).get("physicalLocation") or {}
    reg  = (phys.get("region") or {}) if isinstance(phys, dict) else {}
    snip = ""
    sn   = reg.get("snippet") or {}
    if isinstance(sn, dict):
        snip = sn.get("text") or ""
    return reg.get("startLine"), reg.get("startColumn"), reg.get("endLine"), reg.get("endColumn"), snip

def _file_path(run: Dict[str, Any], loc: Dict[str, Any]) -> str:
    phys = (loc or {}).get("physicalLocation") or {}
    art  = phys.get("artifactLocation") or {}
    uri = art.get("uri")
    if isinstance(uri, str) and uri:
        try:
            p = urlparse(uri)
            if p.scheme == "file":
                path = unquote(p.path or "")
                # Windows: '/C:/...' -> 'C:/...'
                if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                    path = path[1:]
                return path
            return unquote(uri)
        except Exception:
            return uri
    # index -> runs.artifacts[]
    idx = art.get("index")
    if isinstance(idx, int):
        arts = _as_list(run.get("artifacts"))
        if 0 <= idx < len(arts):
            loc2 = (arts[idx] or {}).get("location") or {}
            uri2 = loc2.get("uri")
            if isinstance(uri2, str) and uri2:
                try:
                    p = urlparse(uri2)
                    if p.scheme == "file":
                        path = unquote(p.path or "")
                        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                            path = path[1:]
                        return path
                    return unquote(uri2)
                except Exception:
                    return uri2
    return ""

def load_sarif(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def iter_results(data: Dict[str, Any]):
    for run in (data.get("runs") or []):
        results = run.get("results") or []
        if not isinstance(results, list):
            continue
        for res in results:
            loc = _first_location(res)
            sl, sc, el, ec, snip = _region(loc)
            fp = _file_path(run, loc)
            yield {
                "rule": res.get("ruleId") or (res.get("rule") or {}).get("id") or "(no-rule)",
                "severity": _sev(res.get("level")),
                "file": fp,
                "start_line": sl,
                "start_col": sc,
                "end_line": el,
                "end_col": ec,
                "message": (res.get("message") or {}).get("text") or "",
                "snippet": snip,
                "raw": res,
            }
