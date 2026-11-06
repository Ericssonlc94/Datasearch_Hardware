"""Federal Register (BIS) — testes offline, sem rede.

Cobre a leitura do sentido no título (aperto +1, revisão +0,5, alívio −1),
o filtro de relevância (só chips, China e Entity List), a soma diária com 0
em dia sem regra e a coleta com `get_json` substituído por dado local.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import fedreg  # noqa: E402


@pytest.mark.parametrize(
    "title",
    [
        "Additions to the Entity List",
        "Revocation of License Exception for Advanced Computing Items",
        "Implementation of Additional Export Controls: Certain Advanced Computing "
        "Items; Supercomputer and Semiconductor End Use; New Controls on China",
        "Additions to and Removal From the Entity List",  # aperto prevalece
    ],
)
def test_aperto_vale_mais_um(title):
    assert fedreg.rule_direction(title) == 1.0


@pytest.mark.parametrize(
    "title",
    [
        "Entity List: Revisions of Entries",
        "Entity List; Corrections to Existing Entries",
    ],
)
def test_revisao_da_entity_list_vale_meio(title):
    assert fedreg.rule_direction(title) == 0.5


@pytest.mark.parametrize(
    "title",
    [
        "Removal of Entity From the Entity List",
        "Extension of Validated End-User Authorization for Semiconductor Fabs in China",
        "Suspension of Certain Advanced Computing License Requirements",
    ],
)
def test_alivio_vale_menos_um(title):
    assert fedreg.rule_direction(title) == -1.0


def test_alivio_no_plural_removals():
    assert fedreg.rule_direction("Removals of Certain Entities From the Entity List") == -1.0


@pytest.mark.parametrize(
    "title",
    ["Firearms and Ammunition Export Rule", "Russia: Aircraft Parts Controls", "", None],
)
def test_regra_fora_do_tema_fica_de_fora(title):
    assert fedreg.rule_direction(title) is None


def test_serie_diaria_soma_regras_e_zera_dia_vazio():
    rules = [
        {"date": "2026-10-01", "direction": 1.0},
        {"date": "2026-10-01", "direction": 0.5},
        {"date": "2026-10-03", "direction": -1.0},
        {"date": "2026-09-01", "direction": 1.0},  # fora da janela
    ]
    pts = fedreg.daily_net_series(rules, date(2026, 10, 1), date(2026, 10, 4))
    assert pts == [
        ("2026-10-01", 1.5),
        ("2026-10-02", 0.0),
        ("2026-10-03", -1.0),
        ("2026-10-04", 0.0),
    ]


def test_coleta_filtra_classifica_e_conta(monkeypatch):
    today = datetime.now(timezone.utc).date()
    d1 = (today - timedelta(days=2)).isoformat()
    d2 = (today - timedelta(days=1)).isoformat()
    seen: dict = {}

    async def fake_get_json(url, **kw):
        seen["url"], seen["params"] = url, kw.get("params")
        return {
            "results": [
                {"title": "Additions to the Entity List", "publication_date": d1,
                 "html_url": "https://fr/1"},
                {"title": "Removal of Entity From the Entity List", "publication_date": d2,
                 "html_url": "https://fr/2"},
                {"title": "Firearms Export Rule", "publication_date": d2,
                 "html_url": "https://fr/3"},
                {"title": "Additions to the Entity List", "publication_date": "",
                 "html_url": "https://fr/4"},  # sem data: descartada
            ]
        }

    monkeypatch.setattr(fedreg, "get_json", fake_get_json)
    fetched = asyncio.run(fedreg.fetch_bis_chip_rules())

    assert seen["url"] == fedreg.BASE
    assert seen["params"]["conditions[agencies][]"] == fedreg.AGENCY
    assert seen["params"]["conditions[type][]"] == "RULE"
    assert fetched.status == "ok"
    assert [r["direction"] for r in fetched.payload["rules"]] == [1.0, -1.0]
    by_day = dict(fetched.payload["points"])
    assert by_day[d1] == 1.0 and by_day[d2] == -1.0
    assert len(fetched.payload["points"]) == fedreg.HISTORY_DAYS + 1
    assert "2 regra(s) relevante(s)" in fetched.note
    assert "1 de aperto ou revisão, 1 de alívio" in fetched.note


def test_coleta_sem_results_falha_visivel(monkeypatch):
    async def fake_get_json(url, **kw):
        return {"errors": ["bad request"]}

    monkeypatch.setattr(fedreg, "get_json", fake_get_json)
    with pytest.raises(ValueError, match="results"):
        asyncio.run(fedreg.fetch_bis_chip_rules())
