import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.schema import WarningDTO

def _get(d: Dict[str, Any], path: str, default=None):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

def _norm_sev(level: str) -> str:
    s = (level or "").lower()
    if s not in ("error", "warning", "note"):
        return "warning"
    return s

def _first_location(result: Dict[str, Any]) -> Dict[str, Any]:
    locs = result.get("locations") or []
    return locs[0] if locs else {}

def _extract_file_and_region(result: Dict[str, Any]) -> tuple[str, Optional[int], Optional[int]]:
    loc = _first_location(result)
    phys = loc.get("physicalLocation") or {}
    art = phys.get("artifactLocation") or {}
    uri = (art.get("uri") or art.get("uriBaseId") or "")  # uri может быть относительным
    region = phys.get("region") or {}
    start = region.get("startLine")
    end = region.get("endLine") or start
    return str(uri or "Unknown"), start, end

def _rules_lookup(run: Dict[str, Any]) -> Dict[str, str]:
    # ruleId -> shortDescription / name
    m: Dict[str, str] = {}
    rules = _get(run, "tool.driver.rules", []) or []
    for r in rules:
        rid = r.get("id")
        title = r.get("shortDescription", {}).get("text") \
                or r.get("name") \
                or r.get("fullDescription", {}).get("text")
        if rid and title:
            m[rid] = str(title)
    return m

class SarifReportImporter:
    """Чтение SARIF 2.1.0 (как у appScreener)."""
    def run(self, path: str) -> List[WarningDTO]:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))

        items: List[WarningDTO] = []
        runs = data.get("runs") or []
        for run in runs:
            rules_map = _rules_lookup(run)
            for res in run.get("results") or []:
                rule_id = str(res.get("ruleId") or res.get("rule", {}).get("id") or "Unknown Rule")
                level = _norm_sev(res.get("level") or _get(res, "kind", "warning"))
                msg = _get(res, "message.text", "") or ""
                file_path, start, end = _extract_file_and_region(res)
                title = rules_map.get(rule_id, rule_id)
                items.append(WarningDTO(
                    id=rule_id,
                    title=title,
                    message=msg,
                    severity=level,   # type: ignore
                    file_path=file_path or "Unknown",
                    start_line=start,
                    end_line=end
                ))
        return items
