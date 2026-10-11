# Projects MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Permitir criar, listar e consultar projetos próprios no frontend existente, com persistência no Neon e isolamento entre contas.

**Architecture:** Serviço independente `projects_service`, com API FastAPI, validação RS256 via JWKS do módulo de identidade e repositório SQLAlchemy restrito ao responsável. O MOD1-Frontend usa a sessão atual para consumir a nova API; cada serviço mantém seu próprio schema e credencial.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy 2, psycopg 3, PyJWT[crypto], uv; frontend HTML/CSS/JavaScript com Playwright e unittest.

**Spec:** [Desenho aprovado](../specs/2026-10-11-projects-mvp-design.md).

## Global Constraints

- Backend: `C:/Users/cauek/dev/projeto_eng_soft/.worktrees/projects-mvp`, branch `feat/projects-mvp`; frontend: `C:/Users/cauek/dev/MOD1-Frontend/.worktrees/auth-ui`, branch `feat/auth-ui`.
- Identidade existente: `C:/Users/cauek/.codex/worktrees/2ecd/MOD1-EngenhariaSoftware`. Não alterar seu contrato, schema, `.env` ou chave privada.
- Frontend já contém mudanças de cadastro/validação não commitadas. Preservar esse estado, registrar seu diff antes de editar e revisar separadamente os acréscimos de projetos.
- Python `>=3.12`; pacote `projects_service`; schema `projects`; tabela `projects.projects`; sem FK, join ou acesso às tabelas dos outros módulos.
- `name`: aparado, 1–120 caracteres; `description`: string opcional, padrão `""`, até 2000 caracteres, mantendo quebras de linha; campos extras recusados.
- `id` e `created_at` gerados no servidor; `owner_id` vem somente do `sub` validado. UUIDs, datas UTC, nomes repetidos permitidos.
- Listagem: `items,total,limit,offset`; padrão `limit=20,offset=0`, limite 1–100, offset não negativo; ordem `created_at DESC,id DESC`.
- `JWT_ISSUER=mod1-auth-local`, `JWT_AUDIENCE=engenharia-software-api`, `JWKS_URL=http://127.0.0.1:8000/.well-known/jwks.json`; RS256, claims `sub,iss,aud,iat,exp,jti` obrigatórias.
- API auth `8000`, projetos `8001`, frontend `5173`; `CORS_ORIGINS=["http://127.0.0.1:5173"]`; configuração pública nova `PROJECTS_API_BASE_URL`.
- Banco preparado por `projects-service init`, nunca no startup. Role runtime com USAGE no schema e SELECT/INSERT na tabela. Neon exige TLS verificando certificado e hostname.
- Erros: 401 identidade inválida; 404 projeto ausente/de outra conta; 422 entrada inválida; 503 banco/chaves necessárias indisponíveis. Projetos usam `Cache-Control: no-store`; erros não expõem segredos ou SQL.
- Interface segue os tokens, fontes, temas e regras existentes do módulo 6; credenciais/JWT permanecem fora do armazenamento persistente do navegador.
- Cada commit deste trabalho inclui `Co-authored-by: Brian Freire <briankfreire@outlook.com>`. Hook já configurado no clone de Brian; incluir trailer explicitamente nos commits do frontend.
- Testes destrutivos recusam Postgres remoto. Smoke Neon usa somente contas/projetos sintéticos, sem DROP/DELETE. Segredos e scripts operacionais ficam ignorados em `.env`/`.local/`.
- Escopo: criar/listar/consultar; sem equipes, convites, papéis, edição, exclusão, backlog ou deploy. JWT previamente emitido pode continuar válido até expirar após desativação no emissor.

## Review Focus

1. JWKS indisponível após cache: aceitar chave confiável dentro dos 300 segundos de cache; sem chave utilizável, 503 sem permitir operação (tarefa 2).
2. Projetos com a mesma data e nomes Unicode: paginação estável por UUID, limites em caracteres Unicode consistentes entre API e formulário (tarefas 1 e 3).
3. Falha de INSERT: rollback e 503 sem SQL/DSN; requisição seguinte utiliza sessão limpa (tarefa 2).
4. Logout de A seguido de login de B enquanto chega uma resposta antiga: abortar/ignorar resultado e apagar dados de A (tarefa 3).
5. Nome/descrição contendo HTML e quebras de linha: mostrar texto literal sem execução e preservar a descrição (tarefa 3).

