# Projetos — MVP do Brian

Serviço independente para criar, listar e consultar projetos do usuário autenticado.
Autenticação é fornecida pelo módulo de Caue, e o backlog futuro pertence ao de Igor.

Python 3.12 ou superior e uv. Copie `.env.example` para `.env` e configure o PostgreSQL
com schema `projects`, conexão TLS verify-full e credencial runtime própria.

```powershell
uv sync --python 3.12 --no-install-project
uv sync --no-build-isolation
# Use uma conexão administrativa somente nesta execução explícita:
uv run --no-build-isolation projects-service init
# Depois use a conexão runtime limitada a USAGE no schema e SELECT/INSERT na tabela.
```

O startup da API não prepara o banco. Schema e credencial de identidade permanecem separados.
SQLite é usado apenas pela suíte isolada; não é necessário para a demonstração no Neon.

```powershell
uv run --no-build-isolation pytest -q
uv run --no-build-isolation ruff check src tests
```

Integração PostgreSQL descartável é opt-in via `TEST_DATABASE_URL` e recusa hosts remotos.
Os testes não precisam de conta real ou da chave privada de autenticação.

Neste Windows, a política de execução bloqueia ambientes Python temporários no cache.
O bootstrap acima mantém o build no ambiente local do projeto, com suas dependências
de build instaladas; não altera a política do sistema.

Desenho e plano aprovados estão em `docs/superpowers/`. Cada commit deste trabalho
inclui Brian Freire (`briankfreire@outlook.com`) como coautor.

