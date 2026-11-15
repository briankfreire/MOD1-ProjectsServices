# Gemini no serviço de Projetos

A versão 0.6.0 publicada oferece Gemini como infraestrutura das cinco
recomendações existentes. O frontend continua usando as APIs; a chave existe
somente no ambiente privado do backend. Nenhuma configuração real ou segredo
faz parte desta documentação ou dos testes.

| Variável | Padrão / comportamento |
| --- | --- |
| `AI_PROVIDER` | `structured-http`; selecionar `gemini` explicitamente |
| `GEMINI_API_KEY` | Segredo obrigatório para gerar com Gemini |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_TIMEOUT_SECONDS` | `30`, intervalo 1–30 segundos |
| `GEMINI_MAX_OUTPUT_TOKENS` | `4096`, intervalo 256–8192 |
| `GEMINI_API_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` |
| `AI_SIMULATED` | Deve ser `false` com Gemini |

Sem configuração explícita, `structured-http` mantém a semântica de
`AI_BASE_URL`, `AI_MODEL` e `AI_API_KEY`; se a URL não estiver configurada,
geração retorna 503 sem chamada externa. Gemini usa somente suas variáveis e
expõe `provider=gemini`, o modelo configurado e `simulated=false`. O aplicativo
não altera faturamento nem garante gratuidade: quotas/cobrança dependem do
projeto e chave do provedor. Não habilite uma chave com dados reais nesta etapa local.

O adaptador chama `POST /models/{model}:generateContent` com chave somente em
`x-goog-api-key`. Usa `systemInstruction` em português, contexto JSON em
`contents` e `generationConfig.responseFormat.text` com
`mimeType=APPLICATION_JSON` e schema tipado. Não envia Bearer do usuário,
ferramentas, pesquisa ou chave em URL. Não segue redirects, consulta proxies
implícitos, repete requisições ou troca de modelo após falha. O host permitido
é o oficial HTTPS, sem porta alternativa. HTTP loopback é a única alternativa
para simulação local; userinfo, query, fragmento e traversal são rejeitados.
Headers, cookies, autenticação e parâmetros padrão de um cliente HTTP injetado
não são herdados pela requisição Gemini. Portas inválidas são rejeitadas na configuração.

Contexto tem limite de 128 KiB, resposta de 256 KiB; permanecem os limites
de domínio de 50 sugestões/evidências. Exige um único candidato com
`finishReason=STOP`, sem bloqueio ou function call. Textos `thought=true` não
compõem a resposta final. Quota 429, 5xx, timeout, truncamento, JSON inválido
e saídas fora do schema geram 503 sanitizado sem persistir recomendações.
Bloqueios de `safetyRatings` são rejeitados mesmo com STOP; `thought` exige
tipo booleano. JSON com constantes não finitas ou profundidade excessiva é rejeitado.
Contexto acima do limite retorna 422 antes da chamada; não há gravação parcial.

| Tipo | Sugestões permitidas |
| --- | --- |
| `roles` | `user_id` opt-in e `roles` do catálogo autorizado; proprietário protegido |
| `access_revocation` | `user_id` da janela de inatividade observada e `reason` |
| `teams` | `team_id` existente e `roles`, ou `name`, `user_ids` opt-in e `roles` |
| `skills_map` | `skill` conhecida, `user_ids` opt-in e `gap` booleano |
| `training` | `user_id` opt-in e `topics` sem URLs |

Contexto textual é dado não confiável, nunca instrução. A aplicação confere
IDs, evidências e consentimento no servidor, preservando limites de acesso,
menor privilégio, custos desconhecidos e ausência de evidência de atividade.
Geração não altera permissões. Aprovação humana mantém rechecagem de contexto,
permissões, transação e idempotência. Sem inatividade observada, o fluxo de
revogação continua retornando 409 antes de solicitar geração.

`summary`, `justification` e evidências autorizadas continuam obrigatórios.
`suggestions=[]` representa ausência de ação fundamentada em qualquer schema.
Uma proposta vazia é persistida como pendente, pode ser consultada/rejeitada,
e aprovação retorna 409 sem alterações de acesso ou notificações.

Validação local: `python -m pytest`, `python -m ruff check src tests`,
`python -m ruff format --check src tests` e `python -m mypy`. Os testes
`tests/test_gemini.py` usam exclusivamente chaves/dados sintéticos, transporte
controlado e HTTP loopback; não confirmam qualidade do modelo, quota ou chamada
Gemini real. A rodada de 03/11 foi controlada; a verificação autorizada posterior
está registrada abaixo. Não houve push, merge ou deploy.

Evidência em 03/11/2026: suíte completa com 271 aprovados e 11 pulados
(10 dependem de PostgreSQL loopback descartável e um de `BACKLOG_SERVICE_PATH`).
Os 70 casos Gemini passaram; Ruff, verificação de formato e mypy (25 módulos)
passaram. Metadados da instalação local e OpenAPI conferidos como 0.6.0.

## Compatibilidade e chamadas reais — 14/11/2026

O adaptador envia uma cópia do schema sem `maxItems` nos arrays, inclusive em
definições e alternativas de equipes. Esse ajuste evita o HTTP 400 observado com
o schema limitado de Identidade. Tipos, campos obrigatórios, enums, mínimos e
limites de texto são preservados; os modelos Pydantic originais continuam
recusando respostas acima dos limites. Os 86 testes Gemini passaram, incluindo
evidências no limite de 50 e acima dele e papéis aninhados acima do máximo.
As cinco regressões de requisição falharam antes da correção e passaram depois.

Os cinco tipos (`roles`, `access_revocation`, `teams`, `skills_map`, `training`)
obtiveram HTTP 200 no endpoint oficial com `gemini-3.5-flash-lite`, usando contexto
sintético sem candidatos elegíveis. As propostas vieram vazias e com evidências
autorizadas. `roles` recebeu primeiro HTTP 503 do Google; uma repetição manual
limitada passou, sem adicionar retries ao produto. Nenhum banco ou permissão
foi alterado. Isso não valida todas as US de IA nem a disponibilidade futura.

Contrato oficial de referência: [generateContent](https://ai.google.dev/api/generate-content),
[modelo](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) e
[preços e quotas](https://ai.google.dev/gemini-api/docs/pricing).

## Configuração de produção — 15/11/2026

A versão publicada está configurada com `AI_PROVIDER=gemini`,
`AI_SIMULATED=false` e `GEMINI_MODEL=gemini-3.5-flash-lite`. A chave fica somente
nos segredos do backend. Chamadas reais dos sete tipos, somando Identidade,
Projetos e Backlog, retornaram HTTP 200 com contexto sintético autorizado.
Essa evidência do transporte é separada da validação completa dos fluxos pelo
navegador e da qualidade de cada cenário. Veja [a entrega publicada](final-delivery.md).
