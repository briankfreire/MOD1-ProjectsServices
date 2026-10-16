# Projetos na Azure

A API usa um Azure Container App próprio com Neon. Os recursos compartilhados e os três apps são compostos pelo repositório de identidade. Siga o [passo a passo completo](https://github.com/Ckenz0/MOD1-IdentityService/blob/main/docs/deploy-azure.md) para assinatura, bootstrap, OIDC, segredos, imagens, APIs e frontend.

## Configuração deste serviço

- Imagem: `REGISTRY.azurecr.io/projects@sha256:DIGEST`; Dockerfile Linux/Python 3.12, usuário 10001, porta alvo 8001 e host 0.0.0.0.
- Neon: schema `projects`, papel runtime exclusivo com USAGE e SELECT/INSERT. Use conexão direta com `sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt`; confira o [README](../README.md) para preparação administrativa.
- Key Vault: segredo versionado `projects-database-url`. Não copie a chave RSA de identidade para este serviço.
- JWT: issuer igual à URL HTTPS estável da identidade, audience `engenharia-software-api` e JWKS em `URL_DA_IDENTIDADE/.well-known/jwks.json`.
- CORS: somente a origem HTTPS estável do frontend. Readiness consulta o banco próprio; liveness não depende de banco/JWKS.
- Escala inicial 0–1, 0,25 vCPU/0,5 GiB, sujeita a medição real de capacidade. Startup não cria tabelas.

## Publicar e atualizar

1. Integre as mudanças revisadas em main. No GitHub, crie Environment `demo`.
2. Configure Variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `ACR_NAME` e `AZURE_CONTAINER_APP=PREFIX-projects`.
3. Configure a credencial federada OIDC para o subject `repo:ORGANIZACAO/REPOSITORIO:environment:demo`. A identidade de CI recebe AcrPush e permissão de atualização somente deste app; a identidade runtime recebe AcrPull e leitura somente do seu segredo.
4. Execute Actions → Publish API to Azure em main, inicialmente sem `deploy_revision`. Anote o digest da imagem testada e publicada.
5. O operador aplica `apps.bicep` no repositório de identidade com esse digest, os outros serviços e as referências reais de Key Vault.
6. Nas próximas publicações, marque `deploy_revision` para atualizar o app existente. O workflow espera a revisão nova ficar pronta. Atualize também as referências guardadas na infraestrutura.

PRs executam `container-check.yml` sem credenciais cloud: lint, tipos, testes e build/smoke Docker com SQLite sintético. Um skip de PostgreSQL não comprova Neon. A compilação da infraestrutura não comprova deploy.

Após publicar, valide criar/listar/consultar projetos e a recusa de acesso por outra conta. Registre SHA, versão, digest, revisão e resultados sanitizados. Rollback usa o digest anterior, sem alterar banco, issuer ou chave do emissor. Custos de ACR/logs/segredos permanecem mesmo com API suspensa.
