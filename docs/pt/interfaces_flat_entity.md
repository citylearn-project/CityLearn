# Interfaces: Flat e Entity

O simulador suporta dois contratos de I/O: `flat` para compatibilidade Gymnasium/RL classico e `entity` para ORL, GraphRL, Transformers e topologia dinamica.

## Comparacao Rapida

| Tema | Flat | Entity |
|---|---|---|
| Observacao | Lista de vetores por agente/building, ou vetor unico central. | Dict com tabelas por entidade e edges relacionais. |
| Acao | Lista/array na ordem de `env.action_names`. | Dict com tabelas de acao ou payload map por ID canonico. |
| Melhor para | RBC, MARL classico, wrappers existentes, SB3. | GNNs, transformers, policies com input dinamico, topology dynamic. |
| Topologia dinamica | Nao suportada. | Suportada. |
| IDs estaveis | Indireto pela ordem dos vetores. | Explicito em `env.entity_specs`. |
| Duplicacao EV/charger | Expandida em nomes flat. | Tabelas separadas e edges `charger_to_ev_*`. |

## Flat Mode

Ativacao:

```python
env = CityLearnEnv(schema, interface="flat")
```

ou omitir `interface`.

### Observacoes Flat

Com `central_agent=False`:

```python
observations = [
    [obs_building_1_feature_1, obs_building_1_feature_2, ...],
    [obs_building_2_feature_1, obs_building_2_feature_2, ...],
]
```

Com `central_agent=True`:

```python
observations = [[all_active_features_for_all_buildings]]
```

`shared_observations` entram apenas uma vez no vetor central para evitar repeticao de weather/pricing/calendario.

### Acoes Flat

Com `central_agent=False`:

```python
actions = [
    [building_1_action_1, building_1_action_2],
    [building_2_action_1, building_2_action_2],
]
```

Com `central_agent=True`:

```python
actions = [[all_building_actions_concatenated]]
```

A ordem exata vem de:

```python
env.action_names
env.observation_names
```

## Entity Mode

Ativacao:

```python
env = CityLearnEnv(schema, interface="entity")
```

Para topologia dinamica:

```python
env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic")
```

### Observacao Entity

`env.reset()` e `env.step()` retornam:

```python
{
  "tables": {
    "district": np.ndarray,
    "building": np.ndarray,
    "charger": np.ndarray,
    "ev": np.ndarray,
    "storage": np.ndarray,
    "pv": np.ndarray,
    "deferrable_appliance": np.ndarray
  },
  "edges": {
    "district_to_building": np.ndarray,
    "building_to_charger": np.ndarray,
    "building_to_storage": np.ndarray,
    "building_to_pv": np.ndarray,
    "building_to_deferrable_appliance": np.ndarray,
    "charger_to_ev_connected": np.ndarray,
    "charger_to_ev_connected_mask": np.ndarray,
    "charger_to_ev_incoming": np.ndarray,
    "charger_to_ev_incoming_mask": np.ndarray
  },
  "meta": {
    "time_step": int,
    "endogenous_time_step": int,
    "spec_version": "entity_v1",
    "topology_version": int
  }
}
```

### `entity_specs`

`env.entity_specs` e a fonte oficial para interpretar rows/columns:

```python
specs = env.entity_specs
building_features = specs["tables"]["building"]["features"]
charger_ids = specs["tables"]["charger"]["ids"]
charger_units = specs["tables"]["charger"]["units"]
```

Cada tabela contem:

| Campo | O que contem |
|---|---|
| `ids` | IDs canonicos estaveis das rows. |
| `features` | Nome das colunas. |
| `units` | Unidade inferida. |
| `feature_metadata` | Bundle, unidade e flag legacy por feature. |

### Semantica Temporal

| Campo | Semantica |
|---|---|
| Exogenous observations | Lidas no timestep `t`. Exemplos: weather, pricing, schedules. |
| Endogenous observations | Lidas em `t-1` settled. Exemplos: consumo aplicado no ultimo step, SOC depois da acao anterior. |
| Observacao terminal | Mesma regra no `t` final: features exogenas e de calendario da ultima linha de dados, endogenas do ultimo intervalo executado. As series dos buildings continuam a ter apenas intervalos executados. Os estados de chargers, deferrable appliances e escalators nao avancam e ficam no ultimo intervalo executado. |
| Topology events | Eventos em `k` sao aplicados depois da transicao `k-1 -> k` e antes da observacao `k`. |

Isto evita expor buffers ainda nao inicializados e torna a interface consistente para agentes online.

## Entity Bundles

| Bundle | Ativo por default | Tabelas afetadas | Uso |
|---|---:|---|---|
| `entity_base` | sim | charger, storage, deferrable | Capacidades essenciais, fases e deferrables. |
| `entity_core_electrical` | nao | building, charger, ev, storage, pv | Potencias, energias, eficiencia, SOC derivado, PV. |
| `entity_community_operational` | nao | district | Agregados community, headroom, topology counts. |
| `entity_forecasts_existing` | nao | district | Forecasts ja presentes no dataset. |
| `entity_temporal_derived` | nao | district, building | Lags e medias curtas. |

## Entity Actions

A forma recomendada e por tabelas:

```python
actions = {
    "tables": {
        "building": building_action_array,
        "charger": charger_action_array,
        "deferrable_appliance": deferrable_action_array
    }
}
```

Tambem podes enviar overrides por ID canonico:

```python
actions = {
    "map": {
        "building:Building_1": {"electrical_storage": 0.2},
        "charger:Building_1:AC001": {"electric_vehicle_storage": 0.5},
        "deferrable_appliance:Building_1:washer_1": {"start": 1.0}
    }
}
```

IDs sem prefixo tambem podem funcionar quando sao inequivocos, mas o formato com prefixo e o mais robusto para GraphRL/Transformers.

## Dynamic Topology

Quando `topology_mode="dynamic"`, as tabelas podem mudar de tamanho entre steps. O contrato para agentes e:

Em cada `reset()`, o ambiente restaura primeiro o pool de membros e a composicao estrutural de assets
carregada do schema e so depois aplica eventos agendados para o time step `0`. Chargers, aparelhos
diferiveis, sistemas PV, armazenamento eletrico e membros clonados em runtime nao transitam assim para
o episodio seguinte. Reutilizar o mesmo ambiente em varios episodios mantem a mesma timeline de eventos
que reconstruir o ambiente para cada episodio.

| Elemento | Como tratar |
|---|---|
| `ids` em `entity_specs` | Reconsultar quando `topology_version` muda. |
| Masks de EV | Usar `charger_to_ev_connected_mask` e `charger_to_ev_incoming_mask`. |
| Running stats | Manter estatisticas por feature, nao por row fixa. |
| Assets removidos | Ignorar IDs que sairam de `active_ids`. |
| Assets adicionados | Inicializar hidden state/memoria do modelo para novo ID. |
