from pydantic import BaseModel

class WarningDTO(BaseModel):
    id: str
    rule_id: str
    severity: str
    message: str
    file_path: str
    start_line: int
    end_line: int
    raw: str = ""
    code_snippet: str = ""  # Новое поле для фрагмента кода из PDF