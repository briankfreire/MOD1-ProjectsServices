# ProjectServices

Versão `0.6.0` publicada em produção em 15/11/2026, integrada a Identidade
0.5.0 e Backlog 0.5.0. [Registro da entrega e validações](docs/final-delivery.md).

Projetos com escopo, orçamento, datas, requisitos e ciclo de vida; papéis
personalizados, equipes, concessões com expiração, alocações e recomendações com
aprovação humana. Aprovar equipes entrega notificações internas por destinatário,
com leitura privada idempotente. Gemini real está configurado em produção com
`gemini-3.5-flash-lite`; os cinco tipos de recomendação tiveram chamadas reais
validadas com dados sintéticos. A validação completa dos fluxos de IA continua
por cenário. Projetos não envia e-mail de aprovação de equipes; a entrega interna
e o [aviso externo ao Módulo 6](docs/module6-notifications.md) são independentes.

Contrato atual, limites, segurança, migração e notificações:
[docs/remaining-user-stories.md](docs/remaining-user-stories.md).

Contrato de exclusão para o GitHub Sync: [Módulo 2 — DELETE de projetos](docs/module2-project-deletion.md),
com respostas HTTP, impedimentos por backlog/vínculos e tratamento da interface.

A versão `0.7.0` acrescenta feed e busca de artigos dentro do projeto para
usuários com `project:read`. [Contrato e configuração da curadoria](docs/module5-curation.md).

## Executar localmente

Python 3.12 e uv. Configure `.env` a partir de `.env.example`, com schema e
credencial próprios de Projetos. Identidade publica JWKS e `/auth/me`; Backlog
fornece snapshots autorizados de conteúdo por API e consulta permissões em Projetos.

```powershell
uv sync --locked --no-build-isolation
# Banco novo, com credencial administrativa somente nesta operação:
uv run python -m projects_service.cli init
# Banco existente: atualização explícita e idempotente:
uv run python -m projects_service.cli migrate
uv run python -m uvicorn projects_service.app:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log
```

Startup não executa DDL. Runtime usa credencial limitada ao schema próprio.
AUTH_SESSION_CHECK_ENABLED=true é o padrão: desativação de conta e revogação de
sessão são verificadas na Identidade em cada requisição protegida, sem cache
positivo. Novos projetos começam planned; legados são migrados para active.

## Validar

```powershell
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv build --no-build-isolation
```

TEST_DATABASE_URL habilita PostgreSQL descartável loopback com schemas aleatórios;
os testes recusam bancos remotos. BACKLOG_SERVICE_PATH habilita a regressão HTTP
opcional com um checkout separado. Transportes controlados em testes não comprovam
integrações externas reais. Nunca apontar testes destrutivos para Neon ou produção.

## Documentação

- [Contrato HTTP e exclusão coordenada](docs/integration.md).
- [Papéis e colaboração](docs/collaboration.md).
- [Arquitetura e transações](docs/architecture.md).
- [Evidências e limites de validação](docs/verification.md).
- [Operação Azure](docs/deploy-azure.md) e [banco Neon](docs/database-neon.md).
- [Gemini real e limites](docs/gemini.md).
- [Entrega publicada em 15/11/2026](docs/final-delivery.md).

Frontend, Identidade e Backlog continuam em repositórios separados. Cada commit
deste trabalho inclui Brian Freire como coautor. Documentação de produto não
depende de instruções ou planos locais.

Integração ativa em produção: [notificações para o Módulo 6](docs/module6-notifications.md), com fila persistente e worker próprio, `source=backlog` e tipos `project.*`. Sem replay histórico ou avisos globais.
