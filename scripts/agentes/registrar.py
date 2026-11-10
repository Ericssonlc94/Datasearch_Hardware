#!/usr/bin/env python3
"""Registra/atualiza a linha de um painel em docs/agentes/registro.md.

Uso:
    python scripts/agentes/registrar.py dados --terminal t1
    python scripts/agentes/registrar.py coordenador --terminal t10 --sessao ses_...

O terminal é obrigatório. No servidor compartilhado do OpenCode,
`$HC_TERMINAL_ID` reporta o terminal onde o servidor nasceu (o do Coordenador),
não o terminal do painel; por isso o valor vem explícito.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRO = ROOT / "docs" / "agentes" / "registro.md"

LABELS = {
    "coordenador": "Coordenador (+Documentação)",
    "dados": "Dados",
    "modelo": "Modelo",
    "backend": "Backend",
    "frontend": "Frontend",
    "qa": "QA",
    "seguranca": "Segurança",
}

TERMINAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")


def _line_for(funcao: str, terminal: str, sessao: str) -> str:
    label = LABELS[funcao]
    extra = f" · sessão {sessao}" if sessao else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"- {label} = terminal {terminal}{extra} (desde {now})"


PANEL_ORDER = ["coordenador", "dados", "modelo", "backend", "frontend", "qa", "seguranca"]

LABEL_TO_FUNCAO = {label: funcao for funcao, label in LABELS.items()}
LABEL_TO_FUNCAO["Coordenador"] = "coordenador"


def _panel_key(line: str) -> str | None:
    if not line.startswith("- "):
        return None
    label = line[2:].split(" =", 1)[0].strip()
    return LABEL_TO_FUNCAO.get(label)


def _rebuild(lines: list[str], funcao: str, line: str) -> list[str]:
    if "## Painéis" not in lines:
        lines.extend(["", "## Painéis"])
    idx = lines.index("## Painéis")
    end = idx + 1
    while end < len(lines) and lines[end].strip() and not lines[end].startswith("#"):
        end += 1

    entries: dict[str, str] = {}
    others: list[str] = []
    for current in lines[idx + 1 : end]:
        key = _panel_key(current)
        if key:
            entries[key] = current
        else:
            others.append(current)

    entries[funcao] = line
    section = [entries[fn] for fn in PANEL_ORDER if fn in entries] + others
    return lines[: idx + 1] + section + lines[end:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("funcao", choices=sorted(LABELS))
    ap.add_argument("--terminal", default=os.environ.get("HC_TERMINAL_ID", ""))
    ap.add_argument("--sessao", default=os.environ.get("OPENCODE_SESSION_ID", ""))
    args = ap.parse_args()

    terminal = args.terminal.strip()
    if not terminal:
        print(
            "terminal vazio: passe --terminal tN; não confie em "
            "$HC_TERMINAL_ID no servidor compartilhado",
            file=sys.stderr,
        )
        return 2
    if not TERMINAL_RE.fullmatch(terminal):
        print(f"terminal inválido: {terminal!r}", file=sys.stderr)
        return 2

    sessao = args.sessao.strip()
    if sessao and not re.fullmatch(r"ses_[A-Za-z0-9]+", sessao):
        print(f"sessão inválida: {sessao!r}", file=sys.stderr)
        return 2

    if not REGISTRO.exists():
        print(f"não encontrei {REGISTRO}", file=sys.stderr)
        return 2

    line = _line_for(args.funcao, terminal, sessao)

    with REGISTRO.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            lines = _rebuild(fh.read().splitlines(), args.funcao, line)
            fh.seek(0)
            fh.write("\n".join(lines).rstrip() + "\n")
            fh.truncate()
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)

    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
