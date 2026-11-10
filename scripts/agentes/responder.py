#!/usr/bin/env python3
"""Envia a resposta de um painel ao Coordenador via `hc send`.

Uso:
    python scripts/agentes/responder.py dados "texto em uma linha"
    python scripts/agentes/responder.py dados <<'EOF'
    [Dados] T05 — feito
    ...
    EOF

O terminal do Coordenador é lido de docs/agentes/registro.md; se não houver
linha, usa $HC_COORDINATOR_TERMINAL ou t10.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRO = ROOT / "docs" / "agentes" / "registro.md"

LABELS = {
    "coordenador": "Coordenador",
    "dados": "Dados",
    "modelo": "Modelo",
    "backend": "Backend",
    "frontend": "Frontend",
    "qa": "QA",
    "seguranca": "Segurança",
}


def coordinator_terminal() -> str:
    try:
        text = REGISTRO.read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r"^-\s*Coordenador[^=]*=\s*terminal\s+(\S+)", text, re.M)
    if match:
        return match.group(1)
    return os.environ.get("HC_COORDINATOR_TERMINAL", "t10")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("funcao", choices=sorted(LABELS))
    ap.add_argument("mensagem", nargs="*", help="texto; sem argumentos, lê stdin")
    args = ap.parse_args()

    message = " ".join(args.mensagem).strip()
    if not message and not sys.stdin.isatty():
        message = sys.stdin.read().strip()
    if not message:
        print("mensagem vazia", file=sys.stderr)
        return 2

    if not message.startswith("["):
        message = f"[{LABELS[args.funcao]}] {message}"

    hc = shutil.which("hc") or str(Path.home() / ".local/bin" / "hc")
    target = coordinator_terminal()
    result = subprocess.run(
        [hc, "send", target, message],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        print(f"falha ao enviar para {target}: {detail}", file=sys.stderr)
        return 1

    print(f"ok: enviado para {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
