"""Providers de dados públicos.

Cada módulo expõe corrotinas que devolvem `Fetched` — nunca levantam para o
chamador, pois o `TTLCache` já converte falha em `stale`/`unavailable`.
"""
