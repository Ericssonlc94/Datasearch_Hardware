#!/usr/bin/env python3
"""Reabre neste terminal a sessão OpenCode registrada para uma função.

    python3 scripts/agentes/retomar.py dados

Existe porque `hc send` embrulha o texto em `<hc …>` (o fish quebra) e
`hc keys` não digita `_`, que todo id de sessão tem. Só com letras
minúsculas, espaço e `-`, o comando acima dá para digitar tecla a tecla.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

REGISTRO = Path(__file__).resolve().parents[2] / "docs" / "agentes" / "registro.md"
LINE = re.compile(r"^- (?P<label>[^=]+?) = terminal \S+ · sessão (?P<sessao>ses_\w+)")


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.split("(")[0].strip().lower()


def session_for(funcao: str) -> str:
    for line in REGISTRO.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match and _slug(match["label"]) == funcao:
            return match["sessao"]
    raise SystemExit(f"função {funcao!r} não está em {REGISTRO}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("uso: retomar.py <função>")
    os.chdir(REGISTRO.parents[2])
    os.execvp("opencode", ["opencode", "-s", session_for(sys.argv[1].lower())])
