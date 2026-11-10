#!/usr/bin/env python3
"""Publica o estado das sessões OpenCode dos painéis no herdr (OSC 7501).

O herdr lista no painel lateral apenas terminais cujo programa reporta estado.
Esta versão do herdr não traz a integração oficial do OpenCode, então este
processo lê o estado pelo servidor do OpenCode e escreve o protocolo OSC 7501
no tty de cada painel. Não altera o OpenCode nem os painéis.

Uso:
    python3 scripts/agentes/herdr_status.py --once
    python3 scripts/agentes/herdr_status.py --daemon
    python3 scripts/agentes/herdr_status.py --stop
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRO = ROOT / "docs/agentes/registro.md"
SERVICE = Path.home() / ".config/opencode/service.json"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "datasearch-hardware"
PIDFILE = CACHE_DIR / "herdr-status.pid"
LOGFILE = CACHE_DIR / "herdr-status.log"

PANEL_RE = re.compile(
    r"^-\s*(?P<name>.+?)\s*=\s*terminal\s+(?P<terminal>t\d+)\s*·\s*"
    r"sess[ãa]o\s+(?P<session>ses_[A-Za-z0-9]+)",
    re.MULTILINE,
)
OSC = "\x1b]7501;state={state}:app=opencode{kind}\x1b\\"
VALID_STATES = {"idle", "working", "blocked"}


@dataclass(frozen=True)
class Panel:
    name: str
    terminal: str
    session: str


@dataclass
class Tracked:
    panel: Panel
    tty: str | None = None
    state: str | None = None
    kind: str | None = None
    tty_checked: float = 0.0
    permission: bool = False
    permission_checked: float = 0.0
    form: bool = False
    form_checked: float = 0.0


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def read_panels(path: Path = REGISTRO) -> list[Panel]:
    """Lê o registro de painéis; ignora linhas sem sessão (a abrir)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    seen: set[str] = set()
    panels: list[Panel] = []
    for match in PANEL_RE.finditer(text):
        terminal = match.group("terminal")
        if terminal in seen:
            continue
        seen.add(terminal)
        panels.append(
            Panel(
                name=match.group("name").strip(),
                terminal=terminal,
                session=match.group("session"),
            )
        )
    return panels


