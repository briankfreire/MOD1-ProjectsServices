# Contrato de exclusão para o Módulo 2 — 31/10/2026

O teste do OpenAPI reproduziu a falta do schema de erro antes da correção e
passou depois. Agora verifica Bearer, ausência de corpo na requisição e no
sucesso 204, além dos erros 401/403/404/409/422/503 com `detail` textual.

`python -m pytest tests/test_api.py tests/test_advanced.py tests/test_rbac.py -q --tb=short`:
**106 passaram e 1 foi pulado**, em 67,32 s. O caso pulado exige
`TEST_DATABASE_URL` em PostgreSQL loopback, não configurado nesta execução.
As fixtures usam SQLite temporário e chaves/serviços controlados; não houve
DELETE contra o banco persistente local ou qualquer banco remoto.
Ruff, formato dos dois arquivos Python alterados e mypy (24 módulos) passaram.

Após reiniciar somente o processo local de Projetos, a leitura de
`http://127.0.0.1:8001/openapi.json` confirmou o contrato corrigido. As três APIs
locais responderam readiness 200 e o frontend respondeu 200. Os dados de Projetos
foram preservados com backup. Publicação, disponibilidade externa e a integração
do GitHub Sync não foram verificadas nesta etapa.

Guia do consumidor: [module2-project-deletion.md](module2-project-deletion.md).

# Validação final das US locais — 31/10/2026

`python -m pytest -q --tb=short`, com `TEST_DATABASE_URL` em PostgreSQL 17
descartável/loopback e `BACKLOG_SERVICE_PATH` no checkout local:
**212 testes passaram, nenhum skip**, em 113,54 s.
Ruff, formato (40 arquivos), mypy (24 módulos), lock e build foram aprovados.

Inclui todos os tipos de recomendação, notificações por destinatário e replay,
preservação de concessões/prazos legados, liberação de capacidade após
conclusão/revogação, migrações e callback HTTP concorrente com pool limitado.
A integração opt-in verifica a política atual: projeto com backlog não é
excluído, o congelamento é desfeito e continua editável; cadastro vazio pode ser
excluído e o Backlog passa a recusá-lo, preservando o histórico do outro projeto.

A observação de atividade tem regressões para legado desconhecido, janela
completa, uso recente, alteração de concessão, erro de registro, validação
estrita e corrida entre uso autorizado e revogação, em SQLite e PostgreSQL.
Snapshots externos são coletados antes do writer; callbacks reais não bloqueiam
criação/aprovação. Uma escrita do Backlog intercalada invalida o rascunho mesmo
quando seu lease já foi liberado. Simples leitura não impede exclusão segura.

Múltiplas rodadas RED/GREEN reproduziram os defeitos antes das correções. Testes
controlados não provam entrega SMTP, qualidade de um provedor de IA real,
recuperação real de processos após crash ou disponibilidade em produção.

## Histórico das validações anteriores

# Evidências do serviço de projetos

## Separação multicamadas — 30/10/2026, somente local

- Baseline antes da extração: **133 passed, 4 skipped**, em 63,38 s. Ruff,
  formato, mypy e build wheel/sdist aprovados.
- RED dos novos testes: **3 failed, 1 passed**. Foram detectados SQL/ORM/sessão
  na aplicação, persistência nas rotas e retorno de `ProjectRecord` pelo
  repositório. Após a extração, as fronteiras passam com snapshots de domínio.
- Verificação final: **141 passed, 4 skipped**. Inclui falhas sintéticas de
  INSERT/commit na aceitação de convite e commit na alteração/remoção de vínculo:
  convite e permissões anteriores são preservados e a operação pode ser repetida.
- `ruff check .`, `ruff format --check .`, `mypy src/projects_service`,
  `uv lock --check`, `uv build --no-build-isolation` e `git diff --check` aprovados.
  Wheel/sdist inspecionados sem credenciais ou artefatos locais de instruções/planos.
- Os quatro skips são três cenários PostgreSQL (`TEST_DATABASE_URL` ausente) e
  a regressão HTTP separada com Backlog (`BACKLOG_SERVICE_PATH` ausente). Esta
  rodada usa somente SQLite sintético local e não comprova PostgreSQL ou integração
  completa dos serviços. A rodada coordenada será registrada separadamente.
- Sem acesso ao Neon, mudanças de schema/contrato, push, merge ou deploy.
  [Arquitetura e limites](architecture.md) descrevem os componentes implementados.

## Colaboração/perfil 0.4.0 — 28/10/2026, somente local

