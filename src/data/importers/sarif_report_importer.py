import json
from pathlib import Path
from typing import List, Dict
from core.schema import WarningDTO


class SarifReportImporter:
    """Парсит SARIF файл и извлекает уязвимости в формате WarningDTO"""

    def __init__(self, project_root: Path = None):
        self.project_root = Path(project_root) if project_root else None

    def load(self, source: str) -> List[WarningDTO]:
        """Загружает данные из SARIF файла и конвертирует в список WarningDTO"""
        src = Path(source).resolve()
        with open(src, 'r', encoding='utf-8') as file:
            data = json.load(file)

        return self._parse_sarif(data)

    def _parse_sarif(self, data: Dict) -> List[WarningDTO]:
        """Парсит SARIF файл и конвертирует ошибки в формат WarningDTO"""
        vulns = []

        # Доступ к результатам анализа
        results = data.get("runs", [])

        for result in results:
            for tool in result.get("tool", {}).get("driver", {}).get("name", "").split(','):
                for log in result.get("results", []):
                    rule_id = log.get("ruleId", "Unknown Rule")
                    severity = log.get("level", "error").lower()
                    file_path = log.get("locations", [{}])[0].get("physicalLocation", {}).get("fileLocation", {}).get(
                        "uri", "Unknown")
                    start_line = log.get("locations", [{}])[0].get("physicalLocation", {}).get("region", {}).get(
                        "startLine", 0)
                    message = log.get("message", {}).get("text", "No message")
                    raw = json.dumps(log, ensure_ascii=False)

                    # Формирование WarningDTO
                    vuln = WarningDTO(
                        id=str(log.get("ruleId", "Unknown")),
                        rule_id=rule_id,
                        severity=severity,
                        message=message,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=start_line,
                        raw=raw
                    )
                    vulns.append(vuln)

        return vulns
