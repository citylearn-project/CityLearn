# Referência de ações

As ações são normalizadas para o agente. O simulador converte-as em potência ou energia física usando a capacidade, a potência nominal, os limites dos ativos e `seconds_per_time_step`.

Versão em inglês: [../actions_reference.md](../actions_reference.md).

## Contrato geral

| Regra | Contrato |
|---|---|
| Limites | Lidos de `env.action_space` e `env.action_names`. Uma ação fora dos limites é cortada para eles; ver [Ações fora dos limites](#ações-fora-dos-limites). |
| Ações de armazenamento | Positivo carrega, negativo descarrega. |
| Ações de carregadores de VE | Positivo carrega o VE, negativo descarrega/V2G se estiver ativado. |
| Ações de aparelhos diferíveis | Comando binário de arranque. `action > trigger_threshold` tenta arrancar o próximo ciclo pendente (`trigger_threshold` predefinido: `0.5`). |
| Ações de escadas rolantes | Três estados: standby (`[0, 1/3[`), lento (`[1/3, 2/3[`) e normal (`[2/3, 1]`). |
| Energia interna | A energia aplicada por passo está em `kWh/step`. |
| Limites de potência | As potências nominais dos equipamentos e os limites de serviço estão em `kW`. |
| Restrições | As restrições do serviço de carregamento/elétrico podem cortar as ações antes da aplicação. |

## Ações flat

| Ação | Gama típica | Entidade | Efeito |
|---|---:|---|---|
| `cooling_or_heating_device` | `[-1, 1]` | building | Negativo controla o arrefecimento, positivo controla o aquecimento. Mutuamente exclusiva com ações separadas de arrefecimento/aquecimento. |
| `cooling_device` | `[0, 1]` | building | Controla a procura/setpoint de arrefecimento em edifícios dinâmicos. |
| `heating_device` | `[0, 1]` | building | Controla a procura/setpoint de aquecimento em edifícios dinâmicos. |
| `cooling_storage` | `[-limit, limit]` | building | Carrega/descarrega o armazenamento térmico de arrefecimento. |
| `heating_storage` | `[-limit, limit]` | building | Carrega/descarrega o armazenamento térmico de aquecimento. |
| `dhw_storage` | `[-limit, limit]` | building | Carrega/descarrega o armazenamento de água quente sanitária. |
| `electrical_storage` | `[-1, 1]` | building | Controla o BESS do edifício. |
| `electric_vehicle_storage_{charger_id}` | `[-1, 1]` ou `[0, 1]` | charger | Controla o VE ligado a um carregador. O limite negativo depende de `max_discharging_power`. |
| `deferrable_appliance_{appliance_id}` | `[0, 1]` | appliance | Comando binário de arranque (`0` desligado, `1` ligado) para o próximo ciclo viável. |
| `escalator_{escalator_id}` | `[0, 1]` | escalator | Seleciona o funcionamento em standby, lento ou normal. |

## Ações fora dos limites

As duas interfaces aplicam uma só regra a uma ação fora de `env.action_space`:
é cortada para o limite mais próximo antes de chegar ao equipamento. Vale para
os vetores de ações flat, para os vetores flat enviados a um ambiente entity e
para os payloads entity `tables` e `map`. Uma ação dentro dos limites é aplicada
tal como foi enviada, bit a bit. As ações `NaN` e infinitas não são cortadas:
`step()` rejeita-as com um `ValueError`. Com `physics_version=1` as ações flat
são aplicadas tal como são enviadas, como no CityLearn 3.6.0, e só as tabelas e
os mapas entity são cortados.

Por exemplo, com `cooling_storage` limitado a `[-0.25, 0.25]`, uma ação de
`0.75` carrega o depósito como `0.25`. Depois aplicam-se os limites do
equipamento (potência, capacidade, SOC) como habitualmente.

## Conversão física

Ação do BESS:

```text
energy_kwh_step = action * nominal_power_kw * seconds_per_time_step / 3600
```

Ação do carregador de VE:

```text
charge_energy_kwh_step = positive_action * max_charging_power_kw * seconds_per_time_step / 3600
discharge_energy_kwh_step = negative_action * max_discharging_power_kw * seconds_per_time_step / 3600
```

Depois da conversão, o ativo aplica o SOC, a capacidade, a eficiência, as curvas de potência e as restrições de serviço.

## Lógica de arranque dos aparelhos diferíveis

Um ciclo só arranca quando todas as condições se verificam:

| Condição | Regra |
|---|---|
| Ciclo pendente | Existe um ciclo com o estado `pending`. |
| Limiar da ação | `action > trigger_threshold` (predefinido `0.5`). |
| Janela de arranque | `earliest_start_time_step <= current_global_time_step <= latest_start_time_step`. |
| Prazo | `current + duration_steps - 1 <= deadline_time_step`. |
| Janela do episódio | O ciclo completo cabe dentro do episódio atual. |

Se o agente tentar tarde demais, o arranque é rejeitado. Se `latest_start_time_step` passar sem um arranque válido, o ciclo é marcado como falhado.

Recomendação para controladores: use `deferrable_appliance_can_start` como sinal de prontidão e envie `1.0` apenas quando pretender um arranque.

## Controlo das escadas rolantes

A ação de uma escada rolante só é contínua por compatibilidade com os agentes;
é discretizada em três estados de funcionamento. `standby` consome a potência
de standby e deixa por servir qualquer procura de passageiros acima de
`service_threshold_passengers`. Tanto `slow` como `normal` servem a procura
agregada. `available=0` força o standby. Este modelo não simula filas de
passageiros nem limites de capacidade.

## Ações entity

| Tabela | Feature | Corresponde a |
|---|---|---|
| `building` | nomes das ações do edifício | `cooling_storage`, `dhw_storage`, `electrical_storage`, etc. |
| `charger` | `electric_vehicle_storage` | Uma linha por carregador ativo. |
| `deferrable_appliance` | `start` | Uma linha por aparelho ativo. |

Payload por tabelas:

```python
actions = {
    "tables": {
        "building": [[0.0, 0.2, -0.1]],
        "charger": [[1.0], [0.0]],
        "deferrable_appliance": [[1.0]]
    }
}
```

Payload por mapa (as chaves são `<tipo>:<id>`, com os IDs listados em `env.entity_specs["actions"][<tipo>]["ids"]`;
os IDs de carregadores e equipamentos diferíveis são `<edifício>/<equipamento>`, aqui de `citylearn_challenge_2022_phase_all_plus_evs`):

```python
actions = {
    "map": {
        "building:Building_1": {"electrical_storage": 0.1},
        "charger:Building_1/charger_1_1": {"electric_vehicle_storage": 0.7},
        "deferrable_appliance:Building_1/deferrable_appliance_1": {"start": 1.0}
    }
}
```

## Ordem no passo

A ordem simplificada das ações do edifício é:

1. Resolver as ações ativas/inativas.
2. Aplicar as restrições de carregamento/elétricas aos VE e ao BESS.
3. Atualizar as procuras dinâmicas, quando aplicável.
4. Atualizar os equipamentos AVAC e o armazenamento térmico.
5. Atualizar a carga não deslocável.
6. Atualizar o BESS.
7. Atualizar os carregadores de VE.
8. Atualizar os aparelhos diferíveis.
9. Atualizar as escadas rolantes.
10. Atualizar o balanço líquido, as recompensas, os KPIs e as observações.

Quando `electrical_storage_action < 0`, a descarga do BESS tem prioridade sobre os outros consumos elétricos.

Durante um corte de energia, as ações dos carregadores de VE ficam limitadas ao abastecimento local, e uma ação negativa (descarga) é posta a zero, salvo se o `power_outage.vehicle_to_building` do edifício for `true`. Com essa opção, um VE ligado pode descarregar para o edifício. A descarga fica limitada à carga não deslocável mais a eletricidade de que os equipamentos de arrefecimento, aquecimento e AQS precisam para a procura que resta depois da descarga do armazenamento, menos a produção FV e a saída da bateria já disponíveis, pelo que nada é exportado para a rede em falha. É aplicada depois das descargas térmicas e da bateria e antes dessas cargas; os aparelhos diferíveis continuam a arrancar apenas com o abastecimento que essas cargas deixam.
