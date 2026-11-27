# Referência multicomunidade

`MultiCommunityEnv` orquestra várias instâncias independentes de `CityLearnEnv`, com um ambiente filho por comunidade. A v1 faz apenas sincronização e relatórios do portefólio: não há camada física global, mercado entre comunidades, coordenação DSO/TSO global nem mistura de edifícios entre comunidades.

Versão em inglês: [../multi_community_reference.md](../multi_community_reference.md).

## Início rápido

```python
import numpy as np
from citylearn.multi_community import MultiCommunityEnv

env = MultiCommunityEnv(
    communities=[
        {
            "community_id": "community_a",
            "schema": "citylearn_challenge_2022_phase_all_plus_evs",
            "env_kwargs": {"interface": "entity", "episode_time_steps": 48},
            "weight": 1.0,
        },
        {
            "community_id": "community_b",
            "schema": "citylearn_challenge_2022_phase_all",
            "env_kwargs": {"interface": "entity", "episode_time_steps": 48},
            "weight": 2.0,
        },
    ],
    render_directory="outputs/runs",
    render_session_name="portfolio_001",
)

observations, info = env.reset(seed=0)
terminated = truncated = False

while not (terminated or truncated):
    actions = {
        community_id: {
            "tables": {
                table: np.zeros(space.shape, dtype="float32")
                for table, space in child.action_space["tables"].items()
            }
        }
        for community_id, child in env.envs.items()
    }
    observations, rewards, terminated, truncated, info = env.step(actions)

kpis = env.evaluate_v2(include_business_as_usual=False)
print(kpis.loc[kpis["level"] == "portfolio"].head())
env.close()
```

## Construtor

```python
MultiCommunityEnv(
    communities=[
        {
            "community_id": "community_a",
            "schema": "path/or/dataset/name/schema.json",
            "env_kwargs": {"interface": "entity", "episode_time_steps": 48},
            "weight": 1.0,
        }
    ],
    render_directory=None,
    render_session_name=None,
)
```

`community_id` tem de ser único, não vazio e seguro como componente de um caminho relativo. Só pode conter letras, números, `_`, `-` e `.`. `weight` tem o valor predefinido `1.0`, tem de ser finito e não negativo, e pelo menos uma comunidade tem de ter um peso positivo. Cada entrada só aceita `community_id`, `schema`, `env_kwargs` e `weight`: qualquer outra chave levanta um `ValueError` que a nomeia, e `weight` tem de ser um número: um booleano ou um texto como `'2'` levanta um `ValueError`.

`env_kwargs` são passados ao `CityLearnEnv` filho. O wrapper define a sessão de exportação de cada filho como `<render_session_name>/<community_id>`, para que os ficheiros de render e de KPIs fiquem separados por comunidade.

## Reset e step

`reset()` devolve as observações dos filhos por comunidade, mais a info do wrapper:

```python
observations = {"community_a": child_observations, "community_b": child_observations}
info = {"communities": {...}, "time_step": 0}
```

`reset(seed=..., options=...)` passa `seed` a todos os filhos. `options` pode conter um
mapeamento por comunidade, indexado por `community_id`; uma comunidade sem entrada própria
recebe o mapeamento `options` completo:

```python
# community_a repete o episódio 2. community_b não tem entrada, pelo que recebe o
# mapeamento completo e repete o episódio 0.
env.reset(options={"community_a": {"episode_index": 2}, "episode_index": 0})

# As mesmas opções para todos os filhos.
env.reset(options={"episode_index": 2})
```

`step(actions)` espera um payload de ações do filho por comunidade:

```python
actions = {"community_a": child_actions, "community_b": child_actions}
```

Devolve:

```python
observations_by_community,
rewards_by_community,
terminated,
truncated,
info
```

`info` inclui:

| Chave | Significado |
|---|---|
| `community_rewards_scalar` | Soma finita do payload de recompensa de cada filho. |
| `reward_total` | `sum(weight * community_reward_scalar)`. |
| `reward_mean_weighted` | `reward_total / sum(weights)`. |
| `terminated_by_community` | Flags de terminação dos filhos. |
| `truncated_by_community` | Flags de truncagem dos filhos. |

Se algum filho terminar ou truncar, o wrapper também termina ou trunca. Isto impede que as comunidades derivem para posições diferentes do episódio.

## Contrato de sincronização

Todos os ambientes filhos têm de usar:

