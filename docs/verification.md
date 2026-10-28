# Evidências do serviço de projetos

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

Código preparado em `feat/project-delete`, worktree `.worktrees/project-delete`.
Nenhum push, merge em main, tag, release, deploy ou comando SQL no Neon foi
executado. A permissão DELETE em runtime ainda depende do operador, conforme
[database-neon.md](database-neon.md). Não foi validado PostgreSQL, container ou
deploy nesta rodada. A confirmação/limpeza de vínculos no GitHub Sync pertence
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
