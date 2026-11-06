"""Progresso da coleta — testes offline, sem rede e sem subir o app."""

from __future__ import annotations

from app.services.progress import CollectionProgress


def test_progresso_avanca_por_consulta_e_fecha_em_100():
    p = CollectionProgress()
    p.start(4)

    first = p.snapshot()
    assert first["stage"] == "collecting"
    assert first["percent"] == 0
    assert first["total"] == 4

    p.step("a")
    assert p.snapshot()["percent"] == 25
    p.step("b")
    p.step("c")
    assert p.snapshot()["percent"] == 75
    assert p.snapshot()["completed"] == 3
    p.step("d")

    p.building()
    # Ainda falta montar/gravar; não finge 100% antes de a tela liberar.
    assert p.snapshot()["stage"] == "building"
    assert p.snapshot()["percent"] == 99

    p.ready()
    done = p.snapshot()
    assert done["stage"] == "ready"
    assert done["percent"] == 100
    assert done["completed"] == 4
    assert done["finished_at"] is not None


def test_progresso_de_erro_preserva_o_que_ja_foi_concluido():
    p = CollectionProgress()
    p.start(3)
    p.step("a")
    p.fail("RuntimeError: rede caiu")

    failed = p.snapshot()
    assert failed["stage"] == "error"
    assert failed["completed"] == 1
    assert failed["percent"] == 33
    assert "rede caiu" in failed["error"]
