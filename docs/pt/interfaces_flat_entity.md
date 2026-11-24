# Interfaces flat e entity

O CityLearn suporta dois contratos de I/O: `flat` para fluxos de trabalho clássicos de RL ao estilo Gymnasium e `entity` para ORL, GraphRL, Transformers e topologia dinâmica.

Versão em inglês: [../interfaces_flat_entity.md](../interfaces_flat_entity.md).

## Comparação rápida

| Tema | Flat | Entity |
|---|---|---|
| Observação | Lista de vetores por edifício ou um vetor central único. | Dicionário com tabelas de entidades e arestas relacionais. |
| Ação | Lista/array ordenada por `env.action_names`. | Dicionário com tabelas de ações ou um mapa indexado por ID. |
| Mais adequado para | RBC, MARL, wrappers, fluxos de trabalho ao estilo SB3. | GNN, transformers, redes com entrada/saída dinâmica. |
| Topologia dinâmica | Não suportada. | Suportada. |
| IDs estáveis | Implícitos na ordem do vetor. | Explícitos em `env.entity_specs`. |
| Relação VE/carregador | Nomes flat expandidos. | Tabelas separadas mais as arestas `charger_to_ev_*`. |

## Modo flat

```python
env = CityLearnEnv(schema, interface="flat")
```

Os wrappers de `citylearn.wrappers` (normalização, discretização, Stable
Baselines3 e RLlib) leem e devolvem estes vetores flat, por isso precisam de
`interface="flat"` e lançam um `ValueError` num ambiente entity. Os datasets
`pt_rec_*`, trifásicos, de resposta à procura e de robustez usam por omissão a
interface entity: passe `interface="flat"` para os usar com os wrappers. A
topologia dinâmica e a resposta à procura precisam da interface entity, por isso
os wrappers não podem ser usados com elas.

Com `central_agent=False`, as observações são um vetor por edifício:

```python
observations = [
    [building_1_feature_1, building_1_feature_2],
    [building_2_feature_1, building_2_feature_2],
]
```

Com `central_agent=True`, as observações são concatenadas num único vetor:

```python
observations = [[all_active_features_for_all_buildings]]
```

As `shared_observations` são incluídas uma só vez no vetor central, para evitar repetir as features de meteorologia, preço e calendário.

As ações flat seguem a mesma convenção:

```python
actions = [
    [building_1_action_1, building_1_action_2],
    [building_2_action_1, building_2_action_2],
]
```

A ordem exata está disponível em:

```python
env.observation_names
env.action_names
```

`env.observation_space` segue `env.observation_names` posição a posição. Cada edifício lista primeiro
as suas observações ao nível do edifício, na ordem de `active_observations`, e depois as observações
dos seus carregadores de VE, aparelhos diferíveis e escadas rolantes, agrupadas por equipamento
(`Building.flat_observation_order`). Normalize por posição com `observation_space.low` e `high`,
ou por nome com `observation_names`; ambos dão os mesmos limites.

## Modo entity

```python
env = CityLearnEnv(schema, interface="entity")
```

A topologia dinâmica exige o modo entity:

```python
env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic")
```

As observações entity têm esta estrutura:

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
    "topology_version": int,
    "runtime_status": {
      "version": "runtime_status_v1",
      "emits_health_state": false,
      "active_events": [],
      "asset_connections": [],
      "asset_availability": [],
      "sensor_channels": [],
      "actuator_channels": [],
      "communication_links": [],
      "value_quality": []
    }
  }
}
```

`env.observation_space` declara as três chaves. `meta` é um `EntityMetaSpace`: aceita qualquer
mapeamento com `time_step`, `endogenous_time_step`, `seconds_per_time_step` e `spec_version`, pelo que
`observation_space.contains(observations)` se verifica. Transporta contexto, não features, e não é
achatável (flattenable); passe a uma rede apenas `tables` e `edges`.

`runtime_status_v1` reporta factos do simulador, e não uma classificação de
saúde para uma política de RL. `fault_mode` é preservado como a causa original.
Em particular, um evento `stuck` não é rotulado automaticamente como
desatualizado (stale): o consumidor tem de derivar esse estado a partir da
atualidade, duração, tipo semântico e criticidade.

A ligação dos ativos, a disponibilidade dos ativos, o estado dos canais de
sensores, o estado dos canais de atuadores e o estado da comunicação
comunidade/nuvem são partes independentes do contrato. Um VE normalmente
desligado não é um carregador avariado.

## Limites das observações

`observation_space` declara um `low` e um `high` para cada observação, nas duas
interfaces. O ambiente não limita as observações a estes limites, pelo que uma
observação pode ficar fora de `observation_space`, e `observation_space.contains()`
e verificações como o `check_env` do Stable Baselines3 podem então assinalá-lo
([#357](https://github.com/citylearn-project/CityLearn/issues/357)).
O `NormalizedObservationWrapper` também não limita: aplica
`(x - low) / (high - low)`, pelo que as suas saídas podem sair de [0, 1]. Para
manter as observações dentro do espaço, acrescente o `ClippedObservationWrapper`
(interface flat):

```python
from citylearn.wrappers import ClippedObservationWrapper, NormalizedObservationWrapper

