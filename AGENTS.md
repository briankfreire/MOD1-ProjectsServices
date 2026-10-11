# Trabalho neste repositório

- Serviço de projetos mantido por Brian; autenticação pertence ao módulo de Caue e backlog ao de Igor.
- Todo commit criado por Caue/Codex neste trabalho deve incluir `Co-authored-by: Brian Freire <briankfreire@outlook.com>`.
- Preserve o histórico e trabalhe em uma branch de funcionalidade. O hook local do clone acrescenta a coautoria; em outro clone, inclua o trailer explicitamente.
- Não versione `.env`, credenciais, tokens, chaves privadas ou arquivos de operação em `.local/`.
- Cada serviço acessa somente seu próprio schema. Não adicione joins ou FKs entre projetos e tabelas de identidade/backlog.
- Testes usam dados e chaves sintéticos. Testes que removem schemas devem recusar bancos remotos.