---

## Mapa de arquivos e responsabilidades

Paths abaixo são relativos ao backend; prefixo `frontend/` significa o worktree MOD1-Frontend acima.

| Arquivos | Responsabilidade |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.env.example`, `README.md` | Empacotamento, dependências reproduzíveis, configuração pública e execução |
| `src/projects_service/__init__.py`, `config.py`, `domain.py` | Configuração validada, entradas e objetos de projeto/página |
| `src/projects_service/database.py`, `models.py`, `repository.py`, `service.py`, `cli.py` | Schema, transações, consultas com owner e casos de uso/CLI administrativa |
| `src/projects_service/security.py`, `routes.py`, `app.py` | Verificador JWKS, rotas autenticadas, saúde, erros e CORS |
| `tests/conftest.py`, `test_projects.py`, `test_config_cli.py`, `test_security.py`, `test_api.py`, `test_postgres.py` | Fixtures sintéticas e provas de domínio, segurança, API e Postgres local opt-in |
| `frontend/public/scripts/projects-api.js`, `projects.js` | Cliente específico da API e controlador das telas de projetos |
| `frontend/public/config.js`, `public/index.html`, `public/scripts/app.js`, `public/styles/app.css` | URL pública, telas, integração com sessão e estilos existentes |
| `frontend/tests/browser_support.py`, `test_projects_api.py`, `test_projects_ui.py`, `test_projects_real_api.py` | Configuração dinâmica, comportamento do cliente/UI e integração entre serviços reais |
| `docs/verification.md`, `frontend/docs/verification.md`, `frontend/docs/screenshots/projects-*.png` | Evidências e roteiro de demonstração reproduzível |

### Task 1: Persistência de projetos e preparação explícita do banco

**Files:** criar empacotamento/configuração, domínio, banco, modelo, repositório, serviço e CLI do mapa; criar `tests/conftest.py`, `test_projects.py`, `test_config_cli.py`, `test_postgres.py`; atualizar `README.md`; remover os placeholders `main.py`/`teste.py` apenas na branch.

**Interfaces:**
- Produz `Settings` (Pydantic Settings): `database_url` oculto em repr/erros; `database_schema="projects"`, `jwt_issuer`, `jwt_audience`, `jwks_url`, `cors_origins`, com defaults acima e carregamento `.env`.
- Produz modelos Pydantic: `ProjectDraft(name: str, description: str = "")`, extras proibidos; `Project(id: UUID, owner_id: UUID, name: str, description: str, created_at: datetime)`; `ProjectPage(items: list[Project], total: int, limit: int, offset: int)`.
- Produz `create_database_engine(settings: Settings) -> Engine` e `init_schema(engine: Engine, schema: str) -> None`. SQLite só é usado em testes isolados, com tradução de schema; Postgres usa psycopg.
- Produz `ProjectRepository(session: Session)` com `add(project: Project) -> Project`, `list_owned(owner_id: UUID, *, limit: int, offset: int) -> ProjectPage`, `get_owned(owner_id: UUID, project_id: UUID) -> Project | None`.
- Produz `utc_now() -> datetime` em `service.py` e `ProjectsService(repository: ProjectRepository, *, clock: Callable[[], datetime] = utc_now, id_factory: Callable[[], UUID] = uuid4)` com `create(owner_id: UUID, draft: ProjectDraft) -> Project`, `list(owner_id: UUID, *, limit: int = 20, offset: int = 0) -> ProjectPage`, `get(owner_id: UUID, project_id: UUID) -> Project | None`.
- Produz CLI `main(argv: Sequence[str] | None = None) -> int`, entry point `projects-service`; `init` usa credencial administrativa fornecida explicitamente na configuração daquela execução.

- [x] Escrever `pyproject.toml` mínimo com src layout, hatchling e grupo dev pytest/httpx/ruff/mypy; dependências FastAPI, uvicorn, SQLAlchemy, psycopg[binary], PyJWT[crypto], Pydantic Settings e certifi para o bundle TLS. Usar as faixas compatíveis já existentes na API de identidade para dependências compartilhadas, sem dependência do pacote de autenticação.
- [x] Escrever testes de domínio/repositório: `test_create_assigns_owner_uuid_and_utc_time` afirma `p.owner_id == owner_a`, `p.name == "Projeto"`, UUID novo e UTC; `test_defaults_and_repeated_names` afirma `description == ""` e ids distintos.
- [x] Escrever `test_draft_limits_and_extra_fields` parametrizado: `"   "`, `"😀"*121`, descrição com 2001 caracteres, `owner_id` e tipos não string falham; `"😀"*120` e descrição com 2000 passam; `"linha 1\nlinha 2"` é preservada.
- [x] Escrever `test_owner_isolation_and_stable_pagination`: com datas iguais, `page.total == 3`, páginas de 2/1 itens não se sobrepõem e ids estão decrescentes; `service.get(owner_b, project_a.id) is None`. `test_invalid_pagination` recusa limites 0/101 e offset -1.
- [x] Escrever `test_persists_after_engine_recreation` usando SQLite em arquivo: reconstruir engine/repositório e afirmar `reloaded.id == original.id`. `test_init_is_explicit_and_idempotent` verifica tabela inexistente antes da CLI e dados preservados no segundo init.
- [x] Escrever testes de configuração: `test_rejects_unsafe_config_without_echoing_secrets` recusa schema inválido e JWKS HTTP remoto/URL com credenciais; erros não contêm senha/DSN. `test_postgres_guard_rejects_remote` recusa host fora de localhost/127.0.0.1/::1 antes de executar qualquer DDL de teste.
- [x] Escrever `test_local_postgres_persistence_and_owner_queries` opt-in: criar schema temporário exclusivo em Postgres local, salvar projetos A/B, reconstruir engine, afirmar `page_a.total == 1`, `page_a.items[0].id == project_a.id` e `get_owned(owner_b, project_a.id) is None`; remover somente esse schema temporário no teardown, após a guarda local.
- [x] Executar `uv run pytest tests/test_projects.py tests/test_config_cli.py tests/test_postgres.py -q`; esperado: falha por pacote/interface ainda ausente, não por ferramenta indisponível. Postgres opt-in requer `TEST_DATABASE_URL` local e namespace temporário exclusivo.
- [x] Implementar config/domínio com os contratos acima; validar JWKS configurado e schema; Postgres remoto requer `sslmode=verify-full` e raiz confiável, mantendo SQLite/Postgres loopback para testes; não coagir tipos de entrada, aparar apenas nome; documentar `.env.example` sem credenciais reais.
- [x] Implementar engine/modelo/repositório/serviço; índice owner/data/id, consultas sempre com owner, contagem do mesmo owner; transações da criação fazem commit/rollback. SQLite devolve datas como UTC normalizado.
- [x] Implementar CLI explícita com schema/tabela idempotentes e saída segura; atualizar README com `uv sync`, init administrativo e execução futura da API; retirar scripts placeholder da branch.
- [x] Executar os testes da tarefa e `uv run ruff check src tests`; esperado: PASS, com skip apenas de Postgres opt-in sem URL local. Corrigir falhas antes do commit.
- [x] Commitar somente arquivos da tarefa: `feat: add owner-scoped project persistence`; verificar trailer do Brian com `git log -1 --format=%B`.

### Task 2: API com autenticação independente e autorização por responsável

**Files:** criar `security.py`, `routes.py`, `app.py`, `tests/test_security.py`, `tests/test_api.py`; ampliar fixtures, README e testes Postgres da tarefa 1.

**Interfaces:**
- Consome `Settings`, `ProjectDraft`, `Project`, `ProjectPage`, `ProjectsService`, `ProjectRepository` e `create_database_engine` da tarefa 1.
- Produz `TokenVerifier(settings: Settings)` com `verify(token: str) -> UUID`; exceções `AuthenticationRejected` e `SigningKeysUnavailable`.
- Produz `create_app(settings: Settings | None = None, *, verifier: TokenVerifier | None = None) -> FastAPI`; factory para `uv run uvicorn projects_service.app:create_app --factory --host 127.0.0.1 --port 8001`.
- Contrato público: POST `/projects` -> 201 `Project`; GET `/projects` -> 200 `ProjectPage`; GET `/projects/{project_id}` -> 200 `Project` ou 404; saúde 200/503 conforme spec.

- [x] Escrever fixtures com RSA/JWKS sintéticos servidos em HTTP loopback; tokens para dois UUIDs e issuer/audience aprovados; nenhuma importação do emissor nem chave real.
- [x] Escrever `test_verifier_claims_and_signature`: token válido devolve UUID de `sub`; assinatura errada, HS256/none, issuer/audience errados, expirado além da tolerância, iat futuro, UUIDs inválidos, claims ausentes e exp/iat boolean/string são recusados. Headers com `jku` externo nunca causam busca naquele endereço.
- [x] Escrever `test_jwks_outage_cache_and_rotation`: timeout sem cache gera `SigningKeysUnavailable`; cache válido continua aceitando chave conhecida; após TTL/outage falha; kid desconhecido após atualização válida gera `AuthenticationRejected`; rotação confiável permite nova chave. JWKS remoto malformado/sem chaves utilizáveis gera indisponibilidade segura.
- [x] Escrever `test_http_create_list_and_private_detail`: POST válido retorna 201 e os cinco campos com owner do Bearer; listagem usa 20/0 por padrão; A lê A; B recebe 404 para id conhecido de A e id ausente, e total próprio; validar limites/extras -> 422, token ausente/inválido -> 401.
- [x] Escrever `test_no_store_and_safe_errors`: respostas de sucesso/falha em `/projects` possuem `Cache-Control == "no-store"`; 401 possui challenge Bearer; validação e erros não ecoam JWT, DSN ou SQL. `test_cors` permite somente origem configurada.
- [x] Escrever `test_health_and_database_failure_recovery`: live continua 200 com banco/JWKS indisponíveis; ready verifica tabela -> 200/503; INSERT que falha -> 503 sem detalhes; próximo POST com nova sessão -> 201. `test_startup_does_not_execute_ddl` comprova ausência de CREATE e startup com tabela ainda ausente.
- [x] Executar `uv run pytest tests/test_security.py tests/test_api.py -q`; esperado: falhas por verificador/factory ausentes.
- [x] Implementar `TokenVerifier.verify`: RS256 somente, `typ=JWT`, kid não vazio; PyJWT exige claims, issuer/audience escalares exatos, leeway de 5 segundos, inteiros estritos exp/iat com exp>iat, UUID sub/jti; JWKS configurado com timeout 5 segundos e cache de conjunto 300 segundos, sem cache indefinido por chave.
- [x] Implementar classificação de falhas: token/header/assinatura rejeitados -> 401; conexão/timeout ou conjunto confiável inutilizável -> 503; kid não encontrado após conjunto válido atualizado -> 401. Nenhuma fonte de chave é aceita do JWT.
- [x] Implementar rotas síncronas com sessão por requisição e serviço da tarefa 1; health/live independente; health/ready consulta apenas tabela própria; handlers sanitizados de validação/SQL/chaves, no-store e CORS configurado; fechar engine no shutdown sem DDL.
- [x] Executar `uv run pytest -q`, `uv run ruff check src tests`, `uv run mypy src/projects_service` e `uv build`; esperado: PASS/build, com apenas skips opt-in documentados. Confirmar a instalação do entry point no pacote.
- [x] Commitar arquivos da tarefa: `feat: expose authenticated projects API`; conferir coautoria.

### Task 3: Criar e consultar projetos no frontend existente

**Files:** todos os arquivos frontend de produto do mapa; `frontend/tests/browser_support.py`, `test_projects_api.py`, `test_projects_ui.py`; atualizar README e PRODUCT do frontend apenas para descrever este fluxo.

**Interfaces:**
- Consome HTTP da tarefa 2; sessão existente `session.getToken() -> string | null`, `session.isActive() -> boolean` e `endSession(text, tone)` em `app.js`.
- Produz `createProjectsApiClient({baseUrl, fetchImpl=fetch, timeoutMs=10000})` com `create(token, {name,description}, {signal}={}) -> Promise<Project>`, `list(token, {limit=20,offset=0,signal}={}) -> Promise<ProjectPage>`, `get(token, projectId, {signal}={}) -> Promise<Project>`; UUID/datas são strings JSON. `ProjectsApiError.kind`: unauthorized, validation, not-found, unavailable, network, timeout, invalid-response, cancelled.
- Produz `createProjectsController({api, getToken, onUnauthorized, onBack}) -> {open(): Promise<void>, close(): void, clear(): void}`. Usa os IDs DOM abaixo; `onBack` restaura perfil, `onUnauthorized` chama `endSession`. `clear` aborta, invalida resultados, apaga formulário/lista/detalhe e oculta a tela.
- IDs novos: `open-projects`, `projects-view`, `projects-title`, `projects-list`, `projects-status`, `projects-previous`, `projects-next`, `project-form`, `project-name`, `project-description`, `project-submit`, `project-detail`, `projects-back`, `projects-logout`.

- [x] Escrever `test_projects_api_contract_and_error_mapping`: Bearer correto, POST só name/description, query 20/0, abort/timeout, resposta malformada recusada, códigos 401/404/422/503 com mensagens seguras; nenhuma resposta bruta de erro é mostrada.
- [x] Escrever `test_empty_create_and_detail`: login -> “Meus projetos” -> estado vazio -> preencher “Criar projeto” -> item e detalhe com nome/descrição/data; descrição omitida envia `""`; paginação próxima/anterior preserva contrato e volta à página inicial após criar.
- [x] Escrever `test_project_field_validation_and_keyboard`: vazio/espaços, nome Unicode 121 e descrição 2001 impedem POST, marcam aria-invalid e focam primeiro campo; 120/2000 passam; labels/mensagens acessíveis, navegação por teclado e foco no título ao trocar tela.
- [x] Escrever `test_single_submit_and_recoverable_failure`: clique duplo envia um POST, controles indicam carregamento; erro rede/503 permite recuperar sem repetir POST automaticamente; 401 encerra sessão. `test_project_text_is_inert` mostra `<img src=x onerror=alert(1)>` literal e mantém `linha 1\nlinha 2` sem criar elemento HTML.
- [x] Escrever `test_logout_then_other_login_ignores_late_project_response`: iniciar requisição A pendente, sair, entrar como B e entregar resposta A; dados de A nunca aparecem, formulário/detalhe estão limpos. Também ignorar resposta após voltar ao perfil.
- [x] Executar no frontend `uv run --no-project --with-requirements tests/requirements.txt python -m unittest discover -s tests -p "test_projects_*.py" -v`. Esperado: falha por módulo/telas ausentes.
- [x] Implementar cliente em `projects-api.js` com contrato acima, validador de shape, timeout/abort, sem redirects/credenciais de cookies/cache; nunca mostrar mensagem recebida do backend diretamente.
- [x] Implementar `projects.js`: renderizar com textContent e descrição com white-space pre-wrap; paginação de 20, estados vazio/carregando/falha, submissão única e mensagens de campo. Capturar token e geração de navegação por operação; aceitar resultado só se geração e token atual ainda forem os mesmos.
- [x] Integrar controlador em `app.js`: ação “Meus projetos” disponível após login; retorno ao perfil; logout e expiração chamam `clear()`; profile refresh não deixa tela de projetos sobreposta. Tratar configuração de projetos inválida com mensagem local sem impedir login.
- [x] Adicionar views/URL pública/estilos nos arquivos existentes; reutilizar validação e tokens do módulo 6. `browser_support.py` exporta ambas as URLs quando injeta config; manter formulários inertes até JS inicializar e não persistir tokens.
- [x] Executar suíte completa frontend com `AUTH_BACKEND_PATH` apontando ao worktree de identidade e o comando `uv run --no-project --with-requirements tests/requirements.txt python -m unittest discover -s tests -v`; esperado: regressões existentes e novos testes PASS. Revisar diff de projetos contra baseline preservada.
- [x] Commitar entrega frontend com mensagem `feat: add personal projects workspace` e trailer explícito do Brian. Arquivos compartilhados só são commitados após verificar também as mudanças existentes que precisam acompanhar a entrega; excluir screenshots/artefatos não relacionados.

### Task 4: Demonstração integrada e evidências com Neon

**Files:** criar `frontend/tests/test_projects_real_api.py`; ampliar `frontend/tests/browser_support.py` somente quando necessário para fixture real; atualizar READMEs/verification de ambos; screenshots `frontend/docs/screenshots/projects-desktop-light.png`, `projects-mobile-dark.png`, `projects-validation-mobile.png`. Operação real em `.local/` e `.env`, não versionada.

**Interfaces:**
- Consome factories/CLI/HTTP das tarefas 1–2 e telas da tarefa 3.
- Fixture usa `AUTH_BACKEND_PATH` e `PROJECTS_BACKEND_PATH`, processos em portas loopback efêmeras, banco SQLite temporário de cada serviço e RSA sintético do emissor. Não depende das APIs da demonstração nem do Neon.
- Entrega registro seguro de evidência: provider, status, ids sintéticos, contagens de testes; sem senha, JWT, DSN ou key material. Roteiro reproduzível de três serviços e link da versão específica do MVP quando a branch for publicada.

- [x] Escrever `test_register_login_create_restart_and_second_account_denied`: cadastrar A pela API real, entrar pelo navegador, criar/ler projeto, reiniciar processo de projetos com mesmo arquivo, relogar e encontrar item; cadastrar/entrar B, verificar lista sem item e GET direto A -> 404; auth ausente -> 401.
- [x] Executar a nova suíte integrada com as duas variáveis acima; esperado antes da fixture completa: falha por setup/processo não implementado. Se já passa com serviços das tarefas anteriores, registrar o PASS como verificação de integração, sem inventar falha.
- [x] Implementar fixture real com teardown de processos/arquivos temporários próprios; init explicitamente antes do runtime; não alterar `.env`/portas dos serviços em uso.
- [x] Executar suítes backend e frontend completas, lint, mypy e build dos comandos anteriores; esperado: PASS com skips opt-in justificados; integração não deve pular quando ambos os paths estão configurados.
- [x] Provisionar Neon por conexão administrativa existente, lida sem imprimir: init schema `projects`; criar role runtime dedicada `mod1_projects_runtime` com senha gerada localmente e somente grants previstos. Gerar `.env` ignorado com DSN runtime/TLS verify-full e bundle confiável, sem modificar credencial/schema de identidade.
- [x] Verificar privilégios por metadados: schema projects USAGE, tabela SELECT/INSERT; sem CREATE, UPDATE, DELETE e sem acesso a schema/tabelas de identidade. Runtime executa readiness/criação/listagem e startup não exige credencial administrativa.
- [x] Executar smoke não destrutivo com contas sintéticas A/B na stack local/Neon: cadastro, login, POST 201, listagem, detalhe; B -> 404; sem token -> 401; reiniciar somente a API de projetos e confirmar persistência. Reutilizar ids registrados em `.local/` para inspeção, sem limpar dados remotos.
- [x] Inspecionar desktop 1440/light e mobile 390/dark num único lote: lista/detalhe/validação, teclado, foco, mensagens e ausência de overflow. Corrigir problemas juntos e fazer no máximo uma rodada visual de confirmação; salvar screenshots sintéticos aprovados.
- [x] Atualizar READMEs e verification com comandos PowerShell, variáveis públicas, limitações JWT/equipes, roteiro de 2–3 minutos e resultados reais; distinguir testes isolados, skips Postgres local e smoke Neon.
- [x] Solicitar revisão final conforme `superpowers:requesting-code-review` usando o método escolhido pelo usuário; corrigir achados materiais e repetir apenas os checks afetados. Não declarar conclusão com achado material pendente.
- [x] Commitar evidências de cada repositório separadamente com coautoria do Brian e escopo revisado; verificar `git diff --check`, status e trailers. Não mesclar/reescrever main. Se publicação estiver disponível/autorizada, publicar branch e preparar PR draft; caso contrário, fornecer commits locais e informar a limitação concreta.

## Auto-revisão do plano

- Cobertura: modelo/persistência/CLI (1), JWT/HTTP/erros/saúde (2), fluxo/visual/sessão (3), Neon/isolamento/persistência/demonstração (4).
- Interfaces: nomes de campos/retornos são os mesmos no domínio, HTTP e cliente; apenas UUID/datetime passam a strings no JSON. `clear()` integra logout/expiração e `close()` invalida navegação.
- Cinco focos de revisão têm testes explícitos nas tarefas indicadas. Nenhuma etapa pede alteração do emissor ou operação destrutiva remota.
- Execução nativa aprovada e concluída, seguida de revisão independente final e correção dos achados materiais. Evidências em docs/verification.md. Publicação de branches/PRs e revisão por Brian aprovadas pelo usuário; merge permanece sujeito à revisão.