env = NormalizedObservationWrapper(ClippedObservationWrapper(env))
```

Onde o modelo não tem um limite rígido, os limites são estimativas que
`Building.estimate_observation_space_limits` calcula a partir das séries do
dataset na janela de simulação. Para as observações térmicas:

| Observação | Limite |
|---|---|
| `indoor_dry_bulb_temperature` | Intervalo da coluna `indoor_dry_bulb_temperature` do dataset, alargado de `maximum_temperature_delta` (20 °C por omissão) de cada lado. |
| `indoor_dry_bulb_temperature_heating_delta`, `indoor_dry_bulb_temperature_cooling_delta` | Fixo em ±`maximum_temperature_delta`, [−20, 20] por omissão. |
| Set points de aquecimento e de arrefecimento | Intervalo do horário do dataset. Nos edifícios com interação dos ocupantes, com a física da versão 2, alargado a `set_point_limits` (15–30 °C por omissão); os ocupantes nunca levam o set point para além desses limites, pelo que estes limites são exatos. |

Cada limite é depois alargado de `observation_space_limit_delta` (0 por omissão).

A temperatura interior dos edifícios LSTM depende da forma como o AVAC é usado,
pelo que ficar dentro destas estimativas depende do controlador. Nos dois bairros
do Quebec (20 edifícios, passos 0–2159, física da versão 2):

| Controlador | Temperatura interior | Delta de aquecimento | Set point |
|---|---|---|---|
| AVAC à procura do dataset: `BusinessAsUsualAgent` com `baseline_version=2` (predefinida), `RBCBasicPolicy`, `RBCSmartPolicy`, `RBCCommunityPolicy` | dentro, 17,0–26,5 °C face a [−1,1; 42,4] | dentro | dentro |
| AVAC sem funcionar: `BusinessAsUsualAgent` com `baseline_version=1`, as referências baseadas em regras com `hvac='off'`, `ZeroActionAgent` | abaixo de `low` em 38% dos passos-edifício, até 22,6 °C | abaixo de `low` em 89% dos passos-edifício, até 31,6 °C | dentro |
| Ações aleatórias | acima de `high` em 7% dos passos-edifício, até 20,7 °C | acima de `high` em 19% dos passos-edifício, até 27,3 °C | dentro |

Sem aquecimento, a temperatura interior desce em direção à temperatura exterior,
que neste período chega a −32,5 °C, pelo que o excesso fica do lado frio. As
ações aleatórias podem aquecer um edifício muito para além de qualquer valor do
dataset, pelo que o seu excesso fica do lado quente. Depois da normalização, a
temperatura interior de um edifício do Quebec sem aquecimento chega a cerca de
−0,47, e o seu delta de aquecimento a cerca de −0,79.

Os KPIs, as recompensas, o `evaluate()` e o `evaluate_v2()` leem o estado dos
edifícios, não o vetor de observações, pelo que não dependem destes limites. Os
datasets sem ações de AVAC não são afetados: num episódio completo em
`citylearn_challenge_2022_phase_all_plus_evs` e `pt_rec_4`, com o BAU, o
`RBCSmartPolicy` e ações aleatórias, nenhuma observação sai do espaço mais do que
o arredondamento a float32.

## `entity_specs`

`env.entity_specs` é o schema legível por máquina das tabelas, colunas, IDs, unidades, bundles e arestas:

```python
specs = env.entity_specs
building_features = specs["tables"]["building"]["features"]
charger_ids = specs["tables"]["charger"]["ids"]
charger_units = specs["tables"]["charger"]["units"]
```

| Campo | Conteúdo |
|---|---|
| `ids` | IDs canónicos estáveis das linhas. |
| `features` | Nomes das colunas. |
| `units` | Unidades inferidas. |
| `feature_metadata` | Unidade, bundle e indicador legacy por feature. |
| `actions` | IDs, colunas e unidades das tabelas de ações. |
| `edges` | Metadados das tabelas de origem/destino. |
| `topology` | IDs ativos, ciclo de vida e versão da topologia. |
| `runtime_status_contract` | Vocabulário de estado, valores predefinidos esparsos e a fronteira explícita sem estado de saúde. |
| `action_execution_contract` | Fases da ação: pedida, depois do canal, limitada e aplicada. |

## Semântica temporal

| Campo | Significado |
|---|---|
| Observações exógenas | Lidas no passo `t`. Exemplos: meteorologia, preços, horários. |
| Observações endógenas | Lidas em `t-1`, já liquidado. Exemplos: consumo anterior e SOC depois da última ação. |
| Observação terminal | A mesma regra no `t` final: features exógenas e de calendário da última linha de dados, endógenas do último intervalo executado. As séries dos edifícios continuam a conter apenas intervalos executados. Os estados dos carregadores, dos aparelhos diferíveis e das escadas rolantes não avançam e ficam no último intervalo executado. |
| Eventos de topologia | Os eventos em `k` são aplicados depois do intervalo `k-1` e antes da associação dos VE e da observação em `k`. |

## Bundles entity

| Bundle | Predefinição | Tabelas | Finalidade |
|---|---:|---|---|
| `entity_base` | sempre ativo | charger, storage, deferrable | Features estáticas e de serviço essenciais. |
| `entity_core_electrical` | desativado | building, charger, ev, storage, pv | Potência, energia por passo, eficiência, SOC derivado e FV. |
| `entity_community_operational` | desativado | district | Agregados, margem, contagens e versão da topologia. |
| `entity_forecasts_existing` | desativado | district | Previsões já presentes no dataset. |
| `entity_temporal_derived` | desativado | district, building | Desfasamentos curtos e médias móveis. |

## Ações entity

Payload por tabelas recomendado:

```python
actions = {
    "tables": {
        "building": building_action_array,
        "charger": charger_action_array,
        "deferrable_appliance": deferrable_action_array
    }
}
```

Também são suportadas substituições indexadas por ID:

```python
actions = {
    "map": {
        "building:Building_1": {"electrical_storage": 0.2},
        "charger:Building_1:AC001": {"electric_vehicle_storage": 0.5},
        "deferrable_appliance:Building_1:washer_1": {"start": 1.0}
    }
}
```

Use IDs com prefixo para integrações robustas com GraphRL e Transformers.

Depois de um passo em modo entity, `info["entity_action_execution"]` contém
entradas por ID estável com o comando pedido, o valor depois das perturbações
do canal, o valor limitado pelo equipamento e a potência fisicamente aplicada,
quando observável. As quantidades indisponíveis são `None`.
`info["topology_events_applied"]` identifica os eventos aplicados antes da
observação devolvida.

## Orientações para a topologia dinâmica

Em cada `reset()` com topologia dinâmica, o ambiente restaura primeiro o conjunto de membros e a
composição estrutural de ativos carregados do schema e depois aplica os eventos agendados para o
passo `0`. Os carregadores, aparelhos diferíveis, sistemas FV, armazenamento elétrico e membros
clonados em execução que tenham sido adicionados ou removidos não passam, por isso, para o episódio
seguinte. Reutilizar um ambiente em vários episódios de treino tem a mesma cronologia de eventos de
topologia que recriar o ambiente em cada episódio.

Quando uma bateria estacionária é adicionada ou recolocada em serviço, o SOC
inicial configurado define o stock de abertura. Um SOC inicial abaixo da
reserva de descarga mantém esse valor. A bateria pode carregar de imediato e
pode descarregar quando o seu SOC ultrapassar a reserva.

| Elemento | Orientação para o agente |
|---|---|
| `topology_version` | Volte a ler `entity_specs` quando mudar. |
| Máscaras de VE | Use `charger_to_ev_connected_mask` e `charger_to_ev_incoming_mask`. |
| Estatísticas acumuladas | Mantenha as estatísticas por feature, não por linha fixa. |
| Ativos removidos | Ignore os IDs que desaparecem de `active_ids`. |
| Ativos adicionados | Inicialize a memória/estado oculto do modelo para os novos IDs. |

Os IDs dos VE identificam os veículos independentemente dos seus carregadores.
Remover o último carregador que referencia um VE suspende a sua participação
na comunidade. O mesmo VE continua sujeito à perda em standby e ao modelo de
mobilidade fora da comunidade com semente enquanto está suspenso, sem
carregamento a partir da comunidade. Reinstalar um carregador traz de volta
esse VE com o SOC entretanto alterado. Um SOC de chegada válido do dataset é
um ajuste externo. Um VE do catálogo ativado pela primeira vez a meio do
episódio começa no SOC inicial configurado, e o seu stock de abertura entra na
contabilidade de energia quando se liga. O VE pode ligar-se a um carregador de
cada vez. As métricas de partida começam uma ligação induzida pela topologia
no SOC de abertura observado e contam as oportunidades de carregamento a
partir dessa ligação. As exportações dos carregadores mostram a ligação que
efetivamente ocorreu. Um veículo a chegar aparece como incoming até se ligar.
