# Publicar o CityLearn

O pacote e o módulo Python chamam-se `citylearn`.
O responsável pela manutenção é [Tiago Fonseca](https://github.com/calofonseca).
Versão inglesa: [Publishing CityLearn](../publishing.md).

## Preparar a versão

1. Atualizar a versão em `citylearn/__init__.py`.
2. Acrescentar às [notas da versão](releases.md) as alterações para utilizadores,
   compatibilidade, impacto nos dados, validação e instruções de migração.
3. Atualizar os guias afetados e as [instruções de migração](../migration.md).
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

## CI e publicação

Criar o commit com a identidade do mantenedor, fazer um único push e aguardar pelo
CI. A tag `vX.Y.Z` deve apontar para o commit aprovado.

O [workflow de publicação](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/pypi_deploy.yml) é acionado pela
publicação de uma GitHub Release ou por execução manual. Escolher um único
acionamento por versão; o push da tag, por si só, não publica no PyPI.

Confirmar que a construção, a verificação dos exports instalados e a publicação
passaram para o commit pretendido. Instalar depois a versão exata do PyPI num
ambiente limpo e verificar o pacote. As credenciais configuradas no ambiente
`pypi` não devem ser copiadas para a documentação.

## Política de versões

| Tipo | Utilização |
|---|---|
| Patch | Correções compatíveis, documentação e pequenas adições. |
| Minor | Nova capacidade substancial ou alteração de schema/API. |
| Major | Alterações incompatíveis abrangentes. |
