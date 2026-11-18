# Curadoria do Módulo 5

A área de curadoria de um projeto apresenta notícias técnicas e permite buscar
artigos com uma pergunta explícita. O acesso exige um JWT do Módulo 1, uma sessão
ativa verificada na Identidade e a permissão atual `project:read`. Projetos
arquivados também podem usar os endpoints.

| Método e caminho | Operação |
| --- | --- |
| `GET /projects/{project_id}/curation/feed` | Lê o feed da categoria geral. |
| `POST /projects/{project_id}/curation/queries` | Pesquisa artigos com `{"pergunta":"Como testar contratos HTTP?"}`. |

O POST aceita exclusivamente `pergunta` como string de 1 a 2.000 caracteres
após retirar espaços das extremidades. Entradas inválidas retornam 422. As duas
respostas têm `Cache-Control: no-store` e o mesmo formato:

```json
{
  "enabled": true,
  "artigos": [
    {
      "titulo": "Testes de contrato",
      "link": "https://example.org/contratos",
      "fonte": "Exemplo",
      "idioma": "pt",
      "data_publicacao": null
    }
  ],
  "total": 1,
  "categoria": "geral",
  "fontes_consultadas": [],
  "fontes_indisponiveis": [],
  "truncated": false
}
```

`total` conta os artigos recebidos antes do limite de 50 exibidos. Se houver
mais, `truncated` vale `true`. A consulta usa `geral` e listas de fontes
vazias quando o provedor omite esses metadados. `fonte`, `idioma` e
`data_publicacao` podem conter `null`. Links são URLs absolutas HTTP ou HTTPS,
sem credenciais ou caracteres de controle.

- 401 indica sessão inválida ou rejeição de autenticação pelo provedor. O cliente
  deve solicitar um novo login.
- 403 indica que o provedor recusou o acesso. Um projeto ausente ou inacessível
  retorna 404.
- 503 sinaliza desativação da consulta, indisponibilidade de uma dependência ou
  resposta externa inválida. Em caso de timeout, o provedor pode já ter
  registrado a consulta. Um novo envio depende de ação explícita do usuário.
- Com a integração desativada, o GET autorizado retorna `enabled: false`,
  `total: 0` e listas vazias. As duas rotas pulam a comunicação com o Módulo 5.

## Configuração e dados

`MODULE5_ENABLED` é `false` por padrão. A variável `MODULE5_BASE_URL` usa a
base HTTPS oficial. Um endereço HTTP loopback com porta explícita é aceito em
testes. O pipeline define essas variáveis somente no contêiner da API de
Projetos. Para ativar o recurso em um deploy, configure `MODULE5_ENABLED=true`
no ambiente de release.

O serviço chama `GET /feed` sem Bearer e `POST /consultas` com o Bearer do
usuário no cabeçalho `Authorization` e somente `pergunta` no corpo. Cookies,
dados do projeto e identificadores de chat ficam fora da requisição. Projetos
encerra a leitura do banco antes da rede e revalida JWT, sessão e permissão
antes de devolver o resultado. A operação preserva versão e histórico do
projeto e usa a observação de acesso existente.

A chamada externa tem limites de 5 segundos para conexão, 55 segundos entre
leituras e 60 segundos para a requisição. A resposta deve ser JSON finito
sem compressão, com até 1 MiB e até 1.000 artigos válidos. A API rejeita
redirecionamentos, ignora configurações de proxy do ambiente e realiza uma
única tentativa por chamada.

Os testes automatizados usam HTTP loopback com respostas controladas e SQLite
isolado. Uma verificação com a API do Módulo 5 em 18/11/2026 confirmou aceitação
do Bearer do Módulo 1 e retorno de artigos para uma pergunta sintética.
