# Projetos, equipes e recomendações — contrato 0.5.0

Este contrato descreve a versão 0.5.0 preparada para publicação. Não comprova
deploy ou disponibilidade de serviços externos. IA real permanece desabilitada.

## Projetos e ciclo de vida

POST/PATCH de `/projects` preservam nome, descrição e objetivo e acrescentam:
`scope`, `budget_amount` (string decimal não negativa, até duas casas, ou null),
`budget_currency` (três letras, BRL por padrão), `tags` (até 30),
`planned_start`/`planned_end` (datas ISO ou null), `technology_stack`,
`technical_requirements`, `soft_skills` e `constraints`. Datas são validadas
também contra os campos já armazenados durante um PATCH parcial. Omissão preserva
dados; campos desconhecidos e valores incompatíveis retornam 422 seguro.

Respostas acrescentam `status`, `archived` e `version`. Projetos novos começam
`planned`; a migração torna projetos antigos `active`, preservando o trabalho.
GET `/projects` combina `q`, `status`, `tag` e `archived` antes da paginação.
O padrão `archived=false` omite os arquivados.

| Operação | Corpo | Regra |
| --- | --- | --- |
| POST `/projects/{id}/lifecycle` | `{status,expected_version}` | Proprietário/PM; planned→active/suspended; active→suspended/completed; suspended→active/completed; completed→active |
| POST `/projects/{id}/archive` | `{expected_version}` | Apenas completed |
| POST `/projects/{id}/restore` | `{expected_version}` | Restaura como completed; reabrir exige operação explícita |
| POST `/projects/{id}/transfer` | `{user_id,expected_version}` | Apenas proprietário; destinatário ativo e já autorizado; proprietário anterior mantém PM direto |
| GET `/projects/{id}/history` | `limit,offset,action` | Histórico próprio append-only com ator, versão, horário e alterações |
| GET `/projects/{id}/audit` | `limit,offset,action` | Eventos de alterações de acesso, conforme project:audit:read |
| GET `/projects/{id}/summary` | — | Projeto/equipes e resumo autorizado do Backlog; falha retorna backlog=null e backlog_available=false |

Versão divergente retorna 409. Suspensos/concluídos impedem edição de escopo e
Backlog, mas preservam leitura, histórico, acesso e ciclo de vida. Arquivados
permitem leitura e remoção de acesso, exigindo restauração para as demais escritas.
As regras são verificadas no servidor.

## Identidade atual e permissões

Após verificar RS256/JWKS, Projetos consulta `/auth/me` com o mesmo Bearer em cada
requisição protegida. O ID deve corresponder ao `sub` e `is_active` deve ser true.
Token/conta recusados produzem 401; dependência indisponível ou inconsistente,
503. `AUTH_SESSION_CHECK_ENABLED=true` é o padrão, sem cache positivo. Desativação
é uma ferramenta explícita de testes isolados, não uma configuração de produção.

`GET /projects/{id}/access` mantém o formato legado. A versão nova,
`/access/v2`, informa access_version=2, IDs, papéis, permissões, definições,
status/arquivo/versão e origens owner/direct/team. Definições personalizadas
usam `custom:<UUID>`, contêm project:read e nunca project:delete. O servidor
impede delegar permissões que o próprio ator não possui. Papéis fixos e
operações exclusivas do proprietário permanecem protegidos.

Para evitar esgotamento de conexões quando Backlog autoriza callbacks durante
consultas/aprovações em Projetos, `/access`, `/access/v2` e elegibilidade usam um
pool de leitura separado e limitado. PostgreSQL possui dois pools de até duas
conexões cada, sem overflow. SQLite em memória compartilha o engine original.
Issuer, assinatura, sessão atual e políticas de acesso são iguais nos dois fluxos.

## Equipes, concessões e alocações

`/teams` cria/lista equipes; `/teams/{id}` consulta/edita nome, descrição e centro
de custo. Gestores mantêm `/members` e `/invitations`; aceitar/recusar códigos
ocorre em `/team-invitations/accept` e `/decline`. Códigos são hashes persistidos,
expiram em sete dias, são vinculados ao destinatário e usados uma vez.
Proprietários de equipe são protegidos. Centro de custo e taxas ficam restritos
a gestores; dados não são copiados para Identidade.

