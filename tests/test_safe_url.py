"""Frontend — `safeUrl` de app/static/app.js, executada no Node.

Cobre a defesa de links das manchetes: só `http:`/`https:` absolutos viram
href; `javascript:` (inclusive com caixa mista e tab no meio), `data:`, URL
relativa e `//host` sem esquema são recusados (`null`). A função é extraída do
fonte e rodada com `node` via subprocess; sem `node` ou sem a função, pula.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

CASOS = {
    "javascript:alert(1)": None,
    "JaVa\tScript:alert(1)": None,
    " javascript:alert(1)": None,
    "data:text/html,<script>alert(1)</script>": None,
    "/noticia/relativa": None,
    "noticia.html": None,
    "//evil.example/x": None,
    "": None,
    "https://example.com/a?b=1": "https://example.com/a?b=1",
    "http://example.com": "http://example.com/",
}


def _fonte_safe_url() -> str | None:
    for js in sorted(STATIC.glob("*.js")):
        texto = js.read_text(encoding="utf-8")
        m = re.search(r"^function safeUrl\(.*?^\}", texto, re.S | re.M)
        if m:
            return m.group(0)
    return None


def _rodar_no_node(fonte: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node não está no PATH")
    script = (
        fonte
        + "\nconst casos = JSON.parse(process.argv[1]);"
        + "\nconst out = {}; for (const c of casos) out[c] = safeUrl(c);"
        + "\nout['__null__'] = safeUrl(null); out['__undef__'] = safeUrl(undefined);"
        + "\nprocess.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [node, "-e", script, json.dumps(list(CASOS))],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def resultados() -> dict:
    fonte = _fonte_safe_url()
    if fonte is None:
        pytest.skip("safeUrl não encontrada em app/static/*.js")
    return _rodar_no_node(fonte)


@pytest.mark.parametrize(("entrada", "esperado"), list(CASOS.items()), ids=repr)
def test_safe_url_aceita_so_http_absoluto(resultados, entrada, esperado):
    assert resultados[entrada] == esperado


def test_safe_url_nulo_e_indefinido_viram_null(resultados):
    assert resultados["__null__"] is None
    assert resultados["__undef__"] is None