- Suíte completa com PostgreSQL 16.15 descartável em loopback, UTF-8/ICU und:
  **137 testes passaram, nenhum skip**, em 79,51 s.
- Ruff check/formato, mypy, lock e wheel/sdist verificados no candidato.
- Frontend 0.4.0: **96 testes passaram sem skips**, com três APIs reais e bancos/chaves
  temporários. Teste ampliado de duas contas também passou: convite, perfil,
  Desenvolvedor/status, promoção a PO e remoção/reutilização negada do código.
- Revisão própria de isolamento, contratos, expiração e concorrência. A revisão
  independente deste lote ficou indisponível por limite de uso dos auxiliares;
  a revisão independente histórica abaixo cobre somente o lote anterior.
- PostgreSQL encerrado e dados temporários removidos. Sem main/push/deploy/tag,
  sem acesso ao Neon ou alteração de grants/configuração remota.

## Conferência integrada do gerenciamento 0.3.0 — 28/10/2026

- Suíte completa com PostgreSQL 16.15 descartável e Backlog novo: **114 passaram,
  nenhum skip**, em 85,53 s. Inclui banco antigo preservado após migração repetida,
  PATCH isolado por proprietário, busca/paginação e regressão do DELETE.
- Integração no frontend 0.3.0: **85 testes passaram sem skips**, com as três
  APIs reais e bancos temporários. Cadastro/edição de objetivo e busca funcionam
  no navegador; o refinamento do backlog preserva a autorização pelo projeto.
- Revisão independente dos backends sem achados críticos/importantes. Dois achados
  de recuperação na interface foram reproduzidos em RED e corrigidos: confirmação
  de gravação seguida de 401 e preservação do rascunho se atualizar retorna 503.
- Ruff, formatação, mypy, lock check e wheel/sdist 0.3.0 passaram.
- Nada foi aplicado ao Neon ou à main. Migração e grants para a futura publicação
  continuam administrativos e explícitos; somente dados descartáveis foram usados.

## Candidato 0.3.0 — edição e busca — 28/10/2026

- Baseline: **86 passed, 2 skipped** (PostgreSQL e Backlog opt-in sem configuração).
- RED API/CLI: **22 failed, 39 passed**, por objective ausente, PATCH 405,
  filtro ignorado, CORS sem PATCH e CLI sem migrate. Após implementação: **61 passed**.
- Suíte completa: **111 passed, 3 skipped**. Skips: persistência PostgreSQL,
  migração PostgreSQL e integração Backlog, todos opt-in ainda sem configuração
  nesta execução. A rodada integrada do coordenador será registrada separadamente.
- Ruff check/formato, mypy (11 arquivos), lock check e git diff --check aprovados.
- Wheel e sdist 0.3.0 gerados localmente; versão do pacote alimenta OpenAPI.
- Cobertura de PATCH parcial, limites e Unicode, rejeição null/extras/imutáveis,
  owner no WHERE SQL, rollback statement/commit, erros seguros e no-store/CORS.
- Busca testa caixa, Unicode, `%`/`_` literais, trim, total/paginação e isolamento.
- Migração SQLite em tabela antiga preserva registros, executa duas vezes e
  comprova que init não migra a tabela; banco vazio não é criado por migrate.
- PostgreSQL opt-in cobre tabela antiga, migração duas vezes, objective vazio,
  edição/isolamento e busca persistentes após recriação da conexão.
- DELETE e retenção do backlog mantidos; nenhuma operação remota realizada.
- Revisão independente e PostgreSQL integrado ficam a cargo da rodada coordenada.

## Candidato 0.2.0 — exclusão de projetos — 28/10/2026

- Baseline anterior: 73 testes aprovados e um PostgreSQL opt-in não executado.
- TDD: 13 cenários novos falharam antes da implementação (405, método inexistente
  ou ausência do DELETE no CORS/OpenAPI) e passaram após a mudança.
- Suíte completa de Projetos com `BACKLOG_SERVICE_PATH` configurado: **87 passed,
  1 skipped**. O skip é PostgreSQL local por ausência de `TEST_DATABASE_URL`.
  Sem checkout do Backlog configurado, a regressão integrada também é pulada.
- Suíte completa do checkout de Backlog, sem modificar seu código: **118 passed,
  1 skipped**. PostgreSQL local também não estava configurado.
- Ruff lint/formato e mypy aprovados; `uv lock --check` aprovado; build de wheel
  e sdist 0.2.0 aprovado. Pacote instalado e OpenAPI anunciam 0.2.0.
