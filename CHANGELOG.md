# Changelog

Versão candidata do serviço: `0.1.0`, definida em `pyproject.toml`. O serviço possui
versão SemVer independente de identidade e frontend. A versão será publicada após
revisão e integração; esta mudança não cria tag ou release.

## Unreleased

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
