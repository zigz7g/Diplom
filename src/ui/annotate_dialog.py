# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QRadioButton, QGroupBox
)

class AnnotateDialog(QDialog):
    def __init__(self, parent, status: str, severity: str, comment: str):
        super().__init__(parent)
        self.setWindowTitle("Разметка")
        self.resize(460, 280)

        v = QVBoxLayout(self)

        box = QGroupBox("Изменить статус")
        hb = QHBoxLayout(box)
        self.rb_new = QRadioButton("Не обработано")
        self.rb_ok  = QRadioButton("Подтверждено")
        self.rb_rej = QRadioButton("Отклонено")
        hb.addWidget(self.rb_ok); hb.addWidget(self.rb_rej); hb.addWidget(self.rb_new)
        v.addWidget(box)

        box2 = QGroupBox("Критичность (опционально)")
        hb2 = QHBoxLayout(box2)
        self.rb_c = QRadioButton("Critical")
        self.rb_m = QRadioButton("Medium")
        self.rb_l = QRadioButton("Low")
        self.rb_i = QRadioButton("Info")
        hb2.addWidget(self.rb_c); hb2.addWidget(self.rb_m); hb2.addWidget(self.rb_l); hb2.addWidget(self.rb_i)
        v.addWidget(box2)

        v.addWidget(QLabel("Комментарий"))
        self.ed = QTextEdit(); v.addWidget(self.ed, 1)

        h = QHBoxLayout(); h.addStretch(1)
        btn_cancel = QPushButton("Отмена"); btn_ok = QPushButton("Применить")
        h.addWidget(btn_cancel); h.addWidget(btn_ok); v.addLayout(h)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self.accept)

        (self.rb_ok if status=="Подтверждено" else self.rb_rej if status=="Отклонено" else self.rb_new).setChecked(True)
        {"critical": self.rb_c, "medium": self.rb_m, "low": self.rb_l, "info": self.rb_i}.get(severity, self.rb_m).setChecked(True)
        self.ed.setText(comment or "")

    def chosen(self):
        status = "Не обработано"
        if self.rb_ok.isChecked(): status = "Подтверждено"
        elif self.rb_rej.isChecked(): status = "Отклонено"
        severity = (
            "critical" if self.rb_c.isChecked() else
            "low"      if self.rb_l.isChecked() else
            "info"     if self.rb_i.isChecked() else
            "medium"
        )
        return status, severity, self.ed.toPlainText().strip()
