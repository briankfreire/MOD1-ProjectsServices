# Colaboração por projeto — candidato 0.4.0

Projetos controla membros, convites e autorização. JWT identifica o usuário e não
contém papéis de projeto. Toda consulta calcula permissões atuais pelo servidor;
papéis são independentes entre projetos e compõem união quando há mais de um.

| Papel | Projeto | Integrantes | Backlog |
| --- | --- | --- | --- |
| Proprietário | Consultar, editar, excluir | Consultar/gerenciar | Consultar/criar/refinar/atualizar status |
| Product Owner | Consultar/editar | Consultar | Consultar/criar/refinar/atualizar status |
| PM/Scrum Master | Consultar/editar | Consultar/gerenciar | Consultar/criar/refinar/atualizar status |
| Desenvolvedor | Consultar | Consultar | Consultar/atualizar somente status |

Keys atribuíveis: `product_owner`, `project_manager`, `developer`. `owner` é
implícito e protegido; não se atribui ou remove pela API. Nenhum membro recebe
`project:delete`. O proprietário não pode ser removido nem ter seus papéis editados.
Papéis personalizados e permissões arbitrárias não são suportados neste lote.

## API com o mesmo Bearer

| Método | Rota | Sucesso |
| --- | --- | --- |
| GET | `/projects/{id}/access` | 200: project_id, user_id, is_owner, roles, permissions |
| GET | `/projects/{id}/roles` | 200: items com key/name/permissions dos três papéis |
| GET | `/projects/{id}/members?limit=20&offset=0` | 200: items/total/limit/offset; dono primeiro |
| PATCH | `/projects/{id}/members/{user_id}` | 200 Member; roles obrigatório, expires_at opcional |
| DELETE | `/projects/{id}/members/{user_id}` | 204 sem corpo |
| POST | `/projects/{id}/invitations` | 201: convite e código retornado uma única vez |
| POST | `/invitations/accept` | 200 Access do destinatário |
| POST | `/invitations/decline` | 204 sem corpo |

Member contém user_id, roles, expires_at UTC ou null e is_owner. Lista aceita
limit 1..100 / offset >= 0. Membros autorizados podem consultar IDs/papéis/expiração do
mesmo projeto; não existe diretório de pessoas por e-mail ou de outros projetos.
Project nas rotas anteriores acrescenta permissions do chamador; listagem inclui
projetos próprios e vínculos ativos sem duplicação, mantendo busca/paginação.

PATCH membership aceita roles 0..3 únicas, com vocabulário fixo; lista vazia revoga
todo acesso. Expiração futura se fornecida, null remove, omissão mantém o valor
exato anterior. A data pertence ao vínculo inteiro, portanto vale para todos os
papéis atribuídos àquela pessoa naquele projeto. Horário do servidor é a autoridade.

## Convite por código

Gestor informa `{user_id, roles, expires_at?}`. O destinatário compartilha seu próprio
UUID mostrado na conta. Não há envio por e-mail nem inclusão automática. Criar um
convite para usuário já vinculado ou dono retorna 409; editar o vínculo existente.

Resposta inclui id, project_id, user_id, roles, expires_at, code e code_expires_at.
Código aleatório de 256 bits, validade até 7 dias, vinculado ao destinatário autenticado;
se a validade do vínculo terminar antes, o aceite também se torna indisponível.
O banco armazena apenas SHA256 do código, não seu conteúdo. Nunca colocar o código
na URL, logs, repositório ou storage persistente do navegador. Ele só aparece na
resposta de criação e na tela do gestor enquanto aberta.

Aceitar/recusar usa JSON `{code}` e exige login da conta destinatária. Código
errado, usado, expirado ou de outra conta retorna 404 `Invitation unavailable`.
Transações serializadas por projeto permitem apenas uma ação; aceitar não pode
sobrescrever vínculo existente. Editar/remover vínculo invalida outros convites
pendentes para aquela pessoa. Não há listagem/reenvio/cancelamento administrativo
de convite ainda não aceito nesta versão; o limite temporal permanece aplicável.

## Erros e integração

401 para Bearer inválido;404 para projeto inacessível/ausente;403
`Insufficient project permissions` para ação proibida num projeto legível;409 para
proprietário protegido/vínculo já existente;422 entrada inválida;503 indisponível.
Erros são genéricos e respostas de projeto/convite usam Cache-Control:no-store.
403 não significa sessão encerrada. Repetir uma aceitação após perda de resposta
pode dar404: consultar projetos acessíveis, sem presumir que não houve gravação.

Backlog 0.3.0 deve consultar `/access` em cada operação com mesmo Bearer, validando
project_id/user_id/roles/permissions. Permissões: backlog:read/create/update/update_status.
Status-only exige update_status; textos/prioridade exigem update. Revogar/expirar
afeta novas verificações; uma operação já autorizada pode terminar, pois não existe
transação distribuída. Não há consulta direta a banco de outro serviço.

## Preparação administrativa, ainda não aplicada remotamente

Em instalação anterior, executar explicitamente `python -m projects_service.cli migrate`
com credencial administrativa autorizada. A migração cria members/invitations no schema
próprio e preserva projetos/objetivo. É idempotente; startup não executa DDL. init é
usado para instalação nova. FK/cascata existe apenas entre tabelas deste serviço.

Conferir nomes reais antes de conceder, usando os defaults como exemplo:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON projects.members TO mod1_projects_runtime;
GRANT SELECT, INSERT, UPDATE ON projects.invitations TO mod1_projects_runtime;
```

Preservar USAGE no schema e SELECT/INSERT/UPDATE/DELETE em projects.projects já
documentados. Não conceder CREATE, acesso a schemas alheios ou privilégios de dono.
Readiness verifica leitura da tabela principal, não garante preparo das tabelas
novas ou privilégios de mutação. Confirmar migração/grants antes da publicação.
