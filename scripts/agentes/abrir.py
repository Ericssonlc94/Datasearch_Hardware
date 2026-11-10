#!/usr/bin/env python3
"""Abre/assume os painéis fixos no herdr.

Cria uma sessão OpenCode por função (agente já definido), abre o TUI no terminal
combinado e envia o primeiro prompt de adoção. Uso pelo Coordenador, somente
depois de autorização explícita do usuário.

    python scripts/agentes/abrir.py            # todos
    python scripts/agentes/abrir.py dados qa   # só alguns
    python scripts/agentes/abrir.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRAR = ROOT / "scripts" / "agentes" / "registrar.py"
STATUS = ROOT / "scripts" / "agentes" / "herdr_status.py"

PANELS = {
    "dados": {"label": "Dados", "terminal": "t1"},
    "modelo": {"label": "Modelo", "terminal": "t3"},
    "backend": {"label": "Backend", "terminal": "t2"},
    "frontend": {"label": "Frontend", "terminal": "t6"},
    "qa": {"label": "QA", "terminal": "t7"},
    "seguranca": {"label": "Segurança", "terminal": None},  # aba nova
}

SHELLS = {"fish", "sh", "bash", "zsh", "dash", "ksh", "nu"}


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, text=True, capture_output=True, cwd=ROOT)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(cmd)}: {detail}")
    return result


def api(method: str, path: str, payload: dict | None = None) -> dict:
    cmd = ["opencode", "api", method, path]
    if payload is not None:
        cmd += ["--data", json.dumps(payload, ensure_ascii=False)]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            f"{method} {path}: {result.stderr.strip() or result.stdout.strip()}"
        )
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"resposta não-JSON de {path}: {result.stdout[:200]}"
        ) from exc


def terminal_info(term: str) -> dict:
    result = run(["hc", "get", term])
    if result.returncode != 0:
        raise RuntimeError(
            f"terminal {term} não encontrado: {result.stderr.strip() or result.stdout.strip()}"
        )
    return json.loads(result.stdout)


def check_shell(term: str, force: bool) -> None:
    info = terminal_info(term)
    if info.get("state") != "live":
        raise RuntimeError(f"terminal {term} não está vivo ({info.get('state')})")
    foreground = info.get("foreground") or {}
    argv = foreground.get("argv") or []
    name = (foreground.get("name") or (Path(argv[0]).name if argv else "")).lower()
    if name not in SHELLS and not force:
        raise RuntimeError(
            f"terminal {term} está com {name or 'outro programa'}, não num shell; "
            "use --force se for isso mesmo"
        )
    status = info.get("status")
    if status not in (None, "idle", "done") and not force:
        raise RuntimeError(f"terminal {term} ocupado (status={status}); use --force")


def hc_send(term: str, text: str) -> None:
    # Limpa qualquer linha digitada e garante que o shell está no prompt.
    run(["hc", "keys", term, "ctrl+c"])
    result = run(["hc", "send", term, text])
    if result.returncode != 0:
        raise RuntimeError(
            f"hc send {term}: {result.stderr.strip() or result.stdout.strip()}"
        )


def new_tab(label: str, session: str) -> str:
    result = run(
        [
            "herdr-app",
            "do",
            "tab.new",
            "--name",
            label,
            "--folder",
            str(ROOT),
            "--argv",
            json.dumps(["opencode", "--session", session]),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tab.new {label}: {result.stderr.strip() or result.stdout.strip()}"
        )
    info = json.loads(result.stdout)
    term = info.get("terminal") or info.get("address")
    if not term:
        terminals = info.get("terminals") or []
        if terminals:
            term = terminals[0].get("terminal") or terminals[0].get("address")
    if not term:
        raise RuntimeError(f"tab.new {label}: resposta sem terminal: {result.stdout[:200]}")
    return term


def adoption(funcao: str, label: str, term: str, session: str) -> str:
    return (
        f"Assuma a função {label} neste painel. Seu terminal é {term}.\n\n"
        f"1. Leia `docs/agentes/papeis/{funcao}.md` e `docs/PRD.md`.\n"
        f"2. Registre: `python scripts/agentes/registrar.py {funcao} "
        f"--terminal {term} --sessao {session}`\n"
        f"3. Responda em uma linha: função, terminal e pastas que pode editar.\n"
        f"4. Fique disponível para `[Coordenador → {label}]`.\n\n"
        "Estilo conciso. Não abra nem altere outros painéis e não faça commit."
    )


def start_status() -> None:
    """Liga o reporter OSC 7501 que faz os painéis aparecerem no lateral."""
    result = run([sys.executable, str(STATUS), "--daemon"])
    detail = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0:
        print(f"status herdr: {detail}", file=sys.stderr)
    elif detail:
        print(f"status herdr: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("funcoes", nargs="*", choices=sorted(PANELS))
    ap.add_argument("--force", action="store_true", help="usa o terminal mesmo ocupado")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chosen = args.funcoes or list(PANELS)
    rows: list[tuple[str, str, str]] = []
    failures = 0

    for funcao in chosen:
        cfg = PANELS[funcao]
        label, term = cfg["label"], cfg["terminal"]
        try:
            if args.dry_run:
                rows.append((label, term or "nova aba", "dry-run"))
                continue
            if term:
                check_shell(term, args.force)

            body = api(
                "post",
                "/api/session",
                {
                    "title": label,
                    "agent": funcao,
                    "location": {"directory": str(ROOT)},
                },
            )
            session = (body.get("data") or {}).get("id")
            if not session:
                raise RuntimeError(f"sessão sem id: {body}")

            if term is None:
                term = new_tab(label, session)
            else:
                hc_send(term, f"opencode --session {session}")

            run(
                [
                    sys.executable,
                    str(REGISTRAR),
                    funcao,
                    "--terminal",
                    term,
                    "--sessao",
                    session,
                ],
                check=True,
            )
            api(
                "post",
                f"/api/session/{session}/prompt",
                {"text": adoption(funcao, label, term, session)},
            )
            rows.append((label, term, session))
        except Exception as exc:  # noqa: BLE001 — um painel não derruba os outros
            failures += 1
            rows.append((label, term or "-", f"ERRO: {exc}"))

    print(f"{'Função':<24} {'Terminal':<10} Sessão / resultado")
    for label, term, detail in rows:
        print(f"{label:<24} {term:<10} {detail}")
    if not args.dry_run:
        start_status()
    if failures:
        print(f"\n{failures} painel(es) com erro.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