| Requisito | Motivo |
|---|---|
| O mesmo `seconds_per_time_step` | Mantém o tempo de cada passo alinhado. |
| A mesma duração efetiva do episódio | Mantém os lotes de treino retangulares. |
| A mesma `interface` | Mantém estáveis os contratos dos payloads de observação/ação. |
| O mesmo modo `central_agent` | Evita misturar semânticas de recompensa/ação centralizadas e descentralizadas. |
| A mesma `physics_version` | Os totais do portefólio somam valores dos distritos, pelo que todas as comunidades têm de simular a mesma física. |
| A mesma `random_stream_version` | As predefinições sorteadas (curvas e eficiências das baterias, ruído) têm de vir da mesma definição do fluxo aleatório para que os totais sejam comparáveis. |
| A mesma `baseline_version` | Os KPI de referência do portefólio somam as referências dos distritos, pelo que a definição da referência tem de coincidir. |
| O mesmo `business_as_usual_ev_charge_target` | Os totais BAU do portefólio e os rácios face ao BAU somam as execuções BAU dos distritos, pelo que todas as comunidades têm de carregar os VE no BAU até ao mesmo alvo (`full` ou `requested`). |
| O mesmo `ev_soc_carryover` | Altera o estado dos VE no início de cada episódio, na execução controlada e no BAU, pelo que os totais do portefólio misturariam duas definições de VE. |
| Os mesmos `ev_departure_service_tolerance` e `ev_departure_within_tolerance` | Definem os limiares mínimo aceitável e dentro da tolerância das contagens de partidas dos VE que o portefólio soma. |
| O mesmo `energy_provenance` | Uma comunidade com o registo de proveniência desligado não tem linhas de proveniência, pelo que os totais de proveniência do portefólio cobririam só as outras comunidades. |
| A mesma `evaluation_window` quando ativa | Mantém alinhados os KPIs da janela recorrente entre comunidades. |

O wrapper valida estas condições na construção e novamente depois do reset, e
lança um `ValueError` que indica a definição, por exemplo:

```text
ValueError: MultiCommunityEnv requires all communities to share physics_version, got {'A': 2, 'B': 1}.
```

As janelas de calendário não fazem parte do contrato. Cada filho seleciona a
divisão do seu episódio a partir da sua própria janela de simulação, da definição
`random_episode_split` e da `random_seed`, pelo que as comunidades podem simular
datas diferentes no mesmo passo. Para partilhar janelas, dê aos filhos as mesmas
definições de janela e a mesma `random_seed`, ou passe uma semente a
`reset(seed=...)`, que chega a todos os filhos.

## Resposta à procura

A resposta à procura continua local a cada comunidade. Se o schema de um filho tiver `demand_response.enabled=true`, esse filho carrega o seu próprio `requests_file`, expõe os seus próprios metadados de pedidos nas observações entity e calcula a liquidação e os KPIs locais. Na v1, `MultiCommunityEnv` não coordena pedidos DSO/TSO entre comunidades.

## Agregação dos KPIs

`evaluate_v2()` concatena as tabelas de KPIs dos filhos e adiciona uma coluna `community_id`. Também adiciona linhas do portefólio:

```text
level = "portfolio"
name = "Portfolio"
community_id = "__portfolio__"
```

Só os KPIs de distrito dos filhos são agregados:

| Sufixo do KPI | Regra do portefólio |
|---|---|
| `_kwh`, `_eur`, `_kgco2`, outros `_count` | Soma entre comunidades. |
| `_ratio` de um total de controlo sobre um total de referência | Rácio dos totais somados, por exemplo `portfolio_cost_total_control_eur / portfolio_cost_total_baseline_eur`. |
| Taxas e médias com denominadores aditivos | Agregadas: média ponderada pelo denominador, por exemplo `portfolio_ev_events_departure_met_count / portfolio_ev_events_departure_count`. |
| Outros `_ratio`, `_percent` | Média ponderada pelo `weight` da comunidade. |
| `_kw`, `_c`, outros `_hours` e outras métricas pontuais | Não agregados na v1. |

