# Validação e desempenho

Use esta página para escolher uma verificação e perceber o âmbito dos resultados
publicados. Para interpretar uma simulação comum, comece pelo
[scorecard](scorecard.md) e pela [referência de KPIs](kpis_reference.md).

Versão em inglês: [../validation.md](../validation.md).

## Executar verificações a partir do código-fonte

Instale as dependências de desenvolvimento como descrito no
[guia de desenvolvimento](developer_guide.md). Escreva os relatórios gerados numa
pasta de saída separada:

```console
python scripts/audit/run_full_audit.py --strict --output-dir /tmp/citylearn-audit
```

Esta verificação abrange cenários físicos, contratos de entidades, sondagens
limitadas dos datasets públicos e referências de regressão com comandos fixos.
Verificações falhadas ou em falta fazem falhar a verificação; uma execução comum
não regenera os resultados esperados.

| Investigar | Ferramenta |
|---|---|
| Física dos equipamentos e limites elétricos | `scripts/audit/audit_physics.py` |
| Tabelas de entidades, ações e topologia | `scripts/audit/audit_entity_contract.py` |
| Carregamento de datasets e execução limitada | `scripts/audit/audit_datasets.py` |
| Reconciliação independente de energia e de dinheiro | `scripts/audit/audit_balances.py` |
| Eixos temporais e reprodutibilidade | `scripts/audit/audit_temporal.py` |
| Execução contínua e uso de recursos | `scripts/audit/audit_long_run.py` (apenas Linux: lê o RSS de `/proc`) |
| Tempos dos componentes e da avaliação | Comandos de profiling no [guia de desenvolvimento](developer_guide.md#scripts-manuais-de-simulação) |

Use `--help` em cada script para ver as suas entradas e opções de saída. Os
datasets públicos ficam inalterados; as verificações predefinidas não precisam de
datasets de produção da SoftCPS.

## Validação publicada e melhorias medidas

As [notas da versão 3.1.0](releases.md#v310---2026-11-02) mantêm as alterações
funcionais, as contagens de validação, o protocolo de benchmark e os valores
medidos antes e depois. Distinguem a referência funcional corrigida da versão
original 3.0.2. As medições mais antigas ficam no
[arquivo de versões](releases_archive.md).

Os testes limitados e os benchmarks de integração não estabelecem a validação
anual de todos os datasets, o desempenho dos controladores nem a calibração com
equipamentos reais. A reprodução exige as mesmas entradas, parâmetros, ambiente
de execução e âmbito de validação. Consulte o [guia de migração](migration.md)
antes de comparar versões.
