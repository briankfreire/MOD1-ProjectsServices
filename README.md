# ProjectServices

## Colaboração — candidato 0.4.0

Papéis fixos PO, PM/Scrum Master e Desenvolvedor, múltiplos papéis por pessoa,
expiração de vínculo e convites por código vinculados ao UUID destinatário.
Lista/detalhe incluem projetos acessíveis e permissões do chamador; exclusão
permanece exclusiva do proprietário. [Contrato, matriz e migração](docs/collaboration.md).
Não há equipes independentes nem papéis personalizados nesta versão.

Versão candidata SemVer: `0.4.0`, definida em `pyproject.toml` e refletida no OpenAPI.
Mudanças registradas em [CHANGELOG.md](CHANGELOG.md).

Serviço independente para criar, listar, buscar, consultar, editar e excluir projetos do usuário autenticado.
Autenticação é fornecida pelo módulo de Caue, e o backlog pertence ao de Igor.

Python 3.12 ou superior e uv. Copie `.env.example` para `.env` e configure o PostgreSQL
com schema `projects`, conexão TLS verify-full e credencial runtime própria.

```powershell
uv sync --locked --python 3.12 --no-install-project
uv sync --locked --no-build-isolation
# Use uma conexão administrativa somente nesta execução explícita:
uv run --no-build-isolation python -m projects_service.cli init
# Depois use a conexão runtime limitada a USAGE no schema e SELECT/INSERT/UPDATE/DELETE na tabela.
```

O startup da API não prepara o banco. Schema e credencial de identidade permanecem separados.
Instalações anteriores precisam executar explicitamente a migração aditiva de `objective`
e criar members/invitations com `migrate`; conferir os grants próprios em
[collaboration.md](docs/collaboration.md), preservando UPDATE/DELETE em projects.projects.
Consulte [database-neon.md](docs/database-neon.md). `init` não migra tabelas existentes.
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
| `POST /projects` | Nome/descrição/objetivo; 201 com id, owner_id, name, description, objective, created_at, permissions |
| `GET /projects?q=&limit=20&offset=0` | Busca literal no nome; items, total, limit, offset dos projetos acessíveis |
| `GET /projects/{id}` | Detalhe acessível; sem vínculo e id ausente retornam 404 |
| `PATCH /projects/{id}` | Edição parcial de name, description e objective com project:update; 200 Project |
| `DELETE /projects/{project_id}` | Exclui projeto próprio; 204 sem corpo, ausente/alheio retorna 404 |
| `GET /health/live` | Aplicação viva, independente do banco/JWKS |
| `GET /health/ready` | Acesso à tabela própria; 200 ou 503 |

Projetos exigem Bearer e usam no-store. Entradas inválidas retornam 422;
identidade inválida, 401; banco/chaves necessárias indisponíveis, 503.
Nome aparado de 1–120 caracteres; descrição e objetivo opcionais até 2000, default vazio.
PATCH exige ao menos um campo editável, sem null/extras; id, owner e data são imutáveis.
Busca `q` aparada até 120 caracteres, sem distinção de caixa, com `%`/`_` literais;
filtro e acesso são aplicados antes de total/paginação.
Desativar conta bloqueia login no emissor, mas JWT emitido pode valer até expirar.
Logout limpa a sessão do navegador. Este recorte não inclui equipes ou revogação.

## Exclusão e integração com outros módulos

O DELETE usa o mesmo Bearer, com proprietário derivado do JWT. Remove somente o
projeto: histórias são preservadas no Backlog e operações posteriores nesse projeto
retornam 404. Vínculos do GitHub Sync são responsabilidade do Módulo 2; repositórios,
issues e PRs no GitHub não são apagados. Membros/convites próprios são removidos por FK; não há cascata entre serviços nem restauração pela API.

Contrato completo, erros, confirmação e reconciliação após timeout:
[integration.md](docs/integration.md). O frontend deste repositório é separado;
a confirmação solicitada será implementada pelo Módulo 2 no GitHub Sync.

Regressão integrada opcional, com checkout do Backlog disponível:

```powershell
$env:BACKLOG_SERVICE_PATH = 'C:\CAMINHO\MOD1-BacklogService'
.venv/Scripts/python.exe -m pytest tests/test_backlog_integration.py -q
```

O teste usa HTTP local, JWT/chaves sintéticos e SQLite temporário, sem Neon.

