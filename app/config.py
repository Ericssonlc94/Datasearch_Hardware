"""Configuração central da aplicação."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Contato que vai no User-Agent: e-mail ou URL http(s), sem espaço nem
# caractere de controle (um CR/LF aqui viraria injeção de header).
_CONTACT_RE = re.compile(r"(?:[^@\s]+@[^@\s]+\.[^@\s]+|https?://[^\s]+)")
_CONTACT_MAX = 200
_DEFAULT_UA = "datasearch-hardware/1.0 (+pesquisa de precos de hardware; contato: {contact})"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="DSH_", extra="ignore"
    )

    app_name: str = "DataSearch Hardware"
    host: str = "127.0.0.1"
    port: int = 8000

    # Ciclo de atualização exigido: 15 minutos.
    refresh_seconds: int = 15 * 60
    # Intervalo mínimo entre coletas forçadas por POST /api/refresh. Cada uma
    # ignora o cache e bate em todas as fontes; em excesso, as fontes passam a
    # tratar o IP do usuário como abusivo.
    refresh_min_interval_seconds: int = 60

    # Valores aceitos no header `Host` (contra DNS rebinding), separados por
    # vírgula. O `host` acima entra sozinho quando não é um curinga.
    allowed_hosts: str = "127.0.0.1,localhost"

    # Aquece o cache no startup e mantém um loop de refresh em background.
    autorefresh: bool = True

    # Timeout e retentativas por requisição HTTP externa.
    http_timeout: float = 20.0
    http_retries: int = 2
    # Contato real do responsável (e-mail ou URL do repositório), definido pelo
    # usuário. Vai no User-Agent; sem ele, nenhuma fonte de loja liga (K7).
    contact: str = ""
    user_agent: str = _DEFAULT_UA.format(contact="local")

    # TTLs por classe de fonte, em segundos. Séries mensais não mudam a cada 15 min,
    # então não faz sentido bater nelas nesse ritmo.
    ttl_realtime: int = 15 * 60  # câmbio, bolsa, notícias
    ttl_daily: int = 6 * 60 * 60  # PTAX, séries diárias FRED
    ttl_monthly: int = 24 * 60 * 60  # IPCA, Comex Stat, IMF, Comtrade
    # Manchetes mudam menos que preço; 30 min poupa dezenas de feeds sem
    # esconder notícia por muito tempo.
    ttl_news: int = 30 * 60

    # Sources opcionais que podem ser desligadas se a rede local bloquear.
    enable_markets: bool = True
    # Notícias por RSS público de veículos identificados, sem chave.
    enable_news_rss: bool = True
    # Terremotos perto dos polos de fabricação de chips (USGS, sem chave).
    enable_usgs: bool = True
    # Regras de exportação de chips do BIS no Federal Register (sem chave).
    enable_fedreg: bool = True
    enable_comtrade: bool = True
    # Importação mensal por SH6 via UN Comtrade: substituto do Comex Stat
    # (mesmo dado da SECEX, reportado pelo Brasil). Ver docs/agentes/dados.md.
    enable_comtrade_monthly: bool = True
    # Comex Stat responde 429 atrás de WAF nesta rede e exigia `Origin`/
    # `Referer` forjados — removidos. Desligado por padrão até validação em
    # rede sem WAF. Ver docs/fontes.md.
    enable_comexstat: bool = False
    enable_fred: bool = True
    # Camada "fila do consumidor": SEC EDGAR XBRL, sem chave.
    enable_sec: bool = True
    # Receita mensal da TSMC (frente "demanda" da oferta, T24c; sem chave).
    enable_tsmc: bool = True
    # Camada tarifária (fase 3, ainda sem provider implementado).
    enable_tariffs: bool = False
    # Preço na KaBuM (T24g/T26). DSH_CONTACT é opcional.
    enable_kabum: bool = False

    # Histórico: SQLite com uma linha por (timestamp, métrica).
    history_path: str = "data/history.db"
    # Cache das fontes em SQLite: fechar e abrir o app reaproveita o que ainda
    # está no prazo em vez de bater de novo em todas as fontes.
    cache_path: str = "data/cache.db"
    # 30 dias em alta frequência + 2 anos em base diária (ver seção de retenção).
    history_retention_days: int = 30
    history_daily_retention_days: int = 730

    @property
    def cache_file(self) -> Path:
        """`cache_path` relativo à raiz do projeto, como o `history_path`."""
        return _resolve(self.cache_path)

    @property
    def history_file(self) -> Path:
        return _resolve(self.history_path)

    @property
    def kabum_enabled(self) -> bool:
        """Contato no User-Agent é opcional (decisão do usuário, 05/11)."""
        return self.enable_kabum

    @model_validator(mode="after")
    def _contact_in_user_agent(self) -> "Settings":
        self.contact = self.contact.strip()
        if not self.contact:
            return self
        if len(self.contact) > _CONTACT_MAX or not _CONTACT_RE.fullmatch(self.contact):
            raise ValueError(
                "DSH_CONTACT precisa ser um e-mail ou uma URL http(s), sem espaços "
                f"e com até {_CONTACT_MAX} caracteres"
            )
        # Só troca o UA padrão; um DSH_USER_AGENT escrito à mão fica como está.
        if self.user_agent == _DEFAULT_UA.format(contact="local"):
            self.user_agent = _DEFAULT_UA.format(contact=self.contact)
        return self

    @model_validator(mode="after")
    def _cache_path_is_own_db(self) -> "Settings":
        """Recusa um `cache_path` que aponte para outro arquivo do projeto.

        O cache move para `.corrompido-*` o banco que não consegue ler; apontado
        por engano para o histórico ou para o `.env`, ele os tiraria do lugar.
        Falha na inicialização em vez de voltar ao padrão: o operador vê o erro
        na hora, e o padrão também poderia colidir com um `history_path` mudado.
        """
        cache_file = self.cache_file.resolve()
        if cache_file.suffix.lower() != ".db":
            raise ValueError(
                f"DSH_CACHE_PATH precisa terminar em .db (recebido: {self.cache_path!r})"
            )
        if cache_file == self.history_file.resolve():
            raise ValueError(
                "DSH_CACHE_PATH não pode ser o mesmo arquivo de DSH_HISTORY_PATH "
                f"({cache_file})"
            )
        return self

    @property
    def allowed_host_list(self) -> list[str]:
        hosts = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        if self.host not in ("0.0.0.0", "::", "") and self.host not in hosts:
            hosts.append(self.host)
        return hosts


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


settings = Settings()
