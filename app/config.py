"""Configuração central da aplicação."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="DSH_", extra="ignore"
    )

    app_name: str = "DataSearch Hardware"
    host: str = "127.0.0.1"
    port: int = 8000

    # Ciclo de atualização exigido: 15 minutos.
    refresh_seconds: int = 15 * 60

    # Aquece o cache no startup e mantém um loop de refresh em background.
    autorefresh: bool = True

    # Timeout e retentativas por requisição HTTP externa.
    http_timeout: float = 20.0
    http_retries: int = 2
    user_agent: str = (
        "datasearch-hardware/1.0 (+pesquisa de precos de hardware; contato: local)"
    )

    # TTLs por classe de fonte, em segundos. Séries mensais não mudam a cada 15 min,
    # então não faz sentido bater nelas nesse ritmo.
    ttl_realtime: int = 15 * 60  # câmbio, bolsa, notícias
    ttl_daily: int = 6 * 60 * 60  # PTAX, séries diárias FRED
    ttl_monthly: int = 24 * 60 * 60  # IPCA, Comex Stat, IMF, Comtrade

    # Sources opcionais que podem ser desligadas se a rede local bloquear.
    enable_markets: bool = True
    enable_gdelt: bool = True
    enable_comtrade: bool = True
    enable_comexstat: bool = True
    enable_fred: bool = True


settings = Settings()
