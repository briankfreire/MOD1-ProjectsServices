# ProjectServices

Versão candidata SemVer: `0.1.0`, definida em `pyproject.toml`.
Mudanças registradas em [CHANGELOG.md](CHANGELOG.md).

Serviço independente para criar, listar e consultar projetos do usuário autenticado.
Autenticação é fornecida pelo módulo de Caue, e o backlog futuro pertence ao de Igor.

Python 3.12 ou superior e uv. Copie `.env.example` para `.env` e configure o PostgreSQL
com schema `projects`, conexão TLS verify-full e credencial runtime própria.

```powershell
uv sync --python 3.12 --no-install-project
uv sync --no-build-isolation
# Use uma conexão administrativa somente nesta execução explícita:
uv run --no-build-isolation python -m projects_service.cli init
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

Cada commit deste trabalho
inclui Brian Freire (`briankfreire@outlook.com`) como coautor.

## API local

Para Docker e publicação no Azure Container Apps com Neon, consulte [deploy-azure.md](docs/deploy-azure.md). O workflow manual publica imagem por digest e pode atualizar uma API previamente provisionada.

```powershell
uv run --no-build-isolation python -m uvicorn projects_service.app:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log
```

Identidade em `http://127.0.0.1:8000` publica o JWKS. A API de projetos recebe
somente a chave pública por essa URL confiável, valida RS256, issuer/audience,
datas e UUIDs e aplica o responsável a cada consulta no servidor.

| Rota | Resultado |
| --- | --- |
| `POST /projects` | Nome/descrição; 201 com id, owner_id, name, description, created_at |
| `GET /projects?limit=20&offset=0` | items, total, limit, offset dos próprios projetos |
| `GET /projects/{id}` | Detalhe próprio; outro responsável e id ausente retornam 404 |
| `GET /health/live` | Aplicação viva, independente do banco/JWKS |
| `GET /health/ready` | Acesso à tabela própria; 200 ou 503 |

Projetos exigem Bearer e usam no-store. Entradas inválidas retornam 422;
identidade inválida, 401; banco/chaves necessárias indisponíveis, 503.
Nome aparado de 1–120 caracteres; descrição opcional até 2000; extras proibidos.
Desativar conta bloqueia login no emissor, mas JWT emitido pode valer até expirar.
Logout limpa a sessão do navegador. Este recorte não inclui equipes ou revogação.

