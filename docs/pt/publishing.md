# Publicar o CityLearn

O pacote e o módulo Python chamam-se `citylearn`.
O responsável pela manutenção é [Tiago Fonseca](https://github.com/calofonseca).
Versão inglesa: [Publishing CityLearn](../publishing.md).

## Preparar a versão

1. Atualizar a versão em `citylearn/__init__.py`. O `pyproject.toml` contém os
   restantes metadados do pacote e lê a versão desse ficheiro e as dependências
   de `requirements.txt`.
2. Acrescentar às [notas da versão](releases.md) as alterações para utilizadores,
   compatibilidade, impacto nos dados, validação e instruções de migração.
3. Atualizar os guias afetados e as [instruções de migração](migration.md).
4. Executar os testes e auditores do [guia de desenvolvimento](developer_guide.md).
   Construir também o site Sphinx e verificar ligações e exemplos.
5. Construir e verificar o wheel e o arquivo de código, incluindo uma instalação
   isolada fora do repositório e a verificação dos exports.

```console
python -m build
python -m twine check dist/*
```

Guardar os relatórios de execução nos artefactos do CI ou da versão. As medições
devem identificar a referência, os dados, as repetições, as unidades e os limites.
Mover as versões antigas para o [arquivo](releases_archive.md), preservando a
evidência de validação.

## CI, publicação do pacote e documentação da versão

1. Criar o commit com a identidade do mantenedor, fazer um único push e aguardar pelo
   CI.
2. Criar a tag `vX.Y.Z` no commit aprovado e enviá-la (`git push origin vX.Y.Z`).
   - **Publicação no PyPI:** O push da tag, por si só, não publica no PyPI. O
     [workflow de publicação](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/pypi_deploy.yml)
     é acionado pela publicação de uma GitHub Release ou por execução manual; escolher
     um único acionamento por versão. Confirmar que a construção, a verificação dos
     exports instalados e a publicação passaram para o commit pretendido, e instalar a
     versão exata do PyPI num ambiente limpo.
   - **Publicação da documentação (automática no push da tag):** O envio da tag
     `vX.Y.Z` aciona automaticamente o
     [workflow do Sphinx](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/sphinx.yml),
     que constrói a documentação dessa tag, publica `/X.Y.Z/`, atualiza
     `/versions.json` e, quando se trata da versão final mais recente (sem sufixo
     `a`/`b`/`rc`), atualiza também `/stable/` e a raiz `/`.
   - **Repetir uma construção falhada ou em falta:** Abrir **Actions -> Sphinx build ->
     Run workflow** no ramo `master` e indicar a tag exata em `tag` (por exemplo
     `v3.6.0`). A repetição é idempotente e substitui `/X.Y.Z/` (bem como `/stable/` e
     `/` se for a última versão final).
   - **Lista de verificação da documentação após o lançamento:**
     1. Confirmar que os jobs `build` e `deploy` do workflow `Sphinx build` passaram
        para `vX.Y.Z`.
     2. Abrir `https://www.citylearn.net/X.Y.Z/` e confirmar que o aviso de versão e a
        secção **Other versions** na barra lateral esquerda indicam `X.Y.Z` como a
        versão atual (`(current)`).
     3. Abrir `https://www.citylearn.net/versions.json` e confirmar que `X.Y.Z` consta
        da lista e surge tanto no seletor superior como em **Other versions**.
     4. Para uma **versão final**, abrir `https://www.citylearn.net/` e
        `https://www.citylearn.net/stable/` e confirmar que ambos servem `CityLearn X.Y.Z`
        (`stable (X.Y.Z)`), mantendo `https://www.citylearn.net/dev/` para `master`.

As credenciais configuradas no ambiente `pypi` não devem ser copiadas para a
documentação. O job de publicação aceita dois modos de credenciais: os segredos
`PYPI_USERNAME` e `PYPI_PASSWORD` com `twine` (modo atual) ou a publicação confiável
(OIDC), preparada mas desligada. Para a ligar, configurar no PyPI um publicador
confiável para o projeto `citylearn` (dono `citylearn-project`, repositório
`CityLearn`, workflow `pypi_deploy.yml`, ambiente `pypi`) e definir a variável do
repositório `PYPI_TRUSTED_PUBLISHING=true`; depois de uma versão publicada com sucesso,
apagar os dois segredos.

## Site da documentação

O [workflow do Sphinx](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/sphinx.yml)
publica no GitHub Pages (ramo `gh-pages`, domínio próprio do segredo `CUSTOM_DOMAIN`):

| URL | Conteúdo | Construído quando |
|---|---|---|
| `/` | Última versão final (`stable`). A ligação pública Documentation, a página inicial e as ligações existentes para páginas partilhadas abrem a última versão estável por omissão; os URLs na raiz que existem apenas em `master` redirecionam explicitamente para `/dev/<página>`. | Em conjunto com a última versão final (push de tag `v*` ou execução manual), com atualização dos redirecionamentos `/dev/` em cada push para `master`. |
| `/stable/` | Alias explícito da última versão final (não pré-lançamento). | Em conjunto com essa versão. |
| `/<versão>/` (por exemplo `/3.6.0/`) | Documentação fixa da tag `v<versão>`. | Ao enviar uma tag `v*` ou ao executar o workflow manualmente com `tag=v<versão>`. |
| `/dev/` | Documentação de desenvolvimento (`master`, inclui alterações `Unreleased`). | Em cada push para `master`. |
| `/versions.json` | Versões publicadas, lidas pelo seletor superior e pela secção **Other versions** na barra lateral. | Em cada publicação de `master` ou de uma versão. |

Cada página inclui um seletor no topo e uma secção **Other versions** na barra lateral esquerda
(`docs/source/_static/version_switcher.js`, `docs/source/_templates/layout.html`), alimentados por
`/versions.json`. Ao mudar de versão, abre-se a página equivalente nessa versão se existir (`HTTP HEAD`), ou a
página inicial dessa versão caso a página não exista nela.

### Tags iniciais no lançamento do esquema

Aquando da entrada em produção em `master`, aguardar pela conclusão da execução automática em `master` (para que
`/dev/` fique publicado) e depois executar manualmente **Actions -> Sphinx build -> Run workflow** a partir de
`master`, publicando **primeiro a versão final mais recente** e preenchendo depois as versões anteriores uma de cada
vez:

1. Executar `v3.6.0` **primeiro** e aguardar que os jobs `build` e `deploy` terminem com sucesso. Esta execução
   publica `/3.6.0/`, `/stable/` e a raiz `/`, cria redirecionamentos explícitos para `/dev/<página>` nos URLs da
   raiz ausentes da `3.6.0` e regista `3.6.0` como `stable` em `/versions.json`.
2. Executar `v3.5.0` e aguardar pela conclusão de `build` e `deploy`. Publica `/3.5.0/`, mantendo `/` e `/stable/` a
   servir `3.6.0`.
3. Executar `v3.4.0` e aguardar pela conclusão de `build` e `deploy`. Publica `/3.4.0/`, mantendo `/` e `/stable/` a
   servir `3.6.0`.

Publicar `v3.6.0` primeiro garante que `versions.json` já contém `3.6.0` antes do envio das versões históricas,
evitando que uma tag anterior seja marcada temporariamente como `stable`. As tags `v3.0.0` a `v3.3.1` podem também
ser publicadas uma a uma se necessário. Antes de preparar o site, `scripts/ci/prepare_docs_site.py --probe-remote`
distingue uma primeira publicação verificada de uma falha de leitura de `gh-pages` (abortando de imediato em caso de
erro), serve diretamente as páginas de `stable/` na raiz `/` e redireciona para `/dev/<página>` as páginas HTML
presentes em `/dev/` e ausentes de `stable/` (preservando páginas existentes na raiz até `/dev/` estar publicado). Com
`concurrency: documentation-deploy`, o GitHub mantém uma publicação em curso e uma em fila, cancelando a publicação
pendente anterior quando entra uma terceira execução; qualquer publicação de lançamento ou preenchimento cancelada
desta forma deve ser novamente executada manualmente para não ficar em falta. O ambiente `github-pages` em
Settings -> Environments deve permitir publicações a partir de `master` e das tags `v*`.

## Política de versões

| Tipo | Utilização |
|---|---|
| Patch | Correções compatíveis, documentação e pequenas adições. |
| Minor | Nova capacidade substancial ou alteração de schema/API. |
| Major | Alterações incompatíveis abrangentes. |
