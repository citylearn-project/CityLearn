# Contrato de unidades de dados

Este documento fixa o contrato de unidades esperado pelo simulador. O objetivo é evitar ambiguidades quando se usam datasets horários, datasets abaixo da hora ou dados reais que chegam originalmente como potência.

Versão em inglês: [../data_unit_contract.md](../data_unit_contract.md).

## Regra base

O motor físico contabiliza a energia por passo de simulação.

| Grandeza | Unidade |
|---|---|
| Colunas de energia das séries temporais | `kWh/step` |
| Potência nominal, limites, contratos e ações físicas de potência | `kW` |
| Capacidade de armazenamento | `kWh` |
| Estado de carga (`soc`) | fração em `[0, 1]` |
| Preços de energia | moeda por `kWh` |
| Intensidade carbónica | massa de CO2 por `kWh` |

O `seconds_per_time_step` do schema tem de representar a cadência física do dataset. Se a resolução do dataset e a do schema forem diferentes, o simulador aplica a conversão de compatibilidade e imprime um aviso explícito `[CityLearn][unit-conversion]`. Isto é suportado, mas o caminho preferido em produção é gerar o dataset na mesma resolução declarada pelo schema.

Com essa conversão, as séries de eletricidade simuladas ficam em kWh por passo de controlo. Isto inclui as referências `net_electricity_consumption_without_storage_and_partial_load*`: a eletricidade dos equipamentos para o aquecimento e arrefecimento extra da procura ideal (sem controlo) é convertida uma única vez de kWh por passo do dataset para kWh por passo de controlo, tal como a eletricidade dos equipamentos controlados.

## Séries temporais principais

| Campo | Unidade | Notas |
|---|---|---|
| `energy_simulation.non_shiftable_load` | `kWh/step` | Energia consumida no passo. |
| `energy_simulation.cooling_demand` | `kWh/step` | Procura térmica no passo. |
| `energy_simulation.heating_demand` | `kWh/step` | Procura térmica no passo. |
| `energy_simulation.dhw_demand` | `kWh/step` | Procura térmica no passo. |
| `energy_simulation.solar_generation` | perfil FV por kW instalado ou `kWh/step` | Depende de `pv.attributes.generation_mode`; consulte a secção FV. |
| `pricing.electricity_pricing` | moeda/`kWh` | Não é escalado pela duração do passo. |
| `carbon_intensity.carbon_intensity` | CO2/`kWh` | Não é escalado pela duração do passo. |
| `weather` | unidade física de cada variável | Temperatura, irradiância e humidade não são energia. |

## Equipamentos

| Elemento | Campo típico | Unidade |
|---|---|---|
| Bateria / armazenamento elétrico | `capacity` | `kWh` |
| Bateria / armazenamento elétrico | `nominal_power` | `kW` |
| Armazenamento térmico | `capacity` | `kWh` |
| Armazenamento térmico | `max_input_power`, `max_output_power` | `kW` |
| Bombas de calor, aquecedores, chillers | `nominal_power` | `kW` elétricos |
| FV | `nominal_power` | `kW` |
| Carregador de VE | `max_charging_power`, `max_discharging_power` | `kW` |
| Veículo elétrico | `capacity` da bateria | `kWh` |
| Aparelho diferível | `load_profile` do ciclo | `kWh/step` |
| Aparelho diferível | `total_energy_kwh` do ciclo | `kWh` |
| Limites de rede/fase/contrato | limites de potência | `kW` |

Qualquer limite em `kW` é convertido em energia por passo com:

```text
max_energy_kwh_step = limit_kw * seconds_per_time_step / 3600
```

## Conversão de dados reais

Quando a fonte real chega como potência, o conversor tem de produzir colunas de energia em `kWh/step` antes de gerar o dataset CityLearn.

```text
energy_kwh_step = mean_power_kw_over_step * seconds_per_time_step / 3600
```

Regras práticas:

