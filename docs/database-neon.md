# Permissões do banco de projetos

Schema padrão: `projects`; tabela: `projects.projects`; role runtime:
`mod1_projects_runtime`. O serviço só acessa seu schema. Use a conexão runtime
na API, com TLS verify-full e CA confiável para PostgreSQL remoto.

## Atualização para 0.2.0

Não há alteração de tabela. Para habilitar DELETE em uma instalação anterior,
o operador deve conferir o nome da role/schema/tabela existentes e, usando uma
conexão administrativa autorizada, executar:

```sql
GRANT DELETE ON TABLE projects.projects TO mod1_projects_runtime;
```

Isso complementa USAGE no schema e SELECT/INSERT já existentes. Não conceder
UPDATE, CREATE, propriedade de objetos, privilégios administrativos nem acesso
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
