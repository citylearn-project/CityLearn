# Guia de Desenvolvimento

Esta pagina junta comandos de desenvolvimento local, validacao, smoke tests de performance e o mapa atual da arquitetura interna.

Versao inglesa: [../developer_guide.md](../developer_guide.md).

## Ambiente Local

Usar o virtual environment do repositorio quando existir:

```console
.venv/bin/pip install -e .
```

Dependencias opcionais:

| Funcionalidade | Comando |
|---|---|
| Datasets Parquet | `.venv/bin/pip install pyarrow` |
| PV autosizing | `.venv/bin/pip install ".[pysam]"` |
| Checks de build | `.venv/bin/pip install build twine` |

## Validacao Principal

| Check | Comando |
|---|---|
| Suite completa | `.venv/bin/pytest -q` |
| Lint critico | `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821` |
| Auditoria entity contract | `.venv/bin/python scripts/audit/audit_entity_contract.py --strict` |
| Auditoria fisica | `.venv/bin/python scripts/audit/audit_physics.py` |
| Whitespace diff | `git diff --check` |

A auditoria fisica exercita de proposito caminhos de conversao de resolucao, por isso podem aparecer avisos de unit conversion quando a fixture força diferencas entre dataset e schema.

## Scripts Manuais

Scripts utilitarios vivem em `scripts/manual` e estao excluidos da colecao default do pytest.

```console
.venv/bin/python scripts/manual/demo_ev_rbc.py
.venv/bin/python scripts/manual/demo_ev_rbc_export_end.py
```

Benchmark de runtime:

```console
.venv/bin/python scripts/manual/bench_runtime.py --seconds 5 60 --render-modes none end --episode-steps 1200
```

Smoke check de performance para CI:

```console
.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --baseline-file scripts/ci/perf_baseline.json
```

Profiling de componentes do `step`:

```console
.venv/bin/python scripts/audit/profile_step_breakdown.py --episode-steps 300 --seconds 60 --agent rbc --interface flat --render-mode none --no-write --table-limit 14
```

Profiling de lifecycle e KPI/BAU:

```console
.venv/bin/python scripts/audit/profile_lifecycle.py --episode-steps 300 --seconds 60 --skip-exports --no-write
```

Remover `--skip-exports` quando for preciso medir tambem os caminhos de export CSV.

Para diagnostico ad hoc, passar `debug_timing=True` ao `CityLearnEnv` e ler chaves do `info` como `apply_actions_time`, `reward_observations_time`, `next_observations_time`, `terminal_export_time` e `step_total_time`.

## Arquitetura Interna

As APIs publicas continuam centradas em `CityLearnEnv` e `Building`. A orquestracao interna esta separada em modulos de servico em `citylearn/internal`.

| Modulo | Responsabilidade |
|---|---|
| `loading.py` | Loading por schema e montagem dos buildings. |
| `runtime.py` | Runtime de episodios, `step`, parsing de acoes, progressao temporal e associacao EV/charger. |
| `building_ops.py` | Orquestracao de observacoes e acoes por building. |
| `kpi.py` | Pipeline de KPIs/avaliacao. |
| `entity_interface.py` | Tabelas entity, edges, action specs e bundles de observacao. |

## Regras de Desenvolvimento

| Regra | Motivo |
|---|---|
| Documentar mudancas de schema/API na mesma alteracao. | Algoritmos e datasets dependem de contratos explicitos. |
| Adicionar testes para fisica ou observacoes novas. | Sub-hourly e entity podem regredir sem falhas obvias. |
| Preferir observacoes aditivas em patch releases. | Evita quebrar algoritmos e wrappers ja treinados. |
| Correr auditorias antes de taggar. | Apanham drift de contrato fora dos unit tests normais. |

## Verificação e módulos internos na 3.1

O comando `python scripts/audit/run_full_audit.py --strict --output-dir /tmp/citylearn-audit`
verifica física, contrato de entidades, datasets oficiais e seis trajetórias de
referência com comandos fixos. Falhas, dependências ausentes e referências divergentes
produzem erro; a execução normal não reescreve snapshots. Auditorias de algoritmos
continuam opcionais e explícitas. As referências de teste usam casos temporários
pequenos e os fixtures existentes, sem incluir datasets do SoftCPS.

As fachadas públicas delegam em módulos internos de energia/equipamentos/serviço/
comunidade nos KPIs, observações/layout de entidades, componentes/inputs no loading
e contratos/auditoria de robustez. O módulo de limites elétricos é partilhado pelo
controlo e pelo runtime. Importações públicas, exemplos e catálogo mantêm a
identidade CityLearn; estes módulos internos não são APIs de extensão estáveis.
