# data/importers/pdf_report_importer.py
import PyPDF2
import re  # Добавьте эту строку
from pathlib import Path
from typing import List
from core.schema import WarningDTO

class PdfReportImporter:
    def load(self, source: str) -> List[WarningDTO]:
        pdf_path = Path(source)
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"

        return self._parse_pdf(text)

    def _parse_pdf(self, text: str) -> List[WarningDTO]:
        vulnerabilities = []

        # Регулярное выражение для поиска блоков уязвимостей
        # Ищем строку вида "django-main/...:123" или ":123"
        pattern = r'(django-main[/\\][^\n:]+):(\d+(?:#\d+)?)'
        matches = list(re.finditer(pattern, text))

        for match in matches:
            file_path = match.group(1)
            line_range = match.group(2)

            # Обработка диапазона строк
            start_line = 0
            end_line = 0
            if "#" in line_range:
                try:
                    start_line = int(line_range.split("#")[0])
                    end_line = int(line_range.split("#")[1])
                except ValueError:
                    start_line = 0
                    end_line = 0
            else:
                try:
                    start_line = int(line_range)
                    end_line = start_line
                except ValueError:
                    start_line = 0
                    end_line = 0

            # Поиск уровня критичности в ближайших строках после совпадения
            pos = match.end()
            snippet_end = pos + 500  # Ищем в пределах 500 символов после
            search_area = text[pos:snippet_end]

            severity = "Unknown"
            status = "Not processed"
            code_snippet = ""

            # Ищем Level
            level_match = re.search(r'Level\s+(\w+)', search_area, re.IGNORECASE)
            if level_match:
                severity = level_match.group(1)

            # Ищем Status
            status_match = re.search(r'Status\s+([^\n]+)', search_area, re.IGNORECASE)
            if status_match:
                status = status_match.group(1).strip()

            # Извлекаем фрагмент кода: ищем начало кода после Level/Status
            # Код обычно начинается с отступа или с цифры (номера строки)
            code_match = re.search(r'\n(\s*\d+\s*:.*(?:\n\s*\d+\s*:.*|\n\s*[^\n]*)*)', search_area)
            if code_match:
                code_snippet = code_match.group(1).strip()
            else:
                # Если не нашли структурированный код, берём всё до следующего пути
                next_match = re.search(r'django-main[/\\]', search_area)
                if next_match:
                    code_snippet = search_area[:next_match.start()].strip()
                else:
                    code_snippet = search_area.strip()

            # Извлекаем правило (Rule) из строки выше
            rule = "Unknown Rule"
            prev_lines = text[:pos].splitlines()
            for i in range(len(prev_lines) - 1, -1, -1):
                line = prev_lines[i].strip()
                if line.startswith("[") and "]" in line:
                    rule = line.split("]")[1].strip().split("-")[0].strip()
                    break

            vuln = WarningDTO(
                id=str(len(vulnerabilities) + 1),
                rule_id=rule,
                severity=severity,
                message="No message",
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                raw=match.group(0),
                code_snippet=code_snippet
            )
            vulnerabilities.append(vuln)

        return vulnerabilities