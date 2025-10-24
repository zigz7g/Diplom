# services/code_provider.py
from pathlib import Path

class SimpleCodeProvider:
    def get_context(self, file_path: str, start_line: int, window: int = 30) -> str:
        p = Path(file_path)
        if not p.exists():
            return f"Файл не найден: {file_path}"
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return f"Не удалось прочитать файл: {file_path}"
        s = max(1, start_line - window)
        e = min(len(lines), start_line + window)
        out = []
        for i in range(s, e + 1):
            mark = ">>" if i == start_line else "  "
            out.append(f"{mark} {i:6d}: {lines[i-1]}")
        return "\n".join(out)