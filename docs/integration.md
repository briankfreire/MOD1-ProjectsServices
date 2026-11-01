# Contrato HTTP de Projetos — 0.5.0

O contrato atualizado está em [remaining-user-stories.md](remaining-user-stories.md),
incluindo metadados, ciclo de vida, equipes, concessões, alocações, recomendações e
notificações. Versão preparada para publicação; disponibilidade depende de deploy
verificado. O conjunto de contratos usa Identidade 0.4.0 e Backlog 0.4.0.

## Autenticação e respostas

Toda operação protegida verifica JWT RS256/JWKS e estado atual via GET Identidade
/auth/me com o mesmo Bearer. O proprietário é derivado do sub, nunca do formulário.
401 indica autenticação recusada; 403, ação negada em objeto visível; 404 oculta
objeto ausente ou sem acesso; 409, versão/conteúdo/estado conflitante; 422, entrada
inválida; 503, dependência indisponível ou inconsistente. Erros são sanitizados.
Páginas usam items,total,limit,offset (padrão 20, máximo 100). Mutação rejeita extras.
Operações protegidas respondem Cache-Control:no-store; CORS aceita só origens
configuradas. Tokens e códigos secretos não pertencem a URLs ou logs.

## Contratos preservados

POST/GET /projects e GET/PATCH/DELETE /projects/{id} permanecem. Campos de projeto
novos são aditivos; a política de exclusão passou a recusar dados relevantes.
GET /projects/{id}/access mantém sua forma; /access/v2 acrescenta definições e
origens coerentes para consumidores novos. Membros/convites antigos continuam
usáveis, com fallback da expiração global para concessões antigas.

## Exclusão definitiva

O contrato de respostas e o tratamento recomendado para o consumidor estão em
[Exclusão de projetos — Módulo 2](module2-project-deletion.md).

DELETE é exclusivo do proprietário e só aceita cadastro sem conteúdo relevante.
Primeiro, sob lock, verifica dados próprios e zero leases ativos e congela novas
escritas. Depois consulta GET Backlog /projects/{id}/content-summary com o mesmo
Bearer. A leitura é permitida durante o congelamento, sem adquirir lease.
Finalmente revalida o estado sob lock antes do DELETE e commit. Conteúdo relevante
retorna 409; dependência indisponível/inconsistente retorna 503. Falhas tratadas
revertem o congelamento. Não há autorização por simples check-then-delete.

Resumo reconhece stories,epics,tasks,history,recommendations,recommendation_events,
review_events e total; total deve ser sua soma. Os três contadores novos podem
faltar e valem zero por compatibilidade. Campo desconhecido não é ignorado numa
decisão de exclusão. Todos os contadores devem ser inteiros não negativos.

Backlog adquire POST /projects/{id}/write-leases antes de cada escrita e libera
DELETE /write-leases/{lease_id} após commit/rollback. operation_id torna a aquisição
idempotente; lease encerrado não é reutilizado. Não há expiração automática que
permita escrita atrasada após exclusão. Leases de crash exigem operação
administrativa explicitamente verificada, sem limpeza implícita no startup.

Não há cascata entre schemas/serviços e nenhum recurso GitHub é removido.
Referências externas de outros módulos ainda precisam de contrato explícito;
ausência de integração não comprova inexistência desses dados. O consumidor deve
preferir arquivar projeto com trabalho e histórico, mantendo leitura autorizada.

204 não tem corpo; repetir DELETE retorna 404. Após timeout ou perda de resposta,
consultar GET com a mesma identidade antes de repetir. Resposta 503 não prova que
o commit anterior falhou. Em 401, refazer autenticação; em falha de reconciliação,
manter a ação pendente sem inventar seu resultado.

## Callbacks e disponibilidade

Backlog chama access/v2 e elegibilidade com o mesmo Bearer. Essas leituras usam
pool separado e limitado para não disputar com requisições que já seguram conexão
de Projetos. Autenticação e autorização permanecem iguais. SQLite em memória
compartilha engine para preservar o mesmo banco isolado. O teste de concorrência
faz dois resumos simultâneos com callbacks HTTP reais em loopback e PostgreSQL
descartável. Isso não comprova disponibilidade em produção.
