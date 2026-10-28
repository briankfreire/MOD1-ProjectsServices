# Contrato de projetos — candidato 0.3.0

Projetos, Identidade e Backlog são serviços separados. Projetos valida JWT RS256
pelo JWKS confiável configurado, usando os mesmos issuer/audience da Identidade.
O proprietário vem de `sub` do JWT; o cliente não escolhe `owner_id`.

## Rotas

| Método | Rota | Sucesso |
| --- | --- | --- |
| POST | `/projects` | 201, Project |
| GET | `/projects?q=&limit=20&offset=0` | 200, ProjectPage dos próprios projetos |
| GET | `/projects/{project_id}` | 200, Project próprio |
| PATCH | `/projects/{project_id}` | 200, Project próprio atualizado |
| DELETE | `/projects/{project_id}` | 204, sem corpo |

Project contém `id`, `owner_id`, `name`, `description`, `objective`, `created_at` UTC.
ProjectPage contém `items`, `total`, `limit`, `offset`. Toda rota exige
`Authorization: Bearer <JWT>` e responde com `Cache-Control: no-store`, inclusive
nos erros. CORS permite PATCH e DELETE somente para as origens previamente configuradas;
a origem do GitHub Sync precisa constar em `CORS_ORIGINS` se a chamada vier do navegador.

## Criação, edição e busca — 0.3.0

POST aceita `name` (aparado, 1–120), `description` e `objective` (strings até 2000,
default `""`). PATCH aceita um subconjunto não vazio desses mesmos três campos;
omitir preserva o valor existente, e strings vazias limpam descrição/objetivo.
Null, extras, tipos incorretos e campos imutáveis retornam 422 sanitizado.
`id`, `owner_id` e `created_at` permanecem iguais. O owner vem somente do JWT e
integra o WHERE da própria instrução UPDATE, com id; commit precede a resposta 200.
Projeto ausente/alheio recebe o mesmo 404 `{"detail":"Project unavailable"}`.
401, 422 e 503 seguem os corpos seguros da tabela DELETE abaixo.

GET `/projects` aceita `q` string aparada até 120 caracteres, default vazio.
A busca é uma substring literal no nome, sem distinção de caixa: `%`, `_` e `/`
não viram curingas. Não pesquisa descrição/objetivo. Proprietário e busca filtram
antes do total e da paginação; a ordem continua created_at DESC, id DESC.
Status/etiquetas não fazem parte desse filtro.

Timeout/503 não confirma edição: consultar GET para reconciliar antes de repetir.
Se o salvamento respondeu 200 e a recarga falhou, o cliente deve manter o sucesso
da gravação e oferecer atualização manual.

## DELETE /projects/{project_id}

Disponível a partir do candidato 0.2.0, após integração/publicação e atualização
da permissão runtime do banco. Nenhum corpo de requisição é necessário.
`project_id` é UUID. Somente o proprietário pode excluir. A remoção filtra
`project_id` **e** `owner_id` na mesma instrução SQL e só confirma após o commit.

| Status | Corpo | Tratamento pelo consumidor |
| --- | --- | --- |
| 204 | vazio, sem Content-Type JSON | Remover da lista e limpar seleção/detalhe; não chamar `response.json()` |
| 401 | `{"detail":"Authentication required"}` | Solicitar login; inclui `WWW-Authenticate: Bearer` |
| 404 | `{"detail":"Project unavailable"}` | Projeto ausente, alheio ou já excluído; atualizar a lista, sem revelar existência |
| 422 | `{"detail":"Invalid project input"}` | Corrigir UUID; não repetir a mesma entrada |
| 503 | `{"detail":"Service temporarily unavailable"}` | Banco ou chaves indisponíveis; consultar estado antes de decidir repetir |

A operação é idempotente no efeito: repetir a exclusão retorna 404 e não altera
outros projetos. Um timeout/perda de resposta ou 503 não comprova que o projeto
continua existindo: o resultado do commit pode ser desconhecido para o cliente.
Consulte GET `/projects/{project_id}` com a mesma identidade: 200 indica que ele
ainda existe; 404 significa indisponível para esse usuário. Em 401, refaça login;
em falha de rede/503, mantenha a ação pendente até conseguir reconciliar.

## Backlog e vínculos associados

**Não há exclusão em cascata entre serviços.** DELETE remove somente a linha
de `projects.projects`. Não consulta nem modifica schemas de outros módulos.

- **Backlog:** não é necessário apagar histórias antes. Elas permanecem
  armazenadas, mas GET/listagem/criação/PATCH subsequentes recebem 404 porque
  o Backlog consulta GET do projeto com o mesmo Bearer em cada operação.
  Essa retenção não oferece uma função de restauração ou limpeza automática.
- **Concorrência:** uma operação de backlog cuja autorização ocorreu antes da
  exclusão pode terminar e gravar sua história. Não há lock ou transação
  distribuída entre as APIs. Todas as novas verificações de acesso recebem 404.
- **GitHub Sync:** vínculos, webhooks, índices e tarefas pertencem ao Módulo 2.
  Esta API não conhece esses registros, não os remove, não envia callback/evento
  e não exige uma confirmação de limpeza deles para excluir.
- **GitHub:** nenhum repositório, issue, branch ou PR remoto é excluído.

No GitHub Sync, a sequência recomendada é:

1. Exibir confirmação explícita: o projeto deixará de estar disponível e seu
   backlog ficará inacessível; recursos no GitHub serão mantidos.
2. Após confirmação, guardar `project_id` para reconciliação e suspender novas
   sincronizações desse projeto no Módulo 2 enquanto a ação estiver pendente.
3. Chamar DELETE com o Bearer da sessão. Em 204, limpar vínculos locais conforme
   a política do Módulo 2 e atualizar a interface. Em 404, reconciliar a lista e
   os vínculos dessa identidade; não interpretar 404 como prova de propriedade.
4. Se a limpeza local falhar depois do 204, mantê-la pendente e tentar novamente
   no Módulo 2. O projeto já foi excluído; não reportar que continua disponível.
5. Em timeout/503, reconciliar por GET antes de reativar sincronizações ou dar
   a ação como concluída. Nunca confundir indisponibilidade com confirmação.

Exclusão física do histórico ou cascata distribuída exigirá outro contrato com
coordenação entre os responsáveis. A interface deve apresentar a política atual.

## Banco e implantação

A versão 0.3.0 exige migração explícita aditiva de `objective` em bancos antigos.
A role runtime precisa de UPDATE e DELETE somente em sua tabela, além de
SELECT/INSERT e USAGE já existentes. Procedimento do operador em
[database-neon.md](database-neon.md). Sem UPDATE, PATCH retorna 503; readiness
verifica leitura e não comprova permissões de escrita ou versão do schema.
