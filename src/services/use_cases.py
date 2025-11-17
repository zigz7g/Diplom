from core.schema import WarningDTO
from services import sarif_reader

class ImportSarifService:
    def __init__(self, repo):
        self.repo = repo

    def run(self, path: str) -> int:
        data = sarif_reader.load_sarif(path)
        items = list(sarif_reader.iter_results(data))
        self.repo.clear()
        count = 0
        for item in items:
            w = WarningDTO(
                rule_id=item["rule"],
                severity=item["severity"],
                file_path=item["file"] or "",
                start_line=item["start_line"],
                message=item["message"] or "",
                code_snippet=item.get("snippet") or "",
                start_col=item.get("start_col"),
                end_line=item.get("end_line"),
                end_col=item.get("end_col"),
                snippet_text=item.get("snippet") or "",
                status="Не обработано",
            )
            # отразить исходный уровень в UI, чтобы сразу была окраска
            w.severity_ui = w.severity
            self.repo.add(w)
            count += 1
        return count
