# Referências (baselines)

Uma referência torna explícito o termo de comparação de um resultado. O CityLearn
usa um controlador business-as-usual operacional para comparar controladores, um
contrafactual convencional para os KPIs normalizados antigos e uma referência de
potência anterior ao evento para a liquidação da resposta à procura. Respondem a
perguntas diferentes.

Versão em inglês: [../baselines.md](../baselines.md).

## Business as usual: a referência operacional

`BusinessAsUsualAgent` representa a operação quotidiana dos equipamentos, sem
aprendizagem, previsões nem otimização de preços. Executa a comunidade
configurada, incluindo a sua procura, produção, equipamentos, calendários e
restrições elétricas. Não é um cenário com todos os equipamentos desligados.

| Equipamento ou serviço | Comportamento BAU |
|---|---|
| VE | Pede a potência máxima de carregamento assim que um VE é ligado, até 100% de SOC por omissão, ou até ao SOC de partida pedido pelo utilizador (ver abaixo). Ignora prazos, preços e previsões solares e nunca pede V2G. Os limites elétricos repartem a potência disponível proporcionalmente entre pedidos simultâneos. |
| Baterias estacionárias | Pede carregamento a partir do excedente FV local estimado e descarga para cobrir a procura local estimada. O orçamento de despacho tem em conta o carregamento dos VE e os arranques dos aparelhos antes da bateria estacionária. |
| Aparelhos flexíveis | Pede o próximo ciclo pendente na primeira oportunidade de arranque viável. |
| Ligação elétrica | O simulador aplica os limites de importação/exportação totais e por fase configurados; as restrições dos equipamentos e do simulador determinam a energia aplicada. |
| Partilha local | As regras de liquidação do cenário valorizam a trajetória resultante. O BAU não otimiza a repartição nem o preço do mercado local. |
| Resposta à procura | Funciona no cenário, mas não tem uma política que otimize um alvo de ativação, um pagamento ou uma penalização. |
| AVAC (`heating_device`, `cooling_device`, `cooling_or_heating_device`) | Pede, em cada passo, a ação que fornece a procura de aquecimento ou de arrefecimento do próprio dataset (ver [AVAC e a versão da baseline](#avac-e-a-versão-da-baseline)). O CityLearn 3.6.0 pedia zero, pelo que nos edifícios com dinâmica de temperatura o seu BAU não aquecia nem arrefecia. |
| Outras ações ativas | Pede zero, limitado aos limites da ação. Não é uma política dedicada de armazenamento térmico ou de escadas rolantes; o efeito de zero segue o contrato de ação de cada equipamento. |

### Escolher o alvo de carregamento do BAU

`BusinessAsUsualAgent` tem dois alvos de carregamento dos VE:

| `ev_charge_target` | Definição | Comportamento dos VE |
|---|---|---|
| `'full'` (predefinido) | `immediate-full-charge-v4` | Carrega até 100%, como o BAU do CityLearn 3.1–3.3. |
| `'requested'` | `immediate-user-target-v3` | Carrega até ao SOC de partida pedido pelo utilizador. O último comando é limitado à energia em falta; se esse comando ficasse abaixo da potência mínima do carregador, o último passo carrega à potência mínima e ultrapassa ligeiramente o alvo, como os baselines por regras, para que o VE não saia abaixo dele. A sua diferença face ao predefinido exclui a energia extra entregue acima do SOC pedido. |

Tudo o resto é igual. Selecione o BAU usado como referência dos KPIs por
`evaluate_v2()` com a definição do ambiente
`business_as_usual_ev_charge_target`, como argumento do construtor ou chave do schema:

```python
env = CityLearnEnv(schema, business_as_usual_ev_charge_target='requested')
agent = BusinessAsUsualAgent(env, ev_charge_target='requested')
```

Os metadados exportados registam a definição selecionada. Compare resultados
apenas com referências com a mesma definição.

Todas as referências em `citylearn.agents.baseline` leem as mesmas observações
de entidades nomeadas e não normalizadas (estado atual, calendários e as
previsões publicadas pelo simulador). Funcionam com a interface flat e com a
interface de entidades e devolvem vetores de ações flat pela ordem de
`env.action_names`.

Com eventos de observação de [robustez](robustness_reference.md), uma referência
executada como controlador lê as observações corrompidas em ambas as interfaces e
toma as mesmas ações. Na interface flat, o ambiente corrompe apenas os vetores
flat, pelo que `predict(observations)` aplica os eventos do passo às observações
de entidades que a referência lê, como faz a interface de entidades.
`predict([])`, que a referência BAU nativa de `evaluate_v2()` usa, lê-as sem
corrupção.

### AVAC e a versão da baseline

Nos datasets cujos edifícios têm dinâmica de temperatura (um modelo LSTM), o
AVAC é uma ação: `heating_device`, `cooling_device` ou
`cooling_or_heating_device`, a fração da potência nominal do equipamento que
fica disponível. Os datasets incluídos com uma ação de AVAC ativa são
`quebec_neighborhood_with_demand_response_set_points`,
`quebec_neighborhood_without_demand_response_set_points`,
`tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood`,
`ca_alameda_county_neighborhood`, `baeda_3dem` e os datasets
`citylearn_challenge_2023_*`.

O BAU funciona com o AVAC como um edifício sem otimização. Em cada passo pede a ação que fornece a procura de
aquecimento ou de arrefecimento do próprio dataset, a `heating_demand` e a
`cooling_demand` simuladas do ficheiro do edifício (as séries
`*_demand_without_control` da simulação energética):

    ação = energia de entrada do equipamento para a procura / (potência nominal × passo do dataset em horas)

limitada aos limites da ação. Os limites do equipamento aplicam-se como a
qualquer outra ação: a potência nominal, o COP da bomba de calor à temperatura
exterior e, durante um corte de energia, a alimentação local. Cada serviço só é
usado nos passos em que o `hvac_mode` o permite; com `cooling_or_heating_device`,
a maior das duas procuras define o sinal. O BAU não pré-aquece, não
pré-arrefece, não segue preços nem usa o armazenamento térmico, que continua a
receber zero.

O CityLearn 3.6.0 pedia zero nessas ações, pelo que, terminado o aquecimento
inicial do LSTM, os edifícios do seu BAU não eram aquecidos nem arrefecidos. As
temperaturas interiores afastavam-se dos set points e todas as linhas
`*_business_as_usual` comparavam o controlador com casas sem aquecimento (ou sem
arrefecimento) ([#362](https://github.com/citylearn-project/CityLearn/issues/362)).
A `baseline_version` 1, que mantinha esse BAU, foi removida no CityLearn 3.8.1.

| `baseline_version` | Baseline dos KPIs | AVAC do BAU | Definição do BAU |
|---|---|---|---|
| `2` | repõe o carregamento de VE do BAU `'full'` | fornece a procura de aquecimento e de arrefecimento do dataset | `immediate-full-charge-v4+hvac-dataset-demand-v1` nos datasets com ações de AVAC, `immediate-full-charge-v4` nos outros |

(Com `business_as_usual_ev_charge_target='requested'`, a definição começa por
`immediate-user-target-v3`.)

A regra do AVAC muda as linhas `*_business_as_usual` e os valores
`*_delta_to_business_as_usual_*` e `*_ratio_to_business_as_usual_*` apenas nos
datasets com ações de AVAC. Nos datasets sem ações de AVAC, o BAU, a sua
definição e identidade, e todos os KPIs são iguais, bit a bit, aos de antes da
regra do AVAC. As comparações dão como
incompatíveis execuções com versões da baseline diferentes, como uma exportação
de uma versão anterior feita com a versão 1.

No Quebec (`quebec_neighborhood_without_demand_response_set_points`, passos
0–335), o BAU predefinido passa a aquecer as casas:

| Quebec, passos 0–335 | Antes (AVAC do BAU a zero) | Agora (predefinido) |
|---|---|---|
| Temperatura interior média / mínima do BAU (°C) | 3,4 / −12,8 | 20,6 / 17,2 |
| `comfort_resilience_discomfort_overall_ratio` do BAU | 0,183 | 0,026 |
| `district_cost_total_business_as_usual_eur` | 631,8 | 4403,8 |
| `cost_ratio_to_business_as_usual_total_ratio` do `RBCSmartPolicy` | 6,970 | 1,000 |
| `cost_ratio_to_business_as_usual_total_ratio` do `ZeroActionAgent` | 1,000 | 0,143 |

```python
env = CityLearnEnv('quebec_neighborhood_without_demand_response_set_points')
agent = BusinessAsUsualAgent(env)  # hvac='dataset_demand', a partir do env
off = BusinessAsUsualAgent(env, hvac='off')  # AVAC a zero
```

`BusinessAsUsualAgent(env, hvac=...)` substitui a predefinição para esse
agente: `'off'` envia zero, `'dataset_demand'` fornece a procura do dataset. O
BAU nativo do `evaluate_v2()` fornece sempre a procura do dataset nos datasets
com ações de AVAC.

**As referências baseadas em regras usam o AVAC da mesma forma.**
`RBCBasicPolicy`, `RBCSmartPolicy` e `RBCCommunityPolicy` fornecem a procura de
aquecimento e de arrefecimento do dataset com a mesma regra do BAU (ver [AVAC das
referências baseadas em regras](#avac-das-referências-baseadas-em-regras)). Os
seus rácios face ao BAU comparam, por isso, casas aquecidas e arrefecidas da
mesma forma. O `ZeroActionAgent` continua a enviar zero, tal como qualquer
controlador próprio que não comande o AVAC: os seus valores
`*_ratio_to_business_as_usual_*` parecem muito melhores apenas porque o BAU paga
o aquecimento e o arrefecimento e ele não. Leia os rácios face ao BAU em
conjunto com os KPIs de conforto (`*_comfort_resilience_discomfort_*`). O
`evaluate_v2()` não tem linhas de conforto `*_business_as_usual`; para ver o
conforto do BAU, execute o `BusinessAsUsualAgent` como controlador e leia os
seus KPIs de conforto.

### Limitações conhecidas

O BAU estima o orçamento inicial de despacho da bateria com a procura não
deslocável observada, o FV e a carga dos aparelhos já em funcionamento no passo
a planear. Se faltar uma entrada necessária, usa a estimativa existente baseada
nas observações já liquidadas. A eletricidade dos equipamentos térmicos é
determinada quando o passo é aplicado. Usar a carga térmica anterior como
procura atual introduziria outro desfasamento temporal. O excedente FV real pode
por isso ser menor do que o estimado num passo com procura térmica, e um pedido
de carregamento pode aumentar a importação da rede. O simulador continua a
impor os limites elétricos configurados.
As referências baseadas em regras planeiam o orçamento da bateria, dos VE e dos
aparelhos com a mesma estimativa do passo atual (desde `basic-v4`,
`smart-local-v4` e `community-v4`); antes, usavam a carga, o FV e as potências da
bateria e dos VE já liquidadas no passo anterior
([#400](https://github.com/citylearn-project/CityLearn/issues/400)).

A bateria do BAU serve apenas a potência que o VE ainda consegue aceitar: a
observação `available_charge_power_kw` do grupo `entity_core_electrical` ou, sem
esse grupo, uma estimativa a partir do SOC observado, da capacidade da bateria,
da potência e da eficiência do carregador e da duração do passo, calculada como o
simulador calcula essa observação. Nenhuma das duas inclui a curva
capacidade-potência da bateria do VE, pelo que, em passos de poucos segundos
perto de 100% de SOC, a bateria ainda pode descarregar mais do que o VE recebe.
A estimativa omite também o limite de importação do serviço elétrico, que o
grupo inclui, e a perda de capacidade: na versão física 2, a observação para na
capacidade degradada da bateria do VE, onde o carregamento para, mas sem o grupo
nenhuma observação mostra a perda, pelo que a estimativa para na capacidade
nominal e pode reservar potência para um VE degradado que já está cheio. As
referências baseadas em regras reservam a potência dos VE que comandam.

Sem esse grupo, as referências também não observam a importação e a exportação
do edifício, pelo que consideram a produção FV acima da carga observada como o
excedente que a bateria pode armazenar. A exportação por si só não é contada como
excedente, porque pode vir de uma descarga da bateria que ultrapassou a carga no
último passo; contá-la levava a bateria a recarregar a partir da rede no passo
seguinte.

### Parâmetros predefinidos

Os argumentos nomeados substituem os hiperparâmetros da política. Nomes
desconhecidos levantam um `ValueError`. Os principais parâmetros do BAU são:

| Parâmetro | Predefinido | Significado |
|---|---:|---|
| `ev_normal_charge_rate` | `1.0` | Comando de carregamento do VE abaixo do alvo, como fração da potência máxima do carregador. |
| `storage_min_soc` | `0.20` | Deixa de pedir descarga da bateria abaixo deste SOC. |
| `storage_max_soc` | `0.90` | Deixa de pedir carregamento da bateria acima deste SOC. |
| `storage_charge_rate` | `1.0` | Comando máximo de carregamento da bateria para excedente FV. |
| `storage_discharge_rate` | `1.0` | Comando máximo de descarga da bateria para importação local. |
| `pv_surplus_threshold_kw` | `0.05` | Excedente FV que desencadeia o carregamento da bateria. |
| `normal_storage_discharge_import_threshold_kw` | `0.05` | Importação local que desencadeia a descarga da bateria. |
| `deferrable_start_action` | `1.0` | Comando de arranque de um aparelho flexível pronto. |

Os limiares de armazenamento decidem se se pede carregamento ou descarga; não
são restrições rígidas de SOC. Os limites físicos da bateria são aplicados pelo
simulador.

Consulte a [primeira simulação](https://www.citylearn.net/quickstart.html) para
uma execução completa com estes valores predefinidos. Um BAU personalizado é
criado explicitamente:

```python
from citylearn.agents.baseline import BusinessAsUsualAgent

agent = BusinessAsUsualAgent(env, storage_min_soc=0.10, storage_max_soc=0.95)
```

Identifique as execuções personalizadas com os valores dos seus parâmetros. A
comparação automática descrita abaixo instancia o BAU nativo predefinido; não
herda parâmetros de um agente separado criado pelo utilizador.

## Referências baseadas em regras

Três controladores baseados em regras dão referências progressivamente mais
informadas entre o BAU e um controlador aprendido. Execute-os com os mesmos
membros, ficheiros, janelas, sementes e condições de mercado que o candidato.

| Agente | Política |
|---|---|
| `RBCBasicPolicy` | Usa o preço atual e a urgência do serviço para os VE e os aparelhos flexíveis. Os VE recebem o carregamento mínimo que cumpre o seu alvo de partida, aumentado quando o preço é baixo. Os aparelhos arrancam quando há urgência ou o preço é baixo. A bateria faz autoconsumo. |
| `RBCSmartPolicy` | Usa previsões de preço e o excedente FV local previsto para agendar o carregamento dos VE e os arranques dos aparelhos. A bateria combina autoconsumo, arbitragem de preços e uma reserva de serviço. Usa apenas observações locais do edifício e públicas. |
| `RBCCommunityPolicy` | Acrescenta a energia partilhável entre membros da comunidade. Com o mercado comunitário ativo, as baterias podem apoiar os períodos caros quando a importação da comunidade atinge `community_import_threshold_kw` (15 kW por omissão). Este valor desencadeia uma ação; o pico observado pode excedê-lo. Sem mercado comunitário, não partilha energia e segue as regras económicas da Smart mas, ao contrário da Smart, não está restrita a observações locais do edifício. |

Os três param de carregar um VE 0,001 de SOC abaixo do alvo. No último intervalo antes da partida podem pedir até mais 25% de energia AC do que a energia em falta do lado da bateria (`EV_LAST_INTERVAL_LOSS_ALLOWANCE`), para cobrir as perdas do carregador e da bateria que não observam, e pelo menos a potência mínima do carregador.

### AVAC das referências baseadas em regras

Os motores despacham as baterias, os carregadores de VE e os aparelhos flexíveis.
As ações de AVAC (`heating_device`, `cooling_device`, `cooling_or_heating_device`)
seguem `hvac`:

| `hvac` | Ações de AVAC |
|---|---|
| `'dataset_demand'` (predefinido) | Fornecem, em cada passo, a procura de aquecimento e de arrefecimento do próprio dataset, com a regra do BAU predefinido (ver [AVAC e a versão da baseline](#avac-e-a-versão-da-baseline)): um termóstato que satisfaz a carga, sem otimização. |
| `'off'` | Zero, como antes. Nos datasets com dinâmica de temperatura, as casas não são aquecidas nem arrefecidas. |

Nos datasets sem ações de AVAC, os dois dão os mesmos resultados, bit a bit, e a
mesma `comparison_identity()`. Nos datasets com ações de AVAC, a identidade
regista `hvac='dataset_demand'` e a versão da definição ganha o sufixo
`+hvac-dataset-demand-v1`, para que estas execuções não se misturem com as de
versões anteriores. O armazenamento térmico continua a receber zero.

No Quebec (`quebec_neighborhood_without_demand_response_set_points`, passos
0–335), as três referências baseadas em regras aquecem as casas como o BAU
predefinido. A temperatura interior média é de 20,6 °C em vez de 3,4 °C, a mínima
de 17,2 °C em vez de −12,8 °C, e
`district_comfort_resilience_discomfort_overall_ratio` passa de 0,183 para
0,026. O Quebec não tem baterias nem VE, pelo que funcionam então exatamente como
o BAU: custo de 4403,8 EUR e rácio de custo de 1,000. Com `hvac='off'` custam
631,8 EUR, um rácio de 0,143. Face ao BAU do CityLearn 3.6.0, que não aquecia, o
seu rácio de custo era de 6,970.

```python
smart = RBCSmartPolicy(env)               # AVAC satisfaz a procura do dataset
legacy = RBCSmartPolicy(env, hvac='off')  # AVAC a zero, como antes
```

A Smart e a Community usam os grupos de observações de entidades quando o schema
os ativa: `entity_core_electrical` para a importação e a exportação medidas,
`entity_forecasts_existing` e `entity_forecasts_derived` para as previsões de
preço e FV, e `entity_community_operational` para a importação e o excedente da
comunidade. O simulador deixa-os desativados, salvo se o schema os ativar; alguns
datasets incluídos ativam-nos (por exemplo
`citylearn_challenge_2022_phase_all_plus_evs` e a demonstração de topologia
dinâmica), outros não (por exemplo
`citylearn_three_phase_electrical_service_demo`). Sem o grupo da comunidade, a
Community não consegue observar a importação nem o excedente da comunidade; sem
os grupos de previsões, a Smart e a Community recorrem ao preço e ao FV atuais.
Ative-os no schema, por exemplo
`"observation_bundles": {"entity_community_operational": true}`.

A Smart e a Community só carregam a bateria a partir da rede a preço baixo
quando não há excedente FV local previsto. Com `entity_forecasts_derived`, essa
previsão é `forecast_net_next_*_kw`. Sem ela, a previsão solar faz as suas vezes:
um edifício com FV não carrega a partir da rede a preço baixo enquanto a sua
previsão FV, ou uma previsão de irradiância (`*_solar_irradiance_predicted_*`)
acima de 100 W/m², indicar que vem aí produção FV. Sem nenhuma previsão solar, o
carregamento a preço baixo funciona como antes. Até `smart-local-v3` e
`community-v3`, a previsão de excedente em falta era lida como zero; em datasets
como `citylearn_challenge_2022_phase_all`, as baterias enchiam a partir da rede
antes do nascer do sol e depois exportavam o FV que já não conseguiam guardar
([#400](https://github.com/citylearn-project/CityLearn/issues/400)).

`RBCBasicPolicy` compara o preço atual com limiares fixos,
`basic_cheap_price_eur_kwh=0.0765` e `basic_expensive_price_eur_kwh=0.1078`.
São os tercis do preço diário português de 2023 usado para calibrar a política.
Para outra tarifa, defina os dois limiares na unidade de preço do dataset, ou
use `basic_price_policy='forecast_relative'` para comparar o preço atual com a
previsão de preço:

```python
from citylearn.agents.baseline import RBCBasicPolicy, RBCCommunityPolicy

basic = RBCBasicPolicy(env, basic_cheap_price_eur_kwh=0.20, basic_expensive_price_eur_kwh=0.35)
community = RBCCommunityPolicy(env, community_import_threshold_kw=10.0)
```

Estas políticas foram portadas das referências dos Soft-CPS Algorithms (commit
`725a72a`) e mantêm as suas regras e valores predefinidos, com três alterações
do CityLearn. A regra de AVAC acima é própria do CityLearn (`hvac='off'` dá o
AVAC a zero da versão portada). Desde `basic-v4`, `smart-local-v4` e
`community-v4`, planeiam com a carga e o FV do passo atual, como o BAU, enquanto
a versão portada reage às observações liquidadas do passo anterior; por isso, as
suas ações diferem das da versão portada em todos os datasets. A previsão solar
que substitui uma previsão de excedente FV em falta também é própria do
CityLearn; nunca atua quando `entity_forecasts_derived` está ativo, como em
`pt_rec_*` e `citylearn_challenge_2022_phase_all_plus_evs`. `agent.comparison_identity()` regista a classe, a versão da definição
e os parâmetros resolvidos para os manifestos das experiências.

As referências baseadas em regras também podem orientar a exploração de `SACRBC`
e `MARLISARBC`. Passe como `rbc` uma instância construída sobre o mesmo
ambiente, a classe ou o seu caminho de importação. Nos datasets com ações de
AVAC, a exploração usa então o AVAC à procura do dataset, como a referência
baseada em regras; passe `hvac='off'` para manter o AVAC a zero. Com uma classe
ou um caminho de importação, os hiperparâmetros do próprio aprendiz ficam com o
aprendiz, e os restantes argumentos nomeados vão para a referência:

```python
from citylearn.agents.baseline import RBCBasicPolicy
from citylearn.agents.sac import SACRBC

agent = SACRBC(env, rbc=RBCBasicPolicy, lr=3e-4, batch_size=256, basic_price_policy='forecast_relative')
agent = SACRBC(env, rbc=RBCBasicPolicy(env, basic_price_policy='forecast_relative'), lr=3e-4)
```

Os controladores de aprendizagem por reforço (`SAC`, `SACRBC`, `MARLISA`,
`MARLISARBC`, `TabularQLearning`) leem vetores de observação flat e exigem
`interface='flat'`; na interface de entidades levantam um `ValueError`. As
referências baseadas em regras, `ZeroActionAgent` e o `Agent` aleatório
funcionam com as duas interfaces.

### Avaliação BAU automática

`env.evaluate_v2()` executa ou reutiliza uma simulação BAU separada até ao passo
de avaliação atual. Essa simulação é reconstruída a partir do schema de origem,
dos membros/VE selecionados, da janela do episódio, do passo de tempo, do modo de
topologia e da semente. Volta também a aplicar as substituições do construtor do
ambiente `simulate_power_outage`, `solar_generation`,
`active_actions`/`inactive_actions` e
`active_observations`/`inactive_observations`, para que a referência simule os
mesmos equipamentos, produção e cortes de energia. Carrega os edifícios pela
ordem do ambiente avaliado, para que as listas de substituições por edifício
cheguem aos mesmos edifícios quando `buildings=[1, 0]` os seleciona por uma ordem
diferente da do schema. Usa o modo de entidades quando a topologia dinâmica ou a
resposta à procura o exigem. A renderização fica desativada nesta comparação
interna.

A referência reproduz o que o schema e estes argumentos do construtor definem.
Não consegue acompanhar edifícios, equipamentos ou carregadores alterados depois
do carregamento, por exemplo um novo `max_charging_power` de um carregador ou o
`simulate_power_outage` de um edifício. Antes de ser executada, é comparada com o
ambiente avaliado tal como foi registado no seu último `reset()`: a ordem dos
edifícios, o `simulate_power_outage` e as ações ativas de cada edifício, as
dimensões e os parâmetros de todos os equipamentos (bombas de calor,
aquecedores, depósitos de armazenamento, FV, baterias, carregadores, aparelhos e
baterias dos VE), e a capacidade e a energia inicial das baterias e dos VE. Uma
diferença levanta um `ValueError` que indica a definição; nesse caso, avalie com
`include_business_as_usual=False`. Uma alteração feita depois de `reset()` não é
detetada: a comparação cobre a configuração registada no reset.

Para cortes de energia estocásticos, o CityLearn usa a `random_seed` explícita
do modelo quando é fornecida. Caso contrário, os modelos incluídos derivam a sua
semente da semente do ambiente, da janela do episódio e do nome do edifício. O
controlador e a sua referência BAU nativa enfrentam por isso os mesmos cortes
quando usam a mesma configuração do modelo.

Os resultados ficam em cache para o episódio e o passo atuais. A saída acrescenta
valores `business_as_usual`, diferenças `delta_to_business_as_usual` e rácios
`ratio_to_business_as_usual` para as métricas suportadas:

```python
kpis = env.evaluate_v2()
reference_rows = kpis.loc[
    (kpis["level"] == "district")
    & kpis["cost_function"].str.contains("business_as_usual"),
    ["cost_function", "value"],
]
print(reference_rows.to_string(index=False))
```

Use `include_business_as_usual=False` para avaliar apenas a execução atual e o
contrafactual convencional. `env.run_business_as_usual_baseline(force=True)`
recalcula a referência BAU em cache.

## Contrafactual de avaliação convencional

Os nomes que contêm `baseline` em vez de `business_as_usual` referem-se às
condições de avaliação selecionadas através de `baseline_condition`. Por
omissão, usa as séries contrafactuais do simulador sem armazenamento e, nos
modelos de edifício dinâmicos, sem controlo de carga parcial, mantendo o FV.

"Sem armazenamento" retira a bateria, o armazenamento térmico e o carregamento
dos VE da execução controlada, e volta a somar o carregamento dos VE do BAU
nativo com o alvo `'full'`: cada carro é carregado quando chega, à potência
máxima, até ficar cheio, e nunca é descarregado. Os carros recebem a energia de
que precisam, sem V2G, e a baseline não depende de como o controlador os
carregou, pelo que um controlador que deixa os carros com menos carga não baixa
a sua própria baseline. Os aparelhos diferíveis ficam como o controlador os
operou. O AVAC também, exceto nos edifícios com dinâmica de temperatura (LSTM):
aí a condição predefinida usa a procura de aquecimento e de arrefecimento de
carga ideal do dataset, em vez do AVAC que o controlador operou. As linhas `baseline` creditam assim ao controlador o
despacho do armazenamento, o carregamento dos VE e o V2G, face a carregar à
chegada, e nos edifícios com dinâmica de temperatura também o controlo do AVAC.
O CityLearn 3.6.0 não somava nada, pelo que nos datasets com VE a sua
baseline era uma comunidade cujos carros nunca carregavam.

Fora esse carregamento dos VE, trata-se de um cálculo contrafactual a partir
das séries da própria execução, não de uma segunda execução de
`BusinessAsUsualAgent`. Nos datasets com carregadores de VE o carregamento vem
do sidecar do BAU, que cada avaliação passa então a executar, também o
`evaluate()` antigo e `evaluate_v2(include_business_as_usual=False)`, com o alvo
`'full'` qualquer que seja `business_as_usual_ev_charge_target`. Tal como as
linhas do BAU, não pode ser construído quando as entradas, os edifícios ou os
equipamentos mudam depois do carregamento, e a avaliação lança então
`ValueError`. `EvaluationCondition` expõe também alternativas,
incluindo a remoção do FV. Escolha a mesma condição de avaliação ao comparar
controladores. Durante um corte de energia simulado, o contrafactual, tal como a
execução controlada, não troca energia com a rede: os seus valores de net, custo
e emissões são zero nesses passos de tempo.

Com o mercado comunitário ativo, os custos do controlo e do contrafactual são
liquidados com as regras de mercado do cenário, tanto nos KPIs antigos como nos
v2 e nos de auditoria de equidade. As poupanças da troca local não são então
creditadas ao controlador.

Por exemplo, `district_cost_ratio_to_baseline_total_ratio` e
`district_cost_ratio_to_business_as_usual_total_ratio` têm denominadores
diferentes. Um valor abaixo de um significa um custo mais baixo do que o da
referência indicada.

## Referência de resposta à procura

A entrega de DR é medida face à potência líquida média na janela de histórico
anterior ao evento configurada. A referência é fixada para cada pedido e depois
usada para medir o movimento na direção pedida durante a sua ativação.

Esta referência não é o contrafactual convencional nem uma execução BAU.
Configure `demand_response.baseline_window_seconds` e verifique a validade da
referência juntamente com a resposta pedida, entregue e creditada. Consulte o
[schema de DR](schema_reference.md#resposta-à-procura) e os
[KPIs de DR](kpis_reference.md#demand-response).

## Uma execução de referência selecionada na UI

Ao comparar execuções importadas, a UI identifica a primeira simulação incluída
na sua lista importada como **Compare baseline**. É uma execução selecionada pelo
utilizador; não tem de ser o BAU nativo. As colunas `business_as_usual` dentro de
cada tabela de KPIs exportada mantêm o significado definido pelo simulador.

Leia [o scorecard](scorecard.md) para comparações entre controladores
emparelhados e [o guia da UI](https://www.citylearn.net/ui.html) para o fluxo de
trabalho visual.

A partir da 3.4.0, o BAU continua a carregar os VE até 100% por omissão, agora
decidido a partir das observações de entidades, como as outras referências;
`ev_charge_target='requested'` carrega apenas até ao SOC de partida pedido. A
versão da definição, registada com cada referência nativa, muda sempre que as
ações da referência mudam. Referências calculadas com outra versão da definição
não são comparáveis; volte a executar o controlador e a sua referência.
