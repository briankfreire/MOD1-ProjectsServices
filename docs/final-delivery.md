# Entrega de Projetos — 15/11/2026

A versão `0.6.0` está publicada na Azure. Este registro descreve o estado
verificado nesta data; os documentos com datas anteriores preservam suas
evidências históricas. [README e execução](../README.md).

| Evidência de publicação | Referência |
| --- | --- |
| Versão do pacote/OpenAPI | `0.6.0` |
| Commit de produção | [ebdacfe3](https://github.com/briankfreire/MOD1-ProjectsServices/commit/ebdacfe3b3abaa687933e89da2c1b7ba6c5088d0) |
| Integração | [PR #19](https://github.com/briankfreire/MOD1-ProjectsServices/pull/19) |
| Deploy concluído com sucesso | [GitHub Actions 43731621992](https://github.com/briankfreire/MOD1-ProjectsServices/actions/runs/43731621992) |

Não foi criada tag ou GitHub Release nessa publicação. Versões integradas:
Identidade 0.5.0, Projetos 0.6.0, Backlog 0.5.0 e Frontend 0.6.0.

## Integrações ativas

- Gemini real nas três APIs: `AI_PROVIDER=gemini`, `AI_SIMULATED=false` e
  `GEMINI_MODEL=gemini-3.5-flash-lite`. Os sete tipos dos adaptadores tiveram
  chamadas reais HTTP 200 com contexto sintético autorizado: análise de acessos,
  papéis, revogação, equipes, mapa de habilidades, treinamento e backlog inicial.
  A aprovação permanece humana; transporte validado não garante a qualidade de
  todos os cenários ou disponibilidade futura. [Contrato Gemini](gemini.md).
- CORS publicado nas três APIs para as origens aprovadas de GitHubSync
  (Módulo 2) e MackAI (Módulo 7), preservando frontend M1 e localhost 5173.
  Após os deploys, 36/36 preflights passaram; origens negativas foram bloqueadas
  e a ausência de Bearer continuou retornando 401 com CORS correto.
- Notificações de Backlog e Projetos ao Módulo 6 ativas, com workers separados
  e `source=backlog`. Identidade não emite esses eventos. Há um aceite real
  HTTP 200 de aviso com escopo de projeto, sem inspeção visual da Central.
  [Contrato e operação](module6-notifications.md).

## Evidências de Projetos

- CI final aprovado com testes, lint, tipos, auditoria de dependências e build.
  Na ativação final, 71 testes focados passaram e a suíte teve 358 aprovados
  e 11 ignorados. Os cenários opt-in PostgreSQL e HTTP entre APIs foram
  executados separadamente em ambiente local descartável antes da publicação.
- Login, leitura de projetos e `/access/v2` foram exercitados em produção com
  conta sintética já existente. O mesmo JWT foi recusado após logout.
- O worker `module6-worker` está Running/ready, sem reinícios observados na
  verificação da ativação, sem ingress e com acesso somente ao schema
  `projects`. Usa a mesma imagem da API e réplica mínima um.
- Avisos de criação, ciclo de vida, arquivo/restauração e aprovação de equipes
  usam `source=backlog`, tipos `project.*` e prefixo `mod1:projects:`.
  A convenção foi adotada para eventos compartilhados do Módulo 1 sem criar
  um novo valor no enum do receptor.
- Um aviso real `project.integration_test`, limitado a um projeto sintético
  já existente, foi aceito com HTTP 200 e confirmação válida. Não criou
  entidade de negócio nem aviso global. A validação não percorreu um novo
  evento de negócio pelo outbox de produção nem inspecionou visualmente a Central.

Notificações internas da aprovação de equipes continuam privadas por
destinatário, independentes da fila externa. Projetos não envia e-mail de
aprovação de equipes. [Catálogo e operação M6](module6-notifications.md).

## Validação e limites comuns

As seis rotas públicas de saúde das três APIs responderam 200. A chave
JWT/JWKS existente e os dados anteriores foram preservados. O deploy incremental
manteve configurações de CORS, e-mail, MFA e segredos; migrações aditivas foram
executadas explicitamente, sem DDL no startup ou testes destrutivos em banco
remoto. API, aplicação, domínio e infraestrutura mantêm a
[arquitetura multicamadas](architecture.md).

O navegador em produção cobriu login, perfil, projetos e logout, em desktop e
mobile, sem overflow ou erros de página observados. Em ambiente isolado, o Edge também exerceu os sete tipos reais de Gemini,
persistência após reinício, aprovação idempotente de papéis/backlog, rejeição
e expiração de proposta após mudança de contexto. Equipes retornou vazio
válido; seu caminho positivo continua coberto pelos testes controlados.
[Aceite e reprodução de IA](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/local-ai-testing.md).

O aceite do Módulo 6 comprova transporte e confirmação de um aviso autorizado,
não o percurso completo de um novo evento de negócio pelo outbox de produção
nem sua apresentação na Central. Não há replay de histórico, anúncios globais ou
emissão de eventos privados não mapeados. O contrato externo de revisão de código
US-096 permanece pendente e desabilitado.

Comandos reproduzíveis e evidências históricas estão em
[verification.md](verification.md); operação e rollback em
[deploy-azure.md](deploy-azure.md).

## Fechamento da rastreabilidade

O escopo do Módulo 1 tem 99 US implementadas com evidências de teste e
uma dependência externa aberta, US-096. US-101 duplica US-009.
A aprovação de equipes com saída não vazia do Gemini não foi exercitada
nessa rodada: a análise real vazia foi dispensada sem efeitos. Isso não
substitui os testes controlados de aplicação/notificação desse tipo.
[Matriz e limites do aceite](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/backlog-status.md).
Os commits finais de documentação não alteram a versão nem o contrato
HTTP destes backends. O frontend 0.6.1 acrescenta as correções de permissões
e navegação descritas em seu changelog; `/release.json` identifica o SHA
efetivamente implantado.
