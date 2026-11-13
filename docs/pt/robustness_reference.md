# Referencia de Robustez

Robustez e opcional e orientada por dataset. Se `schema["robustness"]["enabled"]` estiver ausente ou `false`, o `CityLearnEnv` comporta-se como antes.

Versao inglesa: [../robustness_reference.md](../robustness_reference.md).

## Schema

```json
"robustness": {
  "enabled": true,
  "events_file": "robustness_events.csv",
  "random_seed": 0,
  "missing_replacement_value": -9999.0,
  "modules": {
    "observations": {"enabled": true},
    "forecasts": {"enabled": true},
    "actions": {"enabled": true},
    "assets": {"enabled": true}
  }
}
```

`events_file` pode ser CSV ou Parquet e e resolvido a partir da root do dataset.

## Ficheiro de Eventos

| Coluna | Significado |
|---|---|
| `event_id` | ID estavel usado em metadata e auditoria. |
| `module` | `observation`, `forecast`, `action` ou `asset`. |
| `target_type` | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | ID/nome da entidade, ou `*` para targets compativeis. |
| `target_feature` | Nome da feature/acao. Para assets usa `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | Janela inclusiva em timesteps globais. |
| `mode` | Modo de perturbacao dependente do modulo. |
| `value`, `std`, `min_value`, `max_value` | Parametros opcionais do modo. |
| `replacement_value` | Sentinela para missing/telemetry; default `missing_replacement_value`. |
| `delay_steps` | Atraso de acao; default `1`. |

## Modos

| Modulo | Modos |
|---|---|
| observation/forecast | `missing`, `noise`, `bias`, `stuck`, `clip` |
| action | `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip` |
| asset | `unavailable` |

Corrupcao de observations e forecasts afeta apenas o que o agente ve. Rewards, KPIs fisicos e settlement de demand response continuam a usar o estado real do simulador. Eventos de action e asset-control alteram a acao efetivamente aplicada, portanto podem alterar a fisica e KPIs normais.

Um sistema PV nao tem acao. Um evento `asset` com target `pv` e `target_feature` `control` ou `both` coloca o PV fora de servico: nao gera energia durante o evento, pelo que consumo liquido, custo, emissoes, provenance de energia e KPIs de PV usam geracao zero nesses timesteps. A referencia business-as-usual ve a mesma falha. Com `telemetry` apenas, o PV continua a gerar e so as suas observacoes ficam ocultas.

## Diagnostico Entity

Ativar o bundle de diagnostico quando se usa entity observations:

```json
"observation_bundles": {
  "entity_robustness": {"active": true}
}
```

Isto adiciona features na tabela `district` para estado ativo, contagens do step anterior e outages de assets ativos. Metadata leve tambem fica em `observations["meta"]["robustness"]`.

## KPIs

Quando robustez esta ativa, `evaluate_v2()` adiciona contadores district/building para eventos, timesteps ativos, corrupcoes de observation/forecast/action, assets indisponiveis, observations missing e action dropouts.

Em `MultiCommunityEnv`, a robustez continua independente por comunidade filha. Linhas de portfolio agregam KPIs de robustez com sufixo `_count` como os restantes KPIs de contagem.
