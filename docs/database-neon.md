# Permissões do banco de projetos

Schema padrão: `projects`; tabela: `projects.projects`; role runtime:
`mod1_projects_runtime`. O serviço só acessa seu schema. Use a conexão runtime
na API, com TLS verify-full e CA confiável para PostgreSQL remoto.

## Atualização para 0.3.0

Com backup e janela administrativa definidos pelo operador, parar instâncias
antigas e configurar DATABASE_URL administrativa e DATABASE_SCHEMA do próprio
serviço. Para banco novo, executar `init`; para tabela anterior, executar:

```powershell
uv run --locked --no-build-isolation python -m projects_service.cli migrate
```

O comando acrescenta somente `objective TEXT NOT NULL DEFAULT ''` à tabela de
projetos existente. Preserva IDs, owners, nomes, descrições e datas; linhas antigas
recebem objetivo vazio. É idempotente e pode ser repetido. Funciona em PostgreSQL
e SQLite isolado. Se não há tabela, falha com erro seguro: usar `init` para banco novo.
Nem startup nem `init` modificam tabelas existentes silenciosamente. Executar
migrações de forma serial; não é necessário remover coluna em rollback da aplicação.

Depois, com a conexão administrativa autorizada e identificadores conferidos:

```sql
GRANT UPDATE ON TABLE projects.projects TO mod1_projects_runtime;
```

Preservar USAGE no schema e SELECT/INSERT/DELETE somente nessa tabela. A API
volta a usar a credencial runtime, sem CREATE/ALTER, ownership ou acesso aos
schemas de identidade/backlog. A checagem SQL da seção abaixo passa a esperar
`true, false, true, true, true, true`. `init`/`migrate` não gerenciam privilégios.
Sem migração, operações que usam objective podem retornar 503; readiness só lê id.

Rollback de permissão, se necessário e autorizado:

```sql
REVOKE UPDATE ON TABLE projects.projects FROM mod1_projects_runtime;
```

Isso desabilita edição sem desfazer alterações já confirmadas. Nenhuma migração
ou concessão foi aplicada a banco remoto durante esta implementação.

## Atualização para 0.2.0

Não há alteração de tabela. Para habilitar DELETE em uma instalação anterior,
o operador deve conferir o nome da role/schema/tabela existentes e, usando uma
conexão administrativa autorizada, executar:

```sql
GRANT DELETE ON TABLE projects.projects TO mod1_projects_runtime;
```

Isso complementa USAGE no schema e SELECT/INSERT já existentes. Não conceder
CREATE, propriedade de objetos, privilégios administrativos nem acesso
a identidade/backlog. Não trocar credenciais ou owners. Se os nomes configurados
forem outros, o operador deve adaptar os identificadores explicitamente.

Conectado como runtime, verificar sem modificar dados:

```sql
SELECT has_schema_privilege(current_user, 'projects', 'USAGE'),
       has_schema_privilege(current_user, 'projects', 'CREATE'),
       has_table_privilege(current_user, 'projects.projects', 'SELECT'),
       has_table_privilege(current_user, 'projects.projects', 'INSERT'),
       has_table_privilege(current_user, 'projects.projects', 'UPDATE'),
       has_table_privilege(current_user, 'projects.projects', 'DELETE');
```

Esperado: `true, false, true, true, false, true`. Considerar também privilégios
herdados de PUBLIC ou membership. Conferir ausência de acesso a outros schemas.

A API e o comando `init` não gerenciam roles/permissões. Publicar a imagem nova
não concede esse privilégio. Sem ele, DELETE falha com 503 genérico; readiness
continua podendo retornar 200 porque só verifica SELECT.

Rollback de permissão, se necessário e autorizado pelo operador:

```sql
REVOKE DELETE ON TABLE projects.projects FROM mod1_projects_runtime;
```

Isso desabilita novas exclusões, mas não restaura projetos já excluídos. A política
de backup/retenção é administrativa. Nenhum comando deste documento foi aplicado
ao Neon durante a implementação. Testes de exclusão usam SQLite temporário ou
PostgreSQL local descartável opt-in; nunca usar Neon como TEST_DATABASE_URL.