- Testes verificam 204 vazio, 404 para ausente/alheio/repetição, JWT ausente,
  inválido e expirado, UUID inválido, indisponibilidade JWKS, CORS, preservação
  de outros projetos, rollback de SQL/commit e exclusão persistente após reinício.
- Regressão integrada usa a API de Projetos servida por HTTP em porta local
  aleatória e a API real do Backlog. JWT/JWKS e SQLite são temporários. Depois
  do DELETE, listar/consultar/criar/alterar histórias recebe 404; a história
  anterior continua armazenada e inalterada. Outro projeto segue acessível.
- Revisão independente somente leitura concluída sem achados.

### Rodada complementar com PostgreSQL real — 28/10/2026

Os dois skips de PostgreSQL foram resolvidos nesta rodada. Um PostgreSQL 16.15
portátil foi preparado em `.local/postgres-tests`, com cluster temporário,
credenciais sintéticas e acesso restrito a `127.0.0.1` em porta aleatória.
Não foi instalado serviço do Windows nem utilizada conexão do `.env`/Neon.

- **Projetos: 88 passed, nenhum skip**, incluindo PostgreSQL e integração HTTP
  com a API real do Backlog. Tempo: 48,30 s.
- **Backlog: 119 passed, nenhum skip**, incluindo PostgreSQL. Tempo: 35,57 s.
- Conferência adicional com role runtime sintética: sem DELETE, a remoção é
  recusada e o projeto permanece; após conceder DELETE somente na tabela própria,
  a remoção funciona, outro proprietário não exclui e repetir não remove outra linha.
- A mesma role não recebe UPDATE, CREATE no schema ou USAGE no schema de outro
  serviço. Tentativas reais de UPDATE e leitura da tabela alheia foram recusadas.
- Ruff lint/formato, mypy, lock check e build de wheel/sdist 0.2.0 passaram novamente.
- O processo do banco foi encerrado e os clusters/dados temporários foram removidos.

Execução reproduzível local, usando o helper ignorado da rodada:

```powershell
.venv/Scripts/python.exe -u .local/postgres-tests/run_tests.py
```

Esse helper prepara somente um banco descartável; não altera banco remoto.
Em outro ambiente, configurar `TEST_DATABASE_URL` para PostgreSQL **local
descartável** e `BACKLOG_SERVICE_PATH` conforme os READMEs permite executar as
mesmas suítes versionadas. As credenciais não são incluídas na documentação.

Código preparado em `feat/project-delete`, worktree `.worktrees/project-delete`.
Nenhum push, merge em main, tag, release, deploy ou comando SQL no Neon foi
executado. A permissão DELETE em runtime ainda depende do operador, conforme
[database-neon.md](database-neon.md). Container e deploy não foram validados
nesta rodada. A confirmação/limpeza de vínculos no GitHub Sync pertence
ao Módulo 2; o contrato está em [integration.md](integration.md).

## Registro histórico do MVP — 11/10/2026

## Valor demonstrado

A pessoa cadastra uma conta, entra, cria seu primeiro projeto e encontra o mesmo
projeto após reiniciar o serviço. Nome, descrição e data ajudam a registrar o objetivo
da entrega. Outra conta não pode consultar esse conteúdo, mesmo conhecendo seu id.

## Verificações

- Backend: suíte isolada, validação, paginação, persistência, tokens RS256 e falhas seguras.
- Um teste PostgreSQL descartável depende de `TEST_DATABASE_URL` loopback; nunca apontar
  essa variável ao Neon. Ele ficou pendente por falta de instância local descartável.
- Frontend: cadastro/login anteriores preservados, projetos, validação Unicode, teclado,
  HTML como texto, clique duplicado, indisponibilidade e resposta atrasada depois de logout.
- Integração com as duas APIs reais e bancos temporários: cadastro de A, criação pelo
  navegador, reinício do processo de projetos, consulta persistente e conta B isolada.
- Smoke separado na stack local com Neon: cadastro pelo navegador, POST 201, consulta,
  conta B recebe 404 e requisição sem Bearer recebe 401. Após parar/iniciar a API de
  projetos, a consulta do mesmo projeto retornou 200.
- Neon: schema `projects`, tabela `projects.projects`, role `mod1_projects_runtime`.
  Verificados USAGE e SELECT/INSERT; CREATE/UPDATE/DELETE e acesso a identidade recusados.
  TLS verify-full com raiz confiável. API em execução usa credencial runtime.
