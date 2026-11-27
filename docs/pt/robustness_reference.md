# Referência de robustez

A robustez é opcional e definida pelo dataset. Se `schema["robustness"]["enabled"]` estiver ausente ou for `false`, o `CityLearnEnv` comporta-se como antes.

Versão em inglês: [../robustness_reference.md](../robustness_reference.md).

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

`events_file` pode ser CSV ou Parquet e é resolvido a partir da raiz do dataset.

## Ficheiro de eventos

| Coluna | Significado |
|---|---|
| `event_id` | Identificador estável do evento, usado nos metadados e nas auditorias. |
| `module` | `observation`, `forecast`, `action` ou `asset`. |
| `target_type` | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | ID/nome da entidade, ou `*` para os alvos compatíveis. |
| `target_feature` | Nome da variável/ação. Para ativos, use `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | Janela inclusiva de passos de tempo globais. |
| `mode` | Modo de perturbação específico do módulo. |
| `value`, `std`, `min_value`, `max_value` | Parâmetros opcionais do modo. |
| `replacement_value` | Valor sentinela para valores em falta/telemetria; por omissão, `missing_replacement_value`. |
| `delay_steps` | Horizonte de atraso da ação; por omissão, `1`. |

## Modos

| Módulo | Modos |
|---|---|
| observation/forecast | `missing`, `noise`, `bias`, `stuck`, `clip` |
| action | `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip` |
| asset | `unavailable` |

A corrupção de observações e previsões afeta apenas o que o agente vê. As recompensas, os KPIs físicos e a liquidação da resposta à procura continuam a usar o estado real do simulador. Os eventos de ação e de controlo de ativos alteram a ação efetivamente aplicada, pelo que podem alterar a física e os KPIs normais.

As políticas de referência em `citylearn.agents.baseline` leem observações entity nas duas interfaces. Na interface flat, `predict(observations)` aplica os eventos de observação do passo a essas observações entity, tal como faz a interface entity, pelo que uma política de referência usada como controlador toma as mesmas ações nas duas interfaces. Isto não consome nenhum fluxo aleatório (o ruído é função de `random_seed`, do evento, do passo e do alvo), não regista nada no histórico nem nos KPIs de robustez e deixa as observações flat inalteradas. A referência business-as-usual nativa de `evaluate_v2()` chama `predict([])` e lê observações sem corrupção.

Uma ação de escada rolante (só na interface flat) é um alvo `building` cujo `target_feature` é o nome da ação, `escalator_<id>`; um evento `action` sobre ele altera o estado pedido a essa escada rolante.

Um sistema FV não tem ação. Um evento `asset` com alvo `pv` e `target_feature` `control` ou `both` coloca o sistema fora de serviço: não produz nada durante o evento, pelo que o consumo líquido, o custo, as emissões, a proveniência da energia e os KPIs FV usam produção nula nesses passos. A referência business-as-usual vê a mesma falha. Só com `telemetry`, o sistema FV continua a produzir e apenas as suas observações ficam ocultas.

## Diagnóstico entity

Ative o bundle de diagnóstico quando usar observações entity:

```json
"observation_bundles": {
  "entity_robustness": {"active": true}
}
```

Isto acrescenta variáveis de distrito para o estado ativo, as contagens de corrupções do passo anterior e as falhas de ativos em curso. Também são expostos metadados leves em `observations["meta"]["robustness"]`.

## KPIs

Quando a robustez está ativa, `evaluate_v2()` acrescenta contadores de distrito/edifício para o número de eventos, os passos de tempo ativos, as corrupções de observações/previsões/ações, as aplicações de indisponibilidade de ativos, as observações em falta e as ações descartadas (dropouts).

Em `MultiCommunityEnv`, a robustez mantém-se independente em cada comunidade filha. As linhas de portefólio agregam os KPIs de robustez `_count` da mesma forma que os outros KPIs de contagem.