Os rácios reconstruídos a partir dos totais somados são os rácios
`ratio_to_baseline` e `ratio_to_business_as_usual` do custo, das emissões e da
importação, exportação e troca líquida com a rede, e os rácios
`ratio_to_business_as_usual` da produção e exportação solar, do carregamento dos
VE e da exportação V2G, do carregamento, descarga e energia movimentada das
baterias, e das contagens de ciclos e de energia dos aparelhos diferíveis. Usam
apenas as comunidades que reportam os dois totais, ignoram o `weight` tal como os
totais somados, e mantêm a regra "mais baixo é melhor" da
[referência de KPIs](kpis_reference.md#regras-comuns) para totais negativos de
troca líquida e de custo. O rácio de um portefólio com uma só comunidade é igual
ao rácio do distrito.

As taxas e médias agregadas são ponderadas pelos seus denominadores aditivos,
pelo que igualam o rácio entre o numerador e o denominador agregados e ignoram o
`weight`:

| Taxa ou média | Peso |
| `energy_grid_window_average_power_*_kw` | Soma com sinal entre comunidades que partilham `evaluation_window` (`NaN` se alguma comunidade for indefinida). |
|---|---|
| Taxas de sucesso, de mínimo aceitável e dentro da tolerância nas partidas dos VE; médias de défice, falta, excedente e erro absoluto do SOC | `ev_events_departure_count` |
| Taxas de partida `*_feasible` dos VE | O `ev_events_departure_*_feasible_count` correspondente |
| Nível de serviço dos aparelhos diferíveis (controlo e BAU) | Ciclos concluídos mais ciclos falhados |
| Atraso médio no arranque dos aparelhos diferíveis (controlo e BAU) | Ciclos concluídos |
| Nível de serviço das escadas rolantes | Passageiros pedidos |
| Autoconsumo solar (controlo e BAU) | Produção solar |
| Quota local da procura no mercado comunitário (`*_local_share_of_demand_ratio`, `*_import_share_ratio`) | Importação local mais importação da rede depois das trocas locais |
| Quota local da exportação no mercado comunitário | Exportação local mais exportação para a rede depois das trocas locais |
| Cumprimento da resposta à procura | `demand_response_valid_requested_total_kwh` |
| Cumprimento da auditoria da resposta à procura, cobertura da energia pedida e cobertura da referência, por finalidade | A energia pedida válida, a energia pedida e os intervalos ativos da auditoria |
| Ciclos completos equivalentes das baterias estacionárias (controlo e BAU) | Capacidade nominal das baterias estacionárias |

As diferenças e os rácios face ao BAU do nível de serviço dos aparelhos
diferíveis, do atraso no arranque, do autoconsumo e dos ciclos completos
equivalentes agregados comparam os valores agregados de controlo e BAU. As
comunidades cujo valor é indefinido não têm peso.

Para as baterias estacionárias, a contagem de ciclos do portefólio é a energia
movimentada total dividida pelo dobro da capacidade nominal total. As baterias
instaladas contribuem com a sua capacidade mesmo quando estão inativas. O
resultado é indefinido quando a capacidade total é zero.

Os rácios sem totais aditivos continuam a ser médias ponderadas: rácios de forma
da rede (picos, rampas e penalizações do fator de carga), proporções de conforto
e de resiliência, equidade, os rácios de serviço térmico, de partidas dos VE e de
outras auditorias, a perda de capacidade das baterias e o rácio entre a perda de
capacidade das baterias e o seu valor BAU.

As comunidades sem mercado comunitário reportam zeros nas suas linhas de mercado.
Num portefólio em que umas comunidades têm mercado e outras não, uma comunidade
sem mercado entra nas linhas de mercado do portefólio
(`portfolio_energy_grid_community_market_*`, `portfolio_cost_community_market_*`
e `portfolio_solar_self_consumption_community_market_*`) com a sua liquidação
simples com a rede: sem troca local, a importação e a exportação dos seus
membros como importação e exportação da rede depois da troca local, o seu
`cost_total_control_eur` como custo liquidado e contrafactual, e poupança e
saldo do operador nulos. As linhas de mercado do portefólio cobrem então todas
as comunidades, e as quotas são as de todo o portefólio. As linhas de distrito
da própria comunidade não mudam, nem os portefólios em que todas as comunidades
têm mercado ou nenhuma tem
([#373](https://github.com/citylearn-project/CityLearn/issues/373)).

Os nomes dos KPIs do portefólio substituem um prefixo inicial `district_` por `portfolio_`; por exemplo, `district_demand_response_revenue_total_eur` passa a `portfolio_demand_response_revenue_total_eur`.

## Exportação

`export_final_kpis()` escreve a exportação de cada filho na sua própria subpasta e escreve um CSV global na pasta da sessão do wrapper:

```text
<render_directory>/<render_session_name>/
  exported_kpis_multi_community.csv
  community_a/exported_kpis.csv
  community_b/exported_kpis.csv
```

O CSV global mantém o formato longo de `evaluate_v2()`, com linhas locais e do
portefólio e as colunas `unit` e `description`. Cada filho mantém a sua tabela
numérica em formato largo e guarda as definições dos seus KPIs em
`exported_kpis.manifest.json`.
