# src/data/importers/pdf_report_importer.py
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional
from pdfminer.high_level import extract_text
from core.schema import WarningDTO

# ───────────────────────── Базовые паттерны ─────────────────────────

PATH_LINE_RE = re.compile(r"^(?P<path>[\w\-.+/\\ ]+?):(?P<line>\d+(?:#\d+)?)\s*$")
STRICT_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/|\.{1,2}/|\.[A-Za-z0-9]{1,6}\b)")

BLOCK_TITLE_RE = re.compile(r"^[A-ZА-Я].*\([^)]*\)\s*$")

DESCRIPTION_ANCHOR_RE = re.compile(r"^\s*(?:Description|Описание)\s*$", re.IGNORECASE)
ENTRIES_ANCHOR_RE     = re.compile(r"^\s*(?:Vulnerability\s+Entries|Вхождения)\s*$", re.IGNORECASE)

# И Level/Status ловим в любой части строки: pdfminer иногда «склеивает»
LEVEL_LINE_RE  = re.compile(r"\b(?:Level|Уровень)\s+(?P<level>[A-Za-zА-Яа-я]+)\b", re.IGNORECASE)
STATUS_LINE_RE = re.compile(r"\b(?:Status|Статус)\b", re.IGNORECASE)

# Служебные секции
META_OR_SECTION_RE = re.compile(
    r"\b(?:Trace|Трасса|Example|Пример|Recommendations|Рекомендации|Links|Ссылки|"
    r"References|Fix|Исправление|Mitigation|Снижение\s+риска|Description|Описание)\b",
    re.IGNORECASE,
)

# «Слепленная» мусорная строка
NOISE_CHUNK_RE = re.compile(r"(?:Level|Уровень)\s+\w+.*(?:Status|Статус)\b", re.IGNORECASE)

# Код с номерами
CODE_LINE_COLON_RE = re.compile(r"^\s*(?P<num>\d+)[:.]\s+(?P<code>.*\S)\s*$")  # "NN: code"/"NN. code"
CODE_LINE_RE       = re.compile(r"^\s*(?P<num>\d+)\s+(?P<code>.*\S)\s*$")      # "NN code"
ONLY_NUM_LINE_RE   = re.compile(r"^\s*(?P<num>\d+)\s*$")                       # "NN"
REPL_LINE_RE       = re.compile(r"^\s*(>>>|\.\.\.)\s+.*\S\s*$")                # Python REPL

# Общие признаки кода (без VERBOSE, чтобы '#' не ломал шаблон)
CODE_HINTS_RE = re.compile(
    r"(?:[=+\-*/<>]|[\{\(\[]|[\}\)\]]|;|"
    r"^\s*[\{\(\[]|"
    r"^\s*[\w\-\.\[\]\"']+\s*:\s+.+"      # YAML key: value
    r"|^\s*\#.+|"                         # комментарий py/sh
    r"^\s*//.+|"                          # комментарий js
    r"<\s*/?\s*\w+[^>]*>|"                # html-тег
    r"\b(?:def|class|if|for|while|return|var|let|const|function|import|from|"
    r"try|catch|finally|throw|new|public|private|protected|static|using)\b)",
    re.IGNORECASE,
)

# Шапки/футеры/рамки — игнор
HEADER_FOOTER_RE = re.compile(
    r"(?:TABLE\ OF\ CONTENTS|PROJECT\ INFORMATION|Security\ Level\ Dynamics|"
    r"Vulnerability\ Dynamics|Scan\ Information|Scan\ Statistics|Language\ Statistics|"
    r"Vulnerability\ List|Detailed\ Results|CONFIDENTIALITY\ NOTE|WAF\ Configuration\ Guide|"
    r"Export\ Settings|Go\ To\ Results|Report\ Date|Rules\ Version|Product\ Version|"
    r"Report\ Author|Содержание|Информация\ о\ проекте|Детальные\ результаты|"
    r"Статистика\ сканирования|Статистика\ языков|Список\ уязвимостей|"
    r"Конфиденциальность|Дата\ отчёта|Версия\ правил|Версия\ продукта|Автор\ отчёта)",
    re.IGNORECASE,
)

# Док-разметка
DOC_MARKUP_RE = re.compile(
    r"^\s*(\.\.|code-block::|note::|warning::|tip::|:caption:|Sample\b|Examples?\b|Пример)\b",
    re.IGNORECASE,
)

PROJECT_TAIL_RE = re.compile(r"^\s*[\w\-\. ]+?\.(zip|pdf)\s*$", re.IGNORECASE)

# Явные «стоп-слова» в сниппетах (часто лезут в txt/html)
STOPWORDS_CONTAINS = (
    "django-Diplom-Plutalov", "appScreener", "OWASP", "CWE",
    "Go To Results", "Export Settings", "Scan Information",
    "Report Date", "Rules Version", "Product Version", "Report Author",
    "Автор отчёта", "Версия правил", "Версия продукта",
    "Детальные результаты",
)

