import json
from typing import List
from pathlib import Path
from core.schema import WarningDTO
from ports import Importer

class SampleJsonImporter(Importer):
    """Простой импортёр из нашего учебного JSON (не SARIF). Делает file_path абсолютным."""
    def load(self, source: str) -> List[WarningDTO]:
        src_path = Path(source).resolve()
        # .../Diplom/data/samples/warnings.sample.json  -> проектный корень = parents[2]
        project_root = src_path.parents[2] if len(src_path.parents) >= 3 else src_path.parent

        with open(src_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        out = []
        for i, obj in enumerate(data):
            fp = Path(str(obj.get("file_path", "<unknown>"))).expanduser()
            if not fp.is_absolute():
                fp = (project_root / fp).resolve()
            out.append(WarningDTO(
                id=str(obj.get("id", i)),
                rule_id=obj["rule_id"],
                severity=obj.get("severity", "warning"),
                message=obj.get("message", ""),
                file_path=str(fp),
                start_line=int(obj.get("start_line", 1)),
                end_line=int(obj.get("end_line", obj.get("start_line", 1))),
                raw=json.dumps(obj, ensure_ascii=False),
            ))
        return out