| Fonte | Conversão |
|---|---|
| Séries de potência em `kW` | Agregue para a cadência do simulador com a média temporal e depois converta para `kWh/step`. |
| Leituras por intervalo já em `kWh` | Some os intervalos que pertencem ao passo de simulação. |
| Contadores acumulados em `kWh` | Calcule a diferença entre leituras consecutivas e depois agregue. |
| Preços e emissões | Alinhe ou propague o último valor (forward-fill) para a cadência do simulador; não multiplique pela duração do passo. |
| Limites de fase, potência contratada e potências nominais dos equipamentos | Mantenha em `kW`. |
| Marcas temporais dos VE | Converta tempos absolutos para os passos de tempo inteiros usados nos horários dos carregadores. |
| Marcas temporais dos aparelhos diferíveis | Use passos de tempo globais do dataset para `earliest_start_time_step`, `latest_start_time_step` e `deadline_time_step`. |
| Contagens decrescentes dos carregadores de VE | `electric_vehicle_departure_time` e `electric_vehicle_estimated_arrival_time` são contagens de passos, não horas do relógio. |
| Previsões derivadas da interface entity | Calculadas a partir de valores futuros do dataset no tempo do simulador, com horizontes convertidos de segundos usando `seconds_per_time_step`. |
| Retorno das ações na interface entity | As ações pedidas/limitadas são comandos normalizados; os campos de potência pedida/limitada/aplicada estão em `kW`; os campos de energia em janelas curtas estão em `kWh`. |
| Capacidade de energia do BESS na interface entity | `max_*_energy_kwh_step` é a potência nominal convertida pela duração do passo; `available_*_energy_kwh_step` é a capacidade limitada por SOC/margem/corte de energia no mesmo passo. |
| Datasets abaixo do minuto | Inclua a coluna opcional `seconds` em `energy_simulation` sempre que possível. |
| Indicadores de qualidade como `generated` | Mantenha-os no pipeline de ingestão/conversão; não são campos físicos nativos do CityLearn. |

Exemplo:

```text
load_kw = 55.0
seconds_per_time_step = 15
load_kwh_step = 55.0 * 15 / 3600 = 0.2291667
```

Valores pequenos de `kWh/step` são fisicamente corretos a 15s. Se um agente precisar de `kW` ou de valores normalizados, converta na camada de observações do agente, não no balanço energético interno.

## Formatos e carregamento

Os ficheiros de séries temporais referenciados pelo schema podem ser CSV (`.csv`) ou Parquet (`.parquet`, `.pq`, `.parq`). O contrato de colunas e unidades é idêntico nos dois formatos.

O leitor lê apenas a janela declarada por `simulation_start_time_step` e `simulation_end_time_step`, preservando o desfasamento original, para que episódios deslizantes ou que não começam em zero se mantenham alinhados com os índices globais do dataset.

Para datasets grandes, sobretudo dados a 15s de um ano completo, o Parquet é normalmente melhor do que o CSV porque preserva os tipos, comprime melhor e evita a análise de texto. O suporte a Parquet requer `pyarrow`; sem ele, use CSV.

Quando vários edifícios apontam para o mesmo ficheiro `weather`, `pricing` ou `carbon_intensity` e `noise_std = 0`, o simulador partilha a mesma série temporal em memória. `energy_simulation` continua específico de cada edifício, exceto nas colunas de calendário (`month`, `hour`, `minutes`, `seconds`, `day_type`, `daylight_savings_status`): os edifícios cujos valores de calendário são idênticos bit a bit partilham um único array só de leitura, que o simulador nunca escreve. Escrever diretamente num array de calendário levanta `ValueError`; atribua antes um novo array ao atributo. As restantes séries, incluindo `hvac_mode`, `power_outage` e `comfort_band`, continuam específicas de cada edifício e podem ser alteradas diretamente.

A memória cresce com a janela de simulação, não com o episódio: todos os episódios da janela têm de estar disponíveis, e os limites do espaço de observações e o dimensionamento automático leem a janela inteira. Um ano completo a 15 s tem cerca de 2,1 milhões de linhas por edifício. Para um estudo curto, defina `simulation_start_time_step` e `simulation_end_time_step` para o período de interesse em vez de apenas `episode_time_steps`; os limites do espaço de observações e o equipamento dimensionado automaticamente passam a vir desse período, pelo que os resultados não são comparáveis com execuções sobre a janela completa.

### Ruído de robustez

O `noise_std` de um edifício acrescenta ruído gaussiano de média zero às suas temperaturas interior e exterior, à humidade relativa exterior, às irradiâncias solares difusa e direta e às respetivas previsões, à produção solar, ao preço da eletricidade e à intensidade carbónica. O desvio padrão está na unidade de cada série; o ruído não é escalado pela série. Uma regra mantém os valores perturbados fisicamente válidos:

| Série | Limite |
|---|---|
| `solar_generation`, `diffuse_solar_irradiance`, `direct_solar_irradiance` e as respetivas previsões | `>= 0`; sem ruído onde o valor sem ruído é zero (noite) |
| `outdoor_relative_humidity` e as respetivas previsões | `[0, 100]` % |
| `carbon_intensity` | `>= 0` |

Só é cortado o ruído que sai do intervalo: um valor do dataset que já esteja fora dele mantém o seu ruído. A temperatura exterior e os preços da eletricidade, que podem ser negativos, não são limitados; a temperatura interior mantém o seu corte em [-90, 57] C. Com `noise_std = 0`, nenhuma série muda.

## Aparelhos diferíveis

