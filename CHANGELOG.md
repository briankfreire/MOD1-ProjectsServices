# Changelog

Versão candidata do serviço: `0.2.0`, definida em `pyproject.toml`. O serviço possui
versão SemVer independente de identidade e frontend. A versão será publicada após
revisão e integração; esta mudança não cria tag ou release.

## Unreleased

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
