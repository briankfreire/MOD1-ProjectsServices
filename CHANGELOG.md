# Changelog

## 0.5.0 — preparação de release, 2026-11-01

### Added

- Metadados de escopo, orçamento, requisitos e datas; ciclo de vida, arquivamento, transferência e histórico versionados.
- Equipes, papéis personalizados, concessões diretas/por equipe com expiração, alocações e elegibilidade validada na Identidade.
- Recomendações sujeitas à aprovação humana e notificações internas privadas/idempotentes. IA real permanece desabilitada e envio de e-mail de Projetos não é apresentado como concluído.
- `/access/v2` com catálogo, origens e permissões efetivas; leases duráveis para coordenar escritas do Backlog com exclusão.

### Changed

- Arquitetura multicamadas com schema exclusivo; sessão atual verificada online na Identidade por padrão.
- DELETE exige proprietário, cadastro vazio, ausência de leases e resumo válido do Backlog. Conteúdo relevante retorna 409; dependências indisponíveis retornam 503. Não existe cascata de bancos nem remoção de recursos GitHub.
- Migração explícita/idempotente preserva projetos legados como ativos; projetos novos começam planejados. APIs legadas preservadas conforme [contrato](docs/integration.md), com novos bloqueios de ciclo de vida e conteúdo.
- Evolução MINOR pré-1.0 por novas funcionalidades e mudanças de contrato. Versão preparada sem presumir publicação ou deploy.

## Correção local do contrato DELETE — 31/10/2026

- Swagger da exclusão alinhado à política já implementada de cadastro vazio,
  proprietário exclusivo e verificação de conteúdo/escritas em Projetos e Backlog.
- Respostas 403/409 e formato JSON dos erros, inclusive 422, documentados;
  sucesso continua 204 sem corpo e a requisição não exige corpo.
- Contrato de consumo para o Módulo 2 documenta confirmação, atualização da
  interface, reconciliação após falha de rede e limites dos vínculos externos.
- Sem alteração das regras de negócio, migração, publicação ou exclusão remota.

## 0.4.0 — candidato local, 2026-10-28

### Added

- Matriz fixa por projeto, múltiplos papéis, expiração do vínculo e consulta de acessos/membros/papéis.
- Convites por código aleatório de uso único, hash SHA256, validade de sete dias e destinatário obrigatório.
- Aceite/recusa e gestão serializados por projeto; proprietário protegido e DELETE exclusivo dele.
- Lista/detalhe/edição autorizados por acesso atual, com permissions no Project e 403 para ação proibida.
- Migração explícita/idempotente de members/invitations, sem DDL no startup ou acesso a outro schema.
- Contrato canônico para Backlog 0.3.0; códigos não passam por URL/storage. Sem envio de e-mail.

Versão candidata do serviço: `0.4.0`, definida em `pyproject.toml`. O serviço possui
versão SemVer independente de identidade e frontend. A versão será publicada após
revisão e integração; esta mudança não cria tag ou release.

## Unreleased

### Added — candidato 0.3.0

- Campo `objective` até 2000 caracteres, default vazio, em criação e respostas.
- PATCH parcial de nome, descrição e objetivo com owner na mutação SQL, validação
  estrita e confirmação após commit; identidade e data permanecem imutáveis.
- Busca literal case-insensitive de nome por `q`, com isolamento e paginação filtrada.
- CLI `migrate` explícita, aditiva e idempotente para bancos antigos SQLite/PostgreSQL.
- Documentação de UPDATE runtime restrito à tabela própria; CORS PATCH nas origens existentes.
- Testes de schema antigo com dados, repetição de migração, rollback, busca e owner.

### Changed — candidato 0.3.0

- Versão MINOR independente; pacote, lock e OpenAPI alinhados. DELETE e retenção
  do backlog preservados. Nenhum comando remoto foi executado.

## Anterior — candidato 0.2.0

### Added — candidato 0.2.0

- `DELETE /projects/{project_id}` com Bearer RS256 e exclusão restrita ao proprietário.
- Sucesso 204 sem corpo; 404 indistinguível para projeto ausente/alheio ou já excluído.
- DELETE no CORS das origens configuradas, sem ampliar a lista de origens.
- Contrato para o Módulo 2: histórias preservadas e inacessíveis, vínculos geridos
  pelo serviço responsável, sem remoção de recursos do GitHub.
- Procedimento administrativo para conceder DELETE somente em `projects.projects`.
- Regressões de isolamento, repetição, rollback, persistência e integração com Backlog.

### Changed — candidato 0.2.0

- Versão MINOR por funcionalidade nova; OpenAPI usa a versão dos metadados do pacote.
- Sem alteração do schema ou dos contratos existentes de criação e consulta.

## MVP anterior — candidato 0.1.0

### Added

- Imagem Docker sem privilégios, checks de container e publicação manual Azure/OIDC por digest, com guia de configuração Neon.

- API independente para criar, listar e consultar projetos do responsável.
- Persistência no Neon, schema próprio e credencial runtime com SELECT/INSERT.
- Validação RS256 via JWKS confiável, issuer/audience e claims estritas.
- Paginação, validação de entrada, health checks e erros seguros.
- CLI de preparação explícita e testes isolados/integrados com evidências.

### Fixed

- Fonte sem chaves RS256 utilizáveis retorna indisponibilidade.
- Atualização de JWKS é limitada sem bloquear a validação por chaves conhecidas.
- Pacotes de distribuição excluem configurações e artefatos privados.