O formato oficial para cargas diferíveis usa dois ficheiros por aparelho:

| Ficheiro | Finalidade |
|---|---|
| `cycle_profiles_file` | Catálogo de perfis físicos de ciclo. |
| `flexibility_schedule_file` | Pedidos de flexibilidade que apontam para entradas do catálogo através de `profile_id`. |

`cycle_profiles_file`:

| Campo | Unidade/tipo | Notas |
|---|---|---|
| `profile_id` | identificador | Chave estável do perfil físico. |
| `duration_steps` | passos | Tem de coincidir com o comprimento de `load_profile`. |
| `total_energy_kwh` | `kWh` | Tem de coincidir com `sum(load_profile)`. |
| `load_profile` | lista de `kWh/step` | Energia consumida em cada passo do ciclo. |

`flexibility_schedule_file`:

| Campo | Unidade/tipo | Notas |
|---|---|---|
| `cycle_id` | identificador | Pedido/ocorrência único. |
| `profile_id` | identificador | Referência ao catálogo. |
| `earliest_start_time_step` | passo de tempo global | Primeiro passo em que o ciclo pode começar. |
| `latest_start_time_step` | passo de tempo global | Último passo em que o agente pode iniciar o ciclo. |
| `deadline_time_step` | passo de tempo global | Último passo até ao qual o ciclo tem de estar concluído. |
| `priority` | rácio `[0, 1]` | Prioridade/urgência externa do pedido. |
| `must_run` | bool | Indicador de contrato de serviço. |

A ação de RL é simples: `start`. Se a ação ultrapassar o limiar, o simulador tenta iniciar o próximo ciclo pendente. O ciclo só começa dentro de `[earliest_start_time_step, latest_start_time_step]` e apenas se couber antes de `deadline_time_step`. Se o `latest_start_time_step` passar sem um início válido, o ciclo é marcado como falhado.

Se os dados reais do ciclo chegarem como potência (`kW`), o conversor tem de gerar o `load_profile` como energia:

```text
cycle_step_kwh = cycle_step_kw * seconds_per_time_step / 3600
```

Não repita o `load_profile` em cada passo de tempo do dataset. A repetição temporal pertence ao `flexibility_schedule_file`, apontando para o mesmo `profile_id`.

## Variáveis de flexibilidade dos VE

Na interface entity, a flexibilidade dos VE deve, de preferência, ser consumida através de variáveis derivadas físicas/normalizadas:

| Variável | Significado |
|---|---|
| `hours_until_departure` | Tempo físico até à partida. |
| `time_until_departure_ratio` | `hours_until_departure / 24`, limitado a `[0, 1]`. |
| `energy_to_required_soc_kwh` | Energia ainda necessária para atingir o SOC alvo. |
| `required_average_power_kw` | Potência média necessária até à partida. |
| `charging_slack_kw` | Margem entre a potência máxima do carregador e a potência média necessária. |
| `charging_priority_ratio` | Urgência em `[0, 1]`, derivada da potência média necessária face à potência máxima do carregador. |
| `max_deliverable_energy_until_departure_kwh` | Energia que ainda pode ser entregue até à partida com a potência de carregamento atualmente viável. |
| `departure_energy_margin_kwh` | `max_deliverable_energy_until_departure_kwh - energy_to_required_soc_kwh`; um valor negativo significa que o alvo é atualmente inviável. |
| `departure_feasibility_ratio` | `energy_to_required_soc_kwh / max_deliverable_energy_until_departure_kwh`; valores acima de `1` indicam inviabilidade com os limites atuais. |
| `min_required_action_normalized` | Potência média necessária do carregador dividida pela sua potência máxima de carregamento; valores acima de `1` indicam um conflito entre potência e prazo. |

## FV

`energy_simulation.solar_generation` é o campo mais fácil de interpretar mal. O simulador lê este campo do dataset. Por compatibilidade com o CityLearn original, o modo predefinido trata-o como perfil de produção por `1 kW` de FV instalado e multiplica-o por `pv.nominal_power`.

Modo predefinido `per_kw`:

```text
pv_generation_kwh_step = pv.nominal_power_kw * solar_generation / 1000
```

Para dados reais absolutos, declare:

```json
"pv": {
  "type": "citylearn.energy_model.PV",
  "autosize": false,
  "attributes": {
    "nominal_power": 120.0,
    "generation_mode": "absolute"
  }
}
```

Com `generation_mode = "absolute"`, `energy_simulation.solar_generation` é interpretado diretamente como energia FV real em `kWh/step`:

```text
pv_generation_kwh_step = solar_generation
```

No modo absoluto, `pv.nominal_power` continua útil como potência instalada ou potência nominal física em `kW`, mas deixa de escalar a série do dataset.