def service_password() -> str | None:
    try:
        data = json.loads(SERVICE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    password = data.get("password")
    return password if isinstance(password, str) and password else None


def discover_port() -> int | None:
    """Descobre a porta local do serviço do OpenCode."""
    try:
        out = subprocess.run(
            ["ss", "-ltnp"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        if "127.0.0.1:" not in line or "opencode" not in line:
            continue
        match = re.search(r"127\.0\.0\.1:(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def api_get(port: int, password: str, path: str) -> dict | None:
    """GET autenticado no servidor do OpenCode; None em qualquer falha."""
    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.load(response)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def active_sessions(port: int, password: str) -> set[str]:
    data = api_get(port, password, "/api/session/active")
    if not data:
        return set()
    payload = data.get("data")
    return set(payload) if isinstance(payload, dict) else set()


def hc_get(terminal: str) -> dict | None:
    try:
        result = subprocess.run(
            ["hc", "get", terminal, "--json"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def terminal_tty(terminal: str) -> str | None:
    """tty do processo em primeiro plano, só quando há um OpenCode nele."""
    info = hc_get(terminal)
    if not info or info.get("state") != "live":
        return None
    foreground = info.get("foreground") or {}
    argv = foreground.get("argv") or []
    name = (foreground.get("name") or "").lower()
    if name not in {"opencode", "opencode2"} and "opencode" not in " ".join(argv):
        return None
    pid = foreground.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return None


def write_status(tty: str | None, state: str, kind: str | None = None) -> bool:
    if not tty or state not in VALID_STATES:
        return False
    suffix = f":kind={kind}" if kind in {"permission", "question", "auth"} else ""
    payload = OSC.format(state=state, kind=suffix).encode()
    try:
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    except OSError:
        return False
    return True


def pending(tracked: Tracked, port: int, password: str, now: float) -> tuple[bool, bool]:
    """(permissão pendente, formulário pendente), com cache curto."""
    if now - tracked.permission_checked > 2:
        data = api_get(port, password, f"/api/session/{tracked.panel.session}/permission")
        tracked.permission = bool(data and data.get("data"))
        tracked.permission_checked = now
    if now - tracked.form_checked > 5:
        data = api_get(port, password, f"/api/session/{tracked.panel.session}/form")
        tracked.form = bool(data and data.get("data"))
        tracked.form_checked = now
    return tracked.permission, tracked.form


def resolve_state(
    tracked: Tracked,
    active: set[str],
    port: int,
    password: str,
    now: float,
) -> tuple[str, str | None]:
    permission, form = pending(tracked, port, password, now)
    if permission:
        return "blocked", "permission"
    if form:
        return "blocked", "question"
    if tracked.panel.session in active:
        return "working", None
    return "idle", None


def emit(tracked: Tracked, state: str, kind: str | None) -> None:
    if not write_status(tracked.tty, state, kind):
        return
    tracked.state = state
    tracked.kind = kind
    detail = f" ({kind})" if kind else ""
    log(f"{tracked.panel.terminal} {tracked.panel.name}: {state}{detail}")


def refresh_tty(tracked: Tracked, now: float, force: bool = False) -> bool:
    if not force and tracked.tty and now - tracked.tty_checked < 15:
        return True
    tty = terminal_tty(tracked.panel.terminal)
    tracked.tty_checked = now
    if tty != tracked.tty:
        tracked.tty = tty
        tracked.state = None
        tracked.kind = None
    return tty is not None


def run_once() -> int:
    password = service_password()
    port = discover_port()
    if not password or not port:
        log("servidor do OpenCode não encontrado")
        return 1
    panels = read_panels()
    if not panels:
        log("nenhum painel registrado")
        return 1
    active = active_sessions(port, password)
    now = time.monotonic()
    for panel in panels:
        tracked = Tracked(panel=panel, tty=terminal_tty(panel.terminal))
        if not tracked.tty:
            print(f"{panel.terminal:4} {panel.name:24} sem tty (painel não iniciado)")
            continue
        state, kind = resolve_state(tracked, active, port, password, now)
        detail = f" ({kind})" if kind else ""
        print(f"{panel.terminal:4} {panel.name:24} {state}{detail}")
    return 0


def run_forever() -> int:
    panels = read_panels()
    if not panels:
        log("nenhum painel registrado")
        return 1
    tracked = {panel.terminal: Tracked(panel=panel) for panel in panels}
    password = service_password()
    port = discover_port()
    last_reload = time.monotonic()
    last_port_check = last_reload
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log(f"iniciado: {len(panels)} painéis")
    while not stopping:
        now = time.monotonic()
        if now - last_reload > 10:
            current = {panel.terminal: panel for panel in read_panels()}
            for terminal in list(tracked):
                if terminal not in current:
                    write_status(tracked[terminal].tty, "clear")
                    del tracked[terminal]
            for terminal, panel in current.items():
                if terminal in tracked and tracked[terminal].panel != panel:
                    write_status(tracked[terminal].tty, "clear")
                    tracked[terminal] = Tracked(panel=panel)
                elif terminal not in tracked:
                    tracked[terminal] = Tracked(panel=panel)
            last_reload = now

        if port is None or now - last_port_check > 30:
            port = discover_port()
            last_port_check = now

        if port is None or not password:
            time.sleep(1)
            continue

        active = active_sessions(port, password)
        for terminal, item in list(tracked.items()):
            if not refresh_tty(item, now):
                continue
            state, kind = resolve_state(item, active, port, password, now)
            if state != item.state or kind != item.kind:
                emit(item, state, kind)

        time.sleep(1)

    for item in tracked.values():
        write_status(item.tty, "clear")
    log("encerrado")
    return 0


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid() -> int | None:
    try:
        return int(PIDFILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def start_daemon() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pid = read_pid()
    if pid and pid_alive(pid):
        print(f"já rodando (pid {pid})")
        return 0
    with LOGFILE.open("ab") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--run"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    PIDFILE.write_text(str(process.pid), encoding="utf-8")
    print(f"iniciado (pid {process.pid}, log {LOGFILE})")
    return 0


def stop_daemon() -> int:
    pid = read_pid()
    if not pid:
        print("não está rodando")
        return 0
    if pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
    try:
        PIDFILE.unlink()
    except OSError:
        pass
    print(f"parado (pid {pid})")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="imprime o estado e sai")
    group.add_argument("--run", action="store_true", help="roda em primeiro plano")
    group.add_argument("--daemon", action="store_true", help="inicia em segundo plano")
    group.add_argument("--stop", action="store_true", help="para o processo em segundo plano")
    args = parser.parse_args(argv)

    if args.once:
        return run_once()
    if args.stop:
        return stop_daemon()
    if args.daemon:
        return start_daemon()
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
