# Artefatos do Módulo 3

Projetos oferece consulta de arquivos, versões e download da API pública de
artefatos. O navegador usa somente o backend de Projetos com o Bearer M1;
Projetos chama o Módulo 3 somente por GET, sem encaminhar JWT, cookies,
identificadores M1, perfis ou credenciais. Não é necessário CORS adicional.

## Vínculo explícito

Um usuário com `project:update`, em projeto editável, escolhe o projeto remoto
no catálogo e salva `module3_project_id` por `PATCH /projects/{id}`. O campo é
um inteiro positivo até 9007199254740991, ou `null` para desvincular. Omiti-lo
preserva o vínculo. Os nomes não fazem associação automática: os IDs do M1
são UUIDs e os do M3 são numéricos.

O vínculo fica nos metadados JSON já existentes; não há tabela nova, DDL ou
acesso a schemas de outro serviço. A edição mantém a autorização, o histórico,
a versão e as notificações normais de `project.updated`. As consultas não
alteram o vínculo nem a versão do projeto; a observação de acesso existente
continua sendo registrada. Projetos arquivados podem consultar arquivos.

## Rotas autenticadas do Módulo 1

| Método e caminho | Resultado |
| --- | --- |
| `GET /projects/{id}/artifacts/catalog` | Catálogo de projetos remotos para escolha explícita. |
| `GET /projects/{id}/artifacts?search=&artifact_type=` | Arquivos do projeto vinculado. Tipos: `PDF`, `MARKDOWN`, `PNG`, `JPEG`. |
| `GET /projects/{id}/artifacts/{artifact_id}/versions?module3_project_id=N` | Versões do arquivo. |
| `GET /projects/{id}/artifacts/{artifact_id}/download?module3_project_id=N` | Conteúdo da versão atual como anexo. |

As respostas JSON usam `items`, `total` e `truncated`; o catálogo e a listagem
incluem `enabled`. Arquivos e versões informam `module3_project_id`; versões
também informam `artifact_id`. Um projeto sem vínculo retorna lista vazia com
`module3_project_id: null`, sem consultar o provedor. A listagem aceita busca
de até 120 caracteres. Nenhum resultado expõe `file_path` do provedor.

Sessão online e `project:read` são conferidos antes e depois da rede, sem manter
conexão SQL durante o HTTP. O vínculo é conferido novamente; as rotas de arquivo
exigem o vínculo esperado para impedir uso de uma tela anterior à troca.
Antes de versões/download, o arquivo precisa pertencer ao projeto remoto
vinculado. Versões de outro arquivo são rejeitadas.

- `401`: sessão inválida. `404`: projeto/arquivo ausente ou inacessível.
- `409`: vínculo mudou; atualize a consulta.
- `422`: entrada inválida. `503`: recurso desativado, provedor indisponível,
  resposta inválida ou limites excedidos. Recusa do provedor público não
  provoca logout do usuário M1.

## Limites e operação

`MODULE3_ENABLED=false` por padrão. O pipeline de Projetos ativa o recurso
somente na API, com a base oficial fixa:
`https://modulo3-fhgjdpa6d5bbfvff.canadacentral-01.azurewebsites.net`.
Somente HTTP loopback com porta explícita é admitido em testes.

Cada operação tem prazo total de 30 segundos, conexão de até 5 segundos e
nenhuma repetição automática ou redirecionamento. JSON: até 1 MiB e 1000
registros válidos recebidos, com 100 exibidos e truncamento explícito.
Download: até 10 MiB, MIME seguro, nome gerado `artifact-ID.ext`,
`application/octet-stream`, `attachment`, `nosniff` e `Cache-Control: no-store`.
O navegador limita o tamanho novamente, cancela ao sair/trocar projeto ou
sessão e revoga a URL temporária após o download.

O Módulo 3 anunciou uma API sem autenticação; as permissões M1 protegem as
rotas M1 e não alteram a política pública do provedor.

Não há upload, criação remota ou disparo de IA. O GET de versões observado
não fornece `analysis_id`; por isso resumos, classificação e arquitetura
aguardam um contrato GET que permita descobrir a análise existente. Não
chamamos `POST /analyses/versions/{version_id}` para contornar essa ausência.

[Swagger do provedor](https://modulo3-fhgjdpa6d5bbfvff.canadacentral-01.azurewebsites.net/docs)
foi confrontado com GETs reais de catálogo, arquivos, versões e download em
24/11/2026. Testes locais usam respostas sintéticas por HTTP loopback e SQLite
isolado. Esses testes não representam escrita em produção ou teste destrutivo
no PostgreSQL Azure. [Validação](verification.md).