`/projects/{id}/roles` lista/cria papéis personalizados; PATCH/DELETE
`/roles/{key}` alteram/removem somente personalizados. Papel vinculado não é
removido (409). POST `/members` adiciona pessoa ativa manualmente.
PATCH `/members/{user_id}` aceita `roles` e `role_grants:[{role,expires_at}]`;
as concessões devem corresponder exatamente aos papéis, sem duplicações.
O campo legado `expires_at` aplica-se a todos quando não há concessões específicas.
Expiração existente é preservada ao aprovar recomendações de papéis.

POST `/projects/{id}/teams` recebe `{team_id,roles,expires_at?}`; DELETE
`/teams/{team_id}` remove só essa origem. Acesso efetivo reúne concessões diretas
e equipes ativas. Remover pessoa do projeto grava uma negação local para bloquear
também o acesso herdado, sem expulsá-la da equipe. Aprovar recomendação para equipe
já vinculada preserva a expiração do vínculo existente.

GET `/members/{user_id}/eligibility` verifica acesso no projeto e estado atual da
pessoa na Identidade, depois de autorizar o chamador. GET/PUT
`/projects/{id}/allocations` exige gestor e registra horas semanais e taxa/moeda
opcionais. GET `/allocations/me` mostra as próprias alocações e disponibilidade.
Somente alocações em projetos planned/active, não arquivados e ainda autorizados
reservam capacidade; suspensão, conclusão, arquivo ou revogação liberam a reserva
sem apagar o registro. Capacidade conhecida é verificada de forma serializada por
pessoa. Ausência de perfil/taxa não vira disponibilidade ou custo estimado.

## Exclusão coordenada com Backlog

DELETE exige proprietário, ausência de dados relevantes locais e zero leases
ativos. Sob lock, congela novas escritas; depois consulta o resumo do Backlog com
o mesmo Bearer. O congelamento só é confirmado vazio quando todos os contadores
são inteiros não negativos e total coincide com a soma. Contadores reconhecidos:
stories, epics, tasks, history, recommendations, recommendation_events e
review_events. Os três últimos podem faltar em consumidores antigos e valem zero;
campos desconhecidos, dados inconsistentes ou indisponibilidade impedem apagar.
Backlog e demais schemas nunca são alterados por esta API.

POST `/projects/{id}/write-leases` recebe operation_id UUID e retorna lease_id e
project_id. DELETE `/write-leases/{lease_id}` libera somente o lease do ator.
Operação repetida ativa é idempotente; lease já encerrado não é reutilizado.
Leases não expiram por TTL: processos que caíram exigem verificação administrativa
de que não há escritor em andamento antes de qualquer recuperação explícita.
Startup não libera leases nem descongela projetos. Esta branch não adiciona um
endpoint público de recuperação de crash. Em falhas tratadas de dependência ou
conteúdo relevante, a tentativa de exclusão desfaz seu congelamento.

## Recomendações e evidências

POST/GET `/projects/{id}/recommendations`, GET `/{recommendation_id}` e POST
`/{recommendation_id}/approve|reject` implementam rascunhos persistidos e decisões
com expected_version. Tipos: roles, access_revocation, teams, skills_map e training.
Uma pessoa precisa aprovar; o modelo não altera permissões automaticamente.
Contexto alterado expira o rascunho com 409; repetir decisão já aplicada não duplica
vínculos ou mensagens. Rejeição não concede nem revoga acesso.

Snapshots usam somente o projeto autorizado, papéis/equipes/alocações reais e o
diretório profissional opt-in da Identidade. Para roles, teams, skills_map e
training, incluem até 200 itens reais do Backlog, lidos com o mesmo Bearer,
com versão, tipo, título, status, responsável e dados de estimativa/bloqueio.
Associações de tarefas são explícitas. Página inconsistente, projeto cruzado,
duplicação ou falha da dependência retorna 503; mais de 200 itens retorna 422,
sem fingir um contexto completo truncado. A aprovação relê e compara o snapshot.
As leituras HTTP acontecem antes de adquirir o bloqueio de escrita do projeto,
para que callbacks autorizados não disputem um writer SQLite. Dentro do bloqueio,
permissões e estado local são revalidados. Recibos duráveis de leases detectam
escritas do Backlog concluídas entre a coleta do snapshot e a decisão, e leases
ativos impedem usar um snapshot durante uma escrita.

Evidências são referências conhecidas project:UUID, profile:UUID, team:UUID e
item:UUID. Sugestões só podem usar IDs/papéis disponíveis e estruturas próprias de
cada tipo. Treinamento sugere tópicos, sem inventar URLs de cursos.

### Acessos sem uso — observação conservadora