# Уровни RU→EN
RU_SEV_MAP = {
    "критический": "critical",
    "высокий": "high",
    "средний": "medium",
    "низкий": "low",
    "информационный": "info",
}

# Где часто нет левого номера
LOOSE_EXTS = {".yml", ".yaml", ".ini", ".conf", ".cfg", ".toml", ".xml", ".html", ".htm", ".json"}

# ───────────────────────── Хелперы ─────────────────────────

def _clean(s: str) -> str:
    return (s or "").replace("\x0c", "\n").strip()

def is_header_footer(s: str) -> bool:
    if not s:
        return False
    if HEADER_FOOTER_RE.search(s):
        return True
    if re.fullmatch(r"\s*\d+(?:/\d+)?\s*", s) or re.fullmatch(r"\s*[\d\.\)]+\s*", s):
        return True
    if re.search(r"\bdjango[\-\w\.\ ]*zip\b", s, re.IGNORECASE):
        return True
    return False

def has_stopwords(s: str) -> bool:
    return any(k in s for k in STOPWORDS_CONTAINS)

def looks_like_code_generic(s: str) -> bool:
    if not s or not s.strip():
        return False
    if PROJECT_TAIL_RE.match(s) or DOC_MARKUP_RE.match(s) or NOISE_CHUNK_RE.search(s):
        return False
    if has_stopwords(s):
        return False
    # длинные «абзацы текста» без кода — отсекаем
    if len(s) > 90 and not CODE_HINTS_RE.search(s):
        return False
    return bool(CODE_HINTS_RE.search(s))

def looks_like_code_by_ext(s: str, ext: str) -> bool:
    if not s or not s.strip():
        return False
    s = s.rstrip()
    if ext in {".yml", ".yaml"}:
        if re.search(r"^\s*-\s", s) or re.search(r"^\s*[\w\-\.\[\]\"']+\s*:\s+.+", s):
            return True
    elif ext in {".ini", ".conf", ".cfg", ".toml"}:
        if re.search(r"^\s*\[.+\]\s*$", s) or re.search(r"^\s*[\w\.\-]+\s*=\s*.+", s):
            return True
    elif ext in {".xml", ".html", ".htm"}:
        if re.search(r"<\s*/?\s*\w+[^>]*>", s):
            return True
    elif ext == ".json":
        if re.search(r"^\s*[\{\}\[\]],?\s*$", s) or re.search(r'^\s*"[^"]+"\s*:\s*.+', s):
            return True
    # для .txt — принимаем только явные «кодовые» строки
    elif ext == ".txt":
        if REPL_LINE_RE.match(s):
            return True
        # В .txt допускаем код только при наличии явной «кодовой» пунктуации
        if re.search(r"[{}\[\]\(\);:=<>#/$]", s) or re.search(r"\b(import|def|class|const|let|function|return)\b", s):
            return True
        return False
    return looks_like_code_generic(s)