- Capturas sintéticas no MOD1-Frontend: desktop claro 1440, celular escuro 390 e
  validação no celular. Sem overflow horizontal; foco no detalhe ao criar e no campo
  inválido ao enviar formulário vazio. Uma rodada de inspeção visual foi suficiente.

Resultado: **73 testes backend passaram, 1 PostgreSQL local opt-in pendente**;
**47 testes frontend passaram**, incluindo integração com ambas as APIs reais.
Ruff, mypy e build de wheel/sdist passaram. Revisão independente concluída;
dois achados importantes corrigidos com regressões RED→GREEN: fonte sem chaves
RS256 retorna 503, e buscas por kid desconhecido são limitadas sem bloquear
validação por uma chave já conhecida. Auditoria adicional corrigiu o sdist:
wheel e sdist excluem `.env`, `.local` e `.superpowers`; teste usa segredos fictícios.
Os pacotes anteriores existiam somente em `dist` ignorado e não foram publicados.

## Roteiro da apresentação (2–3 minutos)

1. Abra `http://127.0.0.1:5173` e crie uma conta; entre com os mesmos dados.
2. Abra **Meus projetos**, explique o estado vazio e envie um nome vazio para ver a validação.
3. Crie um projeto com nome/descrição; consulte o detalhe e mostre a lista atualizada.
4. Reinicie somente projetos; entre novamente e encontre o mesmo projeto.
5. Saia, entre com outra conta e mostre sua lista separada. Explique a prova de 404
   para o UUID conhecido da primeira conta, registrada pelos testes/smoke.

Os serviços são separados: identidade 8000, projetos 8001 e frontend 5173. Com
identidade/frontend já iniciados, use o comando de execução do README deste repositório.
Sem publicação necessária para esta demonstração local. Código deve ser entregue com
link para a versão específica dos dois repositórios, depois de publicar as branches.

## Limites do recorte

Responsável único, sem equipes/convites/papéis/edição/exclusão/backlog. Desativar conta
impede login no emissor; JWT já emitido pode ser aceito até expirar. Logout limpa a
sessão do navegador. Chaves privadas pertencem exclusivamente à autenticação.

## Ajustes de execução

- Windows App Control bloqueou intérpretes temporários e executáveis auxiliares
  gerados. O build usa Python 3.12 no ambiente local com dependências explícitas e
  `--no-build-isolation`; comandos de aplicação usam `python -m`. A política do
  sistema foi preservada. Os comandos reproduzíveis precisam desse bootstrap aqui.
- A fixture integrada aguarda por até 5 segundos a liberação de arquivos temporários
  pelo Windows depois de encerrar exclusivamente os processos que criou.
- Buscas de JWKS respeitam intervalo de 30 segundos, inclusive após falhas, com cache
  válido por 300 segundos. Uma chave recém-rotacionada pode aguardar até 30 segundos
  para ser consultada novamente; chaves conhecidas não aguardam essa busca.

Credenciais, JWTs e evidências operacionais com contas sintéticas ficam em arquivos
ignorados. Nenhum teste removeu dados/schemas do Neon ou alterou identidade.

## Integração coordenada das camadas — 30/10/2026

- Revisão independente das mudanças de Identidade, Projetos, Backlog e Frontend
  não encontrou regressão funcional ou de segurança nos caminhos inspecionados.
  A lacuna de testes sem DOM do frontend foi corrigida com Worker e verificação
  negativa das fronteiras; a suíte final de navegador passou 124 testes sem skips.
- A suíte usa os três backends reais refatorados, SQLite/RSA temporários e os
  caminhos AUTH_BACKEND_PATH, PROJECTS_BACKEND_PATH e BACKLOG_BACKEND_PATH.
  Inclui login, perfil, projetos, backlog, convite, promoção de papel e remoção.
- O teste HTTP específico Projetos→Backlog passou com BACKLOG_SERVICE_PATH
  configurado. Não se presume teste de PostgreSQL a partir desse resultado.
- O ambiente local persistente foi reiniciado com os mesmos bancos e chave:
  readiness 200 nas três APIs, CORS 127.0.0.1:5173, login da conta de teste
  preservada e consulta de projetos 200 pelo navegador, sem erro JavaScript.
- Nenhum banco remoto, grant, configuração Azure, deploy ou dado de produção
  foi alterado. A integração PostgreSQL opt-in continua pendente nesta etapa.
- Componentes e limites das camadas estão em [architecture.md](architecture.md).