US-039 tem fundação local de atividade autorizada observada. Requisições com
acesso de leitura ao projeto registram atividade do próprio ator; `/access/v2`
inclui os consumidores do Backlog. Tentativas autorizadas contam de forma
conservadora, mesmo que uma operação posterior falhe. O registro usa relógio do
servidor e atualização atômica, no máximo uma vez por minuto. Falha de registro
impede a operação com 503, em vez de criar uma falsa ausência de uso.

Uma concessão ou mudança de equipe inicia/reinicia a janela. Vínculos legados sem
observação ficam desconhecidos; idade do vínculo não prova ociosidade. Somente
uma janela inteira observada sem uso recente torna uma pessoa candidata.
O proprietário e quem solicita a análise são excluídos.
`ACCESS_INACTIVITY_DAYS` tem padrão 30; o pedido pode usar
`constraints.unused_days`, inteiro entre 1 e 3650. Boolean/string são recusados.

O modelo recebe somente candidatos comprovados e evidências `activity:UUID`.
Sugestão fora desse conjunto é rejeitada. Aprovação humana relê e bloqueia as
observações para serializar uso concorrente e decisão de revogação. Atividade
recente torna a proposta obsoleta com 409; rejeitar nunca revoga. Leituras comuns
não invalidam propostas de outros tipos que não utilizam telemetria.

Observações operacionais são removidas com a exclusão explícita de um projeto
vazio e não transformam uma simples consulta em dado de negócio impeditivo.
O provedor de IA real e o comportamento em produção ainda não foram validados.

O adapter opcional faz POST `{AI_BASE_URL}/generate` com
`{schema_version:1,kind,model,context}` e espera
`{summary,justification,evidence,suggestions}`. AI_BASE_URL ausente desativa chamadas.
AI_API_KEY fica só no backend; timeout 30s, contexto até 128 KiB, resposta até
64 KiB, até 50 sugestões e nenhuma repetição automática de geração paga.
AI_SIMULATED=true só aceita loopback e aparece como simulated=true. Provider real,
qualidade do modelo e chamadas externas continuam pendentes de configuração e
validação autorizadas; testes com transporte controlado não demonstram IA real.

## Notificações internas de aprovação de equipe — US-059

Aprovação de teams grava na mesma transação o vínculo, a decisão, a outbox e uma
mensagem interna por destinatário que efetivamente possui acesso após a mudança.
Há unicidade por recomendação/destinatário; pessoas negadas no projeto não recebem
mensagem. Erro na entrega interna causa rollback de toda a aprovação, que pode ser
tentada novamente sem duplicar concessões. Concorrência é serializada pelo projeto.

GET `/notifications?limit=20&offset=0` retorna página da pessoa autenticada, com
`{id,project_id,kind,title,message,created_at,read_at}`. POST
`/notifications/{id}/read` recebe `{}` e retorna a mensagem; mantém o horário da
primeira leitura em chamadas repetidas ou concorrentes. IDs alheios e ausentes
recebem o mesmo 404. As rotas exigem sessão atual e respondem no-store. Mensagens
genéricas não contêm custos, nomes de candidatos, saídas privadas de IA ou tokens.

Outbox de teams entregue usa status delivered_in_app e destinatários explícitos.
Outras espécies mantêm o registro pendente, sem promessa de envio externo.
Nenhum SMTP é chamado: **envio por e-mail permanece pendente**, distinto da caixa
interna funcional. Aprovações históricas com outbox genérica não recebem mensagens
retroativas inventadas, pois seus destinatários não foram persistidos na época.

## Migração e operação local

`python -m projects_service.cli migrate` é explícito e idempotente. Acrescenta
details/status/archived/version/deletion_frozen a projetos existentes e role_grants
a membros/convites; as datas globais antigas continuam válidas pela compatibilidade
de leitura. Cria tabelas próprias para eventos, papéis, equipes/vínculos/convites,
negações locais, alocações, leases, recomendações, outbox e notifications.
A nova tabela notifications tem unicidade e índice por destinatário/data/ID.
Histórico anterior e mensagens antigas não são inventados. Startup não executa DDL.

Antes de atualizar um banco persistente, fazer backup e executar a migração com a
credencial administrativa apropriada; runtime recebe só permissões necessárias
no schema próprio. Reversão de aplicação requer versão compatível com os novos
campos; não há downgrade destrutivo automático. Testes de migração/concorrência
usam SQLite temporário e schemas aleatórios em PostgreSQL descartável loopback.
Neon, Azure, produção, SMTP e provedores pagos não foram modificados nesta etapa.