PLAIN_CODE_CHARS = re.compile(r"[{}\[\]\(\);:=<>#/$]")
PLAIN_CODE_WORDS = re.compile(
    r"\b(def|class|if|for|while|return|var|let|const|function|import|from|"
    r"try|catch|finally|throw|new|public|private|protected|static|using)\b",
    re.IGNORECASE,
)
def is_plain_codeish(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if has_stopwords(s):
        return False
    return bool(PLAIN_CODE_CHARS.search(s) or PLAIN_CODE_WORDS.search(s) or REPL_LINE_RE.match(s))

def norm_sev(word: str) -> str:
    w = (word or "").strip().lower()
    return RU_SEV_MAP.get(w, w)

def post_filter_snippet(lines: List[str]) -> str:
    out: List[str] = []
    seen = set()
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if has_stopwords(s) or is_header_footer(s) or DOC_MARKUP_RE.match(s) or NOISE_CHUNK_RE.search(s):
            continue
        # отбрасываем «обычное предложение» без кодовой пунктуации
        if len(s) > 80 and not PLAIN_CODE_CHARS.search(s) and not REPL_LINE_RE.match(s):
            continue
        # совсем «мягкий» фильтр: должно быть либо пунктуация кода, либо короткая строка с ключевым словом
        if not (PLAIN_CODE_CHARS.search(s) or REPL_LINE_RE.match(s) or PLAIN_CODE_WORDS.search(s)):
            # оставляем короткие (<=40) только если есть точка/скобка/кавычки рядом с буквой/цифрой
            if not (len(s) <= 40 and re.search(r"[A-Za-z0-9][\)\(\"'\]]", s)):
                continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= 12:  # не раздуваем сниппет
            break
    return "\n".join(out).strip()

# ───────────────────────── Парсер ─────────────────────────

class PdfReportImporter:
    """
    Робастный парсер PDF (Detailed Results, EN/RU):
    • жёстче фильтрует всё, что не похоже на код (особенно для .txt/.html);
    • поддерживает NN code, NN: code, «NN»→следующая строка, REPL (>>>);
    • маскирует Level/Status/служебные секции/шапки/стоп-слова;
    • если кода нет — берёт небольшой «безопасный» контекст (до 3 строк) только с кодовыми признаками.
    """

    def run(self, pdf_path: str) -> List[WarningDTO]:
        text = _clean(extract_text(pdf_path))
        lines = text.splitlines()

        items: List[WarningDTO] = []
        current_rule: Optional[str] = None
        current_desc: Optional[str] = None

        i = 0
        L = len(lines)
        while i < L:
            line = lines[i].rstrip()

            # Заголовок блока
            if BLOCK_TITLE_RE.match(line):
                current_rule = line.strip()
                current_desc = None
                i += 1
                continue

            # Короткое описание
            if DESCRIPTION_ANCHOR_RE.match(line):
                j = i + 1
                while j < L and not lines[j].strip():
                    j += 1
                if j < L and lines[j].strip():
                    current_desc = lines[j].strip()
                i += 1
                continue

            # Начало элемента — file:line
            m = PATH_LINE_RE.match(line)
            if m and current_rule:
                file_path = m.group("path").strip()
                if not STRICT_PATH_RE.search(file_path):
                    i += 1
                    continue

                ext = Path(file_path).suffix.lower()
                line_raw = m.group("line")
                start_line = int(line_raw.split("#", 1)[0]) if line_raw else None

                level_word = "unknown"
                raw_code: List[str] = []

                look = i + 1
                safety = 0
                pending_num = False
                in_code_block = False
                max_free = 60

                while look < L and safety < 250:
                    safety += 1
                    s = lines[look].rstrip()

                    # Границы
                    if PATH_LINE_RE.match(s) or BLOCK_TITLE_RE.match(s):
                        break

                    # Очевидный мусор
                    if not s.strip() or is_header_footer(s) or NOISE_CHUNK_RE.search(s) or DOC_MARKUP_RE.match(s):
                        look += 1
                        continue

                    # Уровень/Статус
                    lm = LEVEL_LINE_RE.search(s)
                    if lm:
                        level_word = lm.group("level").strip()
                        look += 1
                        continue
                    if STATUS_LINE_RE.search(s):
                        look += 1
                        continue

                    # Служебные секции — обрываем, если код уже шёл
                    if META_OR_SECTION_RE.search(s):
                        if in_code_block:
                            break
                        look += 1
                        continue

                    # Форматы кода
                    if REPL_LINE_RE.match(s):
                        raw_code.append(s.strip())
                        in_code_block = True
                        look += 1
                        continue

                    cmc = CODE_LINE_COLON_RE.match(s)
                    if cmc:
                        raw_code.append(cmc.group("code").rstrip())
                        in_code_block = True
                        look += 1
                        continue

                    cm = CODE_LINE_RE.match(s)
                    if cm:
                        raw_code.append(cm.group("code").rstrip())
                        in_code_block = True
                        look += 1
                        continue

                    nm = ONLY_NUM_LINE_RE.match(s)
                    if nm:
                        pending_num = True
                        look += 1
                        continue

                    if pending_num:
                        if s.strip() and not (is_header_footer(s) or META_OR_SECTION_RE.search(s)):
                            if looks_like_code_by_ext(s, ext) or is_plain_codeish(s):
                                raw_code.append(s.strip())
                                in_code_block = True
                            pending_num = False
                            look += 1
                            continue
                        look += 1
                        continue

                    # Свободные «кодовые» строки
                    if (ext in LOOSE_EXTS and looks_like_code_by_ext(s, ext)) or looks_like_code_by_ext(s, ext):
                        raw_code.append(s.strip())
                        in_code_block = True
                        max_free -= 1
                        look += 1
                        if max_free <= 0:
                            break
                        continue

                    if in_code_block:
                        break

                    look += 1

                snippet = post_filter_snippet(raw_code)
                if not snippet:
                    # Фолбэк: максимум 3 кодоподобные строки рядом
                    j = i + 1
                    take = 0
                    fallback: List[str] = []
                    while j < L and take < 3:
                        t = lines[j].strip()
                        if not t:
                            j += 1
                            continue
                        if PATH_LINE_RE.match(t) or BLOCK_TITLE_RE.match(t):
                            break
                        if not (is_header_footer(t) or NOISE_CHUNK_RE.search(t) or META_OR_SECTION_RE.search(t) or DOC_MARKUP_RE.match(t) or has_stopwords(t)):
                            if looks_like_code_by_ext(t, ext) or is_plain_codeish(t):
                                fallback.append(t)
                                take += 1
                        j += 1
                    snippet = post_filter_snippet(fallback)

                items.append(
                    WarningDTO(
                        rule=current_rule,
                        severity=WarningDTO.norm_sev(norm_sev(level_word)),
                        file_path=file_path,
                        start_line=start_line,
                        message=current_desc or current_rule,
                        code_snippet=snippet,
                    )
                )
                i = look
                continue

            i += 1

        return items
