"""Coletor — importação mensal pelo UN Comtrade (T11), offline.

Cobre a montagem dos jobs `comtrade_monthly.*` (um por SH6, sem Comex Stat),
a herança por SH6 (`motherboard` herda de `gpu`, 847330) e o `collect()`
completo com os fetchers substituídos por dado local num cache novo.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched, TTLCache  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.catalog import CATEGORIES  # noqa: E402
from app.services import collector  # noqa: E402

PREFIX = "comtrade_monthly"


def _ok(key: str, sh6: str = "847330") -> Fetched:
    return Fetched(
        key=key,
        label=key,
        provider="teste",
        url="",
        status="ok",
        payload={"months": [{"period": "2026-08", "fob_usd": 1.0, "kg": 1.0, "usd_per_kg": 1.0}],
                 "sh6": sh6},
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def _indisponivel(key: str) -> Fetched:
    return Fetched(key=key, label=key, provider="teste", url="", status="unavailable",
                   error="falhou")


@pytest.fixture()
def padrao(monkeypatch):
    """Flags de importação no valor padrão do Settings (ignora um .env local)."""
    for flag in ("enable_comtrade_monthly", "enable_comexstat"):
        monkeypatch.setattr(collector.settings, flag, Settings.model_fields[flag].default)


# ---------------- _tasks ----------------


def test_padrao_liga_comtrade_mensal_e_desliga_comexstat():
    assert Settings.model_fields["enable_comtrade_monthly"].default is True
    assert Settings.model_fields["enable_comexstat"].default is False


def test_tasks_padrao_um_job_comtrade_mensal_por_sh6(padrao):
    keys = [k for k, _, _ in collector._tasks()]
    mensais = [k for k in keys if k.startswith(f"{PREFIX}.")]
    assert len(mensais) == 9 == len({c.sh6 for c in CATEGORIES})
    assert len(set(mensais)) == 9
    assert f"{PREFIX}.gpu" in mensais
    assert f"{PREFIX}.motherboard" not in mensais  # mesmo SH6 da gpu
    assert not [k for k in keys if k.startswith("comexstat.")]


def test_tasks_comtrade_mensal_usa_ttl_mensal(padrao):
    ttls = {ttl for k, ttl, _ in collector._tasks() if k.startswith(f"{PREFIX}.")}
    assert ttls == {collector.settings.ttl_monthly}


def test_tasks_sem_comtrade_mensal(padrao, monkeypatch):
    monkeypatch.setattr(collector.settings, "enable_comtrade_monthly", False)
    keys = [k for k, _, _ in collector._tasks()]
    assert not [k for k in keys if k.startswith(f"{PREFIX}.")]


# ---------------- _share_by_sh6 ----------------


def test_share_by_sh6_motherboard_herda_da_gpu():
    gpu = _ok(f"{PREFIX}.gpu")
    collected = {f"{PREFIX}.gpu": gpu}
    collector._share_by_sh6(collected, PREFIX)
    assert collected[f"{PREFIX}.motherboard"] is gpu


def test_share_by_sh6_gpu_indisponivel_nao_cria_motherboard():
    gpu = _indisponivel(f"{PREFIX}.gpu")
    collected = {f"{PREFIX}.gpu": gpu}
    collector._share_by_sh6(collected, PREFIX)
    assert f"{PREFIX}.motherboard" not in collected
    assert collected[f"{PREFIX}.gpu"] is gpu


# ---------------- collect() ----------------


def test_collect_com_fetchers_simulados_entrega_10_chaves(padrao, monkeypatch):
    s = collector.settings
    for flag in ("enable_fred", "enable_markets", "enable_news_rss", "enable_usgs",
                 "enable_fedreg", "enable_comtrade", "enable_sec"):
        monkeypatch.setattr(s, flag, False)
    monkeypatch.setattr(collector, "cache", TTLCache())

    async def bcb_falso(key):
        return _ok(f"bcb.{key}")

    async def ibge_falso():
        return _ok("ibge.ipca_hardware")

    chamadas: list[tuple[str, str, list[str]]] = []

    async def mensal_falso(cat_key, sh6, label, all_sh6):
        chamadas.append((cat_key, sh6, list(all_sh6)))
        return _ok(f"{PREFIX}.{cat_key}", sh6)

    monkeypatch.setattr(collector.bcb, "fetch_series", bcb_falso)
    monkeypatch.setattr(collector.ibge, "fetch_ipca_hardware", ibge_falso)
    monkeypatch.setattr(collector.comtrade, "fetch_monthly_imports", mensal_falso)

    collected = asyncio.run(collector.collect())

    mensais = sorted(k for k in collected if k.startswith(f"{PREFIX}."))
    assert mensais == sorted(f"{PREFIX}.{c.key}" for c in CATEGORIES)
    assert len(mensais) == 10
    assert all(collected[k].ok for k in mensais)
    assert collected[f"{PREFIX}.motherboard"] is collected[f"{PREFIX}.gpu"]
    assert len(chamadas) == 9
    todos_sh6 = sorted(c.sh6 for c in CATEGORIES)
    assert all(sorted(sh6s) == todos_sh6 for _, _, sh6s in chamadas)
    assert not [k for k in collected if k.startswith("comexstat.")]
