"""API — segurança da coleta forçada (T10) e marcação da fila (T10b), offline.

Cobre, com `httpx.ASGITransport` (sem servidor real e sem lifespan) e o
coletor substituído por uma função local:

- T10: `POST /api/refresh` exige `X-DSH-Refresh: 1` (403), respeita o
  intervalo mínimo (429 com `Retry-After`), faz single-flight; `Host` fora da
  lista dá 400; `GET /api/snapshot?force=true` não coleta de novo; headers
  CSP/nosniff/Referrer-Policy (sem CSP em /docs); `public_error` tira o corpo
  de terceiros; coleta que falha sem snapshot dá 503 sem vazar a exceção.
- T10b: `model_breaks` marca o início da conta atual da fila e anda quando a
  versão muda; `/api/history` devolve `model_since` só na fila;
  `/api/methodology` expõe a fórmula em z-score e os prazos do câmbio;
  `ranking[].imports.source` vem do Comtrade mensal.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app.cache import Fetched  # noqa: E402
from app.schemas import PUBLIC_ERROR_MAX, public_error  # noqa: E402
from app.services import collector, history  # noqa: E402

BASE_URL = "http://127.0.0.1"
SEGREDO = "detalhe-interno-da-fonte https://api.exemplo/token=abc123"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=BASE_URL)


class ColetorFalso:
    """Substitui `collector.collect_and_build`: conta chamadas e pode dormir/falhar."""

    def __init__(self, delay: float = 0.0, exc: Exception | None = None) -> None:
        self.calls = 0
        self.delay = delay
        self.exc = exc

    async def __call__(self, force: bool = False):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return collector.build_snapshot({}), {}


@pytest.fixture()
def api(monkeypatch, tmp_path: Path):
    """Zera o estado global de app.main e aponta o histórico para tmp_path."""
    monkeypatch.setattr(main, "_snapshot", None)
    monkeypatch.setattr(main, "_inflight", None)
    monkeypatch.setattr(main, "_last_forced_at", None)
    monkeypatch.setattr(main, "_last_error", None)
    monkeypatch.setattr(main, "_purge_day", None)
    db = tmp_path / "historico.db"
    monkeypatch.setattr(history, "_db_path", history._db_path)  # restaura no fim
    monkeypatch.setattr(main.settings, "history_path", str(db))
    history.init_db(db)
    fake = ColetorFalso()
    monkeypatch.setattr(collector, "collect_and_build", fake)
    return fake


# ---------------- T10.1 — header anti-CSRF ----------------


@pytest.mark.parametrize("headers", [{}, {"X-DSH-Refresh": "0"}, {"X-DSH-Refresh": "true"}])
def test_refresh_sem_header_correto_da_403(api, headers):
    async def go():
        async with _client() as c:
            return await c.post("/api/refresh", headers=headers)

    r = asyncio.run(go())
    assert r.status_code == 403
    assert api.calls == 0


# ---------------- T10.2 — intervalo mínimo ----------------


def test_segundo_refresh_em_menos_de_60s_da_429_com_retry_after(api):
    async def go():
        async with _client() as c:
            a = await c.post("/api/refresh", headers={"X-DSH-Refresh": "1"})
            b = await c.post("/api/refresh", headers={"X-DSH-Refresh": "1"})
            return a, b

    a, b = asyncio.run(go())
    assert a.status_code == 200
    assert b.status_code == 429
    assert int(b.headers["Retry-After"]) > 0
    assert api.calls == 1


def test_refresh_com_intervalo_zero_aceita_os_dois(api, monkeypatch):
    monkeypatch.setattr(main.settings, "refresh_min_interval_seconds", 0)

    async def go():
        async with _client() as c:
            a = await c.post("/api/refresh", headers={"X-DSH-Refresh": "1"})
            b = await c.post("/api/refresh", headers={"X-DSH-Refresh": "1"})
            return a, b

    a, b = asyncio.run(go())
    assert (a.status_code, b.status_code) == (200, 200)
    assert api.calls == 2


# ---------------- T10.3 — single-flight ----------------


def test_refresh_simultaneos_chamam_o_coletor_uma_vez(api):
    api.delay = 0.2

    async def go():
        async with _client() as c:
            return await asyncio.gather(
                *(c.post("/api/refresh", headers={"X-DSH-Refresh": "1"}) for _ in range(6))
            )

    respostas = asyncio.run(go())
    assert [r.status_code for r in respostas] == [200] * 6
    assert api.calls == 1


# ---------------- T10.4 — TrustedHost ----------------


@pytest.mark.parametrize("rota", ["/", "/api/methodology", "/api/health"])
def test_host_desconhecido_da_400(api, rota):
    async def go():
        async with _client() as c:
            return await c.get(rota, headers={"Host": "evil.example"})

    assert asyncio.run(go()).status_code == 400


def test_host_localhost_com_porta_e_aceito(api):
    async def go():
        async with _client() as c:
            return await c.get("/api/methodology", headers={"Host": "localhost:8000"})

    assert asyncio.run(go()).status_code == 200


# ---------------- T10.5 — GET sem efeito colateral ----------------


def test_get_snapshot_force_com_snapshot_existente_nao_coleta(api, monkeypatch):
    monkeypatch.setattr(main, "_snapshot", collector.build_snapshot({}))

    async def go():
        async with _client() as c:
            return await c.get("/api/snapshot", params={"force": "true"})

    r = asyncio.run(go())
    assert r.status_code == 200
    assert api.calls == 0


# ---------------- T10.6 — headers de segurança ----------------


@pytest.mark.parametrize("rota", ["/", "/api/methodology", "/api/progress"])
def test_headers_de_seguranca_no_painel_e_na_api(api, rota):
    async def go():
        async with _client() as c:
            return await c.get(rota)

    r = asyncio.run(go())
    assert r.status_code == 200
    assert r.headers["Content-Security-Policy"] == main.CONTENT_SECURITY_POLICY
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_docs_fica_sem_csp(api):
    async def go():
        async with _client() as c:
            return await c.get("/docs")

    r = asyncio.run(go())
    assert r.status_code == 200
    assert "Content-Security-Policy" not in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"


# ---------------- T10.7 — public_error ----------------


def test_public_error_omite_corpo_de_terceiros():
    msg = "resposta nao-JSON de https://x: '<html><body>erro interno</body></html>'"
    out = public_error(msg)
    assert "<html>" not in out
    assert "erro interno" not in out
    assert out.startswith("resposta nao-JSON de https://x")
    assert "[corpo da resposta omitido]" in out


def test_public_error_corta_em_200_caracteres():
    out = public_error("falha " + "x" * 500)
    assert len(out) == PUBLIC_ERROR_MAX == 200
    assert out.endswith("…")


def test_public_error_preserva_vazio_e_mensagem_curta():
    assert public_error(None) is None
    assert public_error("") == ""
    assert public_error("HTTP 503   em\nhttps://x") == "HTTP 503 em https://x"


# ---------------- T10.8 — falha sem snapshot ----------------


def test_coleta_que_falha_sem_snapshot_da_503_sem_vazar_texto(api):
    api.exc = RuntimeError(SEGREDO)

    async def go():
        async with _client() as c:
            snap = await c.get("/api/snapshot")
            saude = await c.get("/api/health")
            return snap, saude

    snap, saude = asyncio.run(go())
    assert snap.status_code == 503
    assert SEGREDO not in snap.text
    corpo = saude.json()
    assert corpo["status"] == "warming"
    assert corpo["last_error"].startswith("RuntimeError")
    assert SEGREDO not in corpo["last_error"]
    assert "token" not in saude.text


# ---------------- T10b — marco da conta da fila ----------------


def _snap_com_fila(when: datetime, fila: float = 42.0):
    snap = collector.build_snapshot({})
    snap.supply.queue_pressure = fila
    return snap.model_copy(update={"generated_at": when})


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_model_breaks_marca_o_primeiro_snapshot_e_anda_com_a_versao(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_db_path", history._db_path)
    db = history.init_db(tmp_path / "fila.db")
    t1 = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=15)
    t3 = t1 + timedelta(hours=2)

    history.record_snapshot(_snap_com_fila(t1), path=db)
    history.record_snapshot(_snap_com_fila(t2), path=db)
    assert history.model_breaks(path=db) == {"supply.queue": _iso(t1)}

    monkeypatch.setattr(history, "QUEUE_MODEL_VERSION", "teste-versao-nova")
    history.record_snapshot(_snap_com_fila(t3), path=db)
    assert history.model_breaks(path=db) == {"supply.queue": _iso(t3)}


def test_model_breaks_vazio_sem_fila(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_db_path", history._db_path)
    db = history.init_db(tmp_path / "sem_fila.db")
    history.record_snapshot(collector.build_snapshot({}), path=db)  # fila None
    assert history.model_breaks(path=db) == {}


def test_api_history_model_since_so_na_fila(api):
    agora = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    history.record_snapshot(_snap_com_fila(agora))

    async def go():
        async with _client() as c:
            return await c.get("/api/history", params={"series": "supply.queue,iph"})

    r = asyncio.run(go())
    assert r.status_code == 200
    series = {s["key"]: s for s in r.json()["series"]}
    assert series["supply.queue"]["model_since"] == _iso(agora)
    assert series["iph"]["model_since"] is None


def test_api_methodology_fila_em_zscore_e_prazos_do_cambio(api):
    async def go():
        async with _client() as c:
            return await c.get("/api/methodology")

    corpo = asyncio.run(go()).json()
    assert "/10" not in corpo["queue"]["formula"]
    assert corpo["queue"]["model_version"] == history.QUEUE_MODEL_VERSION
    assert "inventory_scale" not in corpo["queue"]
    assert corpo["fx_passthrough_days"] == 90
    assert corpo["fx_horizon_days"] == 30


# ---------------- T10b — CategoryImport.source ----------------


def _comtrade_mensal(cat_key: str, sh6: str) -> Fetched:
    months = [
        {"period": f"{2025 + (m // 12)}-{m % 12 + 1:02d}", "fob_usd": 1_000_000.0,
         "kg": 1_000.0, "usd_per_kg": 1_000.0 + m}
        for m in range(8, 20)  # 2025-09 .. 2026-08
    ]
    return Fetched(
        key=f"comtrade_monthly.{cat_key}",
        label=f"UN Comtrade — importação mensal (SH6 {sh6})",
        provider="United Nations Comtrade (preview público), dado da SECEX",
        url="",
        status="ok",
        payload={"months": months, "sh6": sh6},
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def test_snapshot_com_comtrade_mensal_rotula_a_fonte(api, monkeypatch):
    collected = {"comtrade_monthly.gpu": _comtrade_mensal("gpu", "847330")}
    collector._share_by_sh6(collected, "comtrade_monthly")
    monkeypatch.setattr(main, "_snapshot", collector.build_snapshot(collected))

    async def go():
        async with _client() as c:
            return await c.get("/api/snapshot")

    r = asyncio.run(go())
    assert r.status_code == 200
    imports = {item["key"]: item["imports"] for item in r.json()["ranking"]}
    for key in ("gpu", "motherboard"):
        assert imports[key]["source"] == "UN Comtrade (dado SECEX)"
        assert imports[key]["status"] == "ok"
        assert imports[key]["period"] == "2026-08"
    assert imports["ram"]["source"] is None
    assert api.calls == 0
