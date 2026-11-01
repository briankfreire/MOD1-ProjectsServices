# Exclusão de projetos — contrato para o Módulo 2

Contrato da versão 0.5.0. O Swagger identifica a versão efetivamente em execução
no ambiente consultado; confira também a release correspondente no GitHub.
O Swagger é gerado a partir da mesma implementação.

## Requisição

`DELETE /projects/{project_id}`, sem corpo, com o mesmo
`Authorization: Bearer <JWT>` usado nas demais operações de Projetos.
O identificador é o UUID retornado no cadastro do projeto. O proprietário é
identificado pelo token e confirmado pelo serviço, sem aceitar um proprietário
informado pelo cliente. Somente ele pode excluir; PO, PM e Desenvolvedor não
recebem esse direito por seu papel.

## Respostas

Todas têm `Cache-Control: no-store`. O sucesso não tem conteúdo nem
`Content-Type`; as falhas têm JSON no formato `{"detail":"mensagem"}`.
O cliente deve decidir pelo status HTTP; os textos não são códigos estáveis.

| HTTP | Significado | Tratamento no GitHub Sync |
| --- | --- | --- |
| `204` | Cadastro vazio excluído, sem corpo | Não executar `response.json()`; fechar a confirmação e atualizar lista/seleção e vínculos próprios pertinentes. |
| `401` | Bearer ausente, inválido, expirado ou sessão recusada | Solicitar nova autenticação conforme a política da sessão. |
| `403` | Projeto visível, mas o chamador não é proprietário | Informar falta de permissão e manter a sessão. |
| `404` | Projeto inexistente ou inacessível; também ocorre ao repetir DELETE após sucesso | Atualizar os projetos acessíveis; não afirmar que houve exclusão apenas com esse retorno. |
| `409` | Conteúdo relevante, vínculos/histórico ou escritas em andamento | Preservar o projeto na interface e explicar o impedimento. Para trabalho existente, usar o fluxo de arquivamento. |
| `422` | Identificador inválido | Corrigir o UUID, sem repetir automaticamente. |
| `503` | Banco, Identidade, chaves ou Backlog indisponíveis/inconsistentes | Não presumir sucesso ou ausência de conteúdo. Preservar a ação como pendente e reconciliar por leitura. |

Exemplos de falha: `{"detail":"Insufficient project permissions"}` em `403`,
`{"detail":"Project unavailable"}` em `404` e
`{"detail":"Project contains relevant data or active writes"}` em `409`.
Uma repetição após `204` retorna `404`, não um segundo `204`.

## Backlog e vínculos

A exclusão definitiva é destinada a cadastros vazios criados por engano. Não
há exclusão em cascata de backlog ou de recursos em outros serviços.

O serviço verifica membros, convites, equipes vinculadas, alocações, papéis
personalizados, recomendações, negações de acesso e histórico relevante. A simples
criação do projeto é a exceção no histórico. Ter removido um vínculo não apaga o
histórico e não torna necessariamente o cadastro elegível para DELETE.

Antes de concluir, Projetos impede novas escritas e consulta o resumo autorizado
do Backlog com o mesmo Bearer. Histórias, épicos, tarefas, histórico, recomendações
e eventos de recomendações/revisão existentes impedem a exclusão. Escritas em
andamento também impedem. Falha da consulta nunca equivale a backlog vazio.

Para projetos com trabalho ou histórico, o fluxo é concluir e arquivar, preservando
as consultas autorizadas. Não remover dados ou vínculos apenas para forçar DELETE.

Repositórios, branches, PRs e referências mantidas no GitHub Sync não são apagados
por esta API. Também não há consulta automática a referências dos demais módulos.
O tratamento desses vínculos precisa de acordo explícito entre os módulos;
o cliente não deve fazer limpeza destrutiva remota como consequência implícita.

## Confirmação e falhas de rede

Mostrar o nome do projeto na confirmação e restringir a ação ao proprietário
conforme os dados autorizados da API; o backend revalida a permissão mesmo assim.
Enquanto a requisição estiver em andamento, evitar um segundo envio.

Após `204`, atualizar a lista a partir da API. Se houver timeout ou resposta
perdida, consultar `GET /projects/{project_id}` com a mesma identidade antes de
decidir por nova tentativa. `200` confirma que o projeto continua acessível;
`404` informa indisponibilidade para essa conta e exige atualizar a listagem;
`503` mantém o resultado incerto. Nenhum desses casos autoriza declarar uma
exclusão bem-sucedida sem confirmação. Uma resposta `503` posterior não comprova
que um commit anterior deixou de ocorrer.

Validações e coordenação entre serviços: [integration.md](integration.md).
