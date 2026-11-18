# Fornecedores externos de mobilidade

Um fornecedor de mobilidade (*mobility provider*) controla as ligações de veículos elétricos (EV)
durante um episódio. Liga, por exemplo, um simulador de tráfego como o SUMO ou o CARLA ao CityLearn:
o simulador de tráfego decide onde e quando os veículos estacionam, o CityLearn calcula a energia de
carga e de veículo-para-edifício e o controlador decide os *set-points* dos carregadores.

## Funcionamento

Normalmente, um carregador lê o seu calendário (ligado, a chegar ou ausente, EV, contagem até à
partida, SOC pedido à partida, chegada estimada) de um ficheiro. Um carregador externo tem as mesmas
linhas de calendário, mas estas começam "ausente" e o fornecedor escreve-as durante o episódio. Tudo
o que lê essas linhas fica igual: a associação carregador-EV, o SOC de chegada, as observações flat
e entity, os KPI, a auditoria de partidas de EV e a referência *business-as-usual* (BAU).

## Schema

Um carregador é externo quando o nome do ficheiro de calendário é substituído por:

```json
"chargers": {
  "hub_1": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": {"source": "external"},
    "attributes": {"max_charging_power": 11.0, "max_discharging_power": 11.0}
  }
}
```

Um veículo cujo estado de carga (SOC) é comunicado pelo fornecedor declara-se assim:

```json
"electric_vehicles_def": {
  "EV_1": {"external": true, "battery": {"attributes": {"capacity": 60.0, "nominal_power": 11.0}}}
}
```

O CityLearn não aplica deriva aleatória de SOC a um veículo externo enquanto está ausente. O seu SOC
só muda com a carga, com a perda em repouso da bateria e com o fornecedor. Veículos sem `external`
também podem ser ligados a carregadores externos; mantêm a deriva aleatória enquanto ausentes, exceto
nos passos em que o fornecedor define o seu SOC. Os carregadores externos não são suportados com
`topology_mode="dynamic"`.

## Fornecedor

Um fornecedor é qualquer objeto com dois métodos (`citylearn.mobility.MobilityProvider`):

| Método | Chamado |
|---|---|
| `reset(env)` | Em cada `env.reset()`, depois de os edifícios e veículos serem reiniciados e antes de os carregadores serem associados para o passo 0. O construtor também executa `reset()`, pelo que um fornecedor passado ao construtor é reiniciado durante a construção. |
| `update(env, time_step)` | Em `env.step()`, depois de a energia do intervalo `time_step - 1` estar calculada e de o ambiente avançar para `time_step`, antes de os carregadores serem associados para `time_step`. Não é chamado na transição terminal, após a qual não há mais ações. |

Passe-o como `CityLearnEnv(..., mobility_provider=provider)` ou atribua `env.mobility_provider` antes
de `env.reset()`. Como `update` corre antes da associação, as observações devolvidas por `step()` já
mostram as ligações escritas para o novo passo. `step_many()` e a referência BAU usam o mesmo caminho;
as atualizações de observações e de topologia nunca chamam o fornecedor.

## Escrever o calendário

Dentro de `reset` e `update`, o fornecedor escreve através de `env.mobility`. Escritas fora destas
chamadas lançam `RuntimeError`. Cada escrita aplica-se de imediato ao passo atual.

| Chamada | Efeito |
|---|---|
| `connect(charger_id, ev_id, *, soc=None, departure_steps=None, required_soc=None, session_id=None, connected_seconds=None, discharge_soc_floor=None)` | Liga o veículo. |
| `incoming(charger_id, ev_id, *, arrival_steps=None, soc_on_arrival=None)` | Anuncia um veículo a caminho de um carregador livre; as estimativas são apenas observações. |
| `away(charger_id)` | Liberta o carregador. |
| `set_vehicle_soc(ev_id, soc)` | Define o SOC de um veículo que não continua uma sessão de carga, por exemplo depois de conduzir. |

Uma ligação mantém-se de um passo para o seguinte até `away()` ou outra escrita a alterar. As
contagens até à partida e até à chegada diminuem uma unidade por passo e param em 0; o veículo sai no
fim do passo em que a contagem até à partida é 1. Contagens para além do episódio são guardadas como
a duração do episódio, o limite superior do espaço de observação.

| Argumento de `connect` | Significado |
|---|---|
| `soc` | SOC à chegada, em [0, 1]. Só quando a chamada inicia uma sessão; define o SOC do veículo. Sem ele, a sessão começa com o SOC que o veículo tem no CityLearn. Em ambos os casos, o valor é o SOC de chegada da sessão para o runtime, os KPI e a auditoria de partidas. |
| `departure_steps` | Passos até à partida. Desconhecido se omitido no início da sessão; mantido se omitido depois. |
| `required_soc` | SOC que o utilizador pede à partida. Desconhecido se omitido no início da sessão; mantido se omitido depois. |
| `session_id` | Identidade da sessão; gerada se omitida. Um novo ID para o veículo já ligado inicia uma sessão seguida. |
| `connected_seconds` | Segundos do passo atual em que o veículo está ligado, em [0, `seconds_per_time_step`]. A energia do passo é a potência comandada durante esse tempo; os limites de potência e a eficiência da bateria referem-se a ele. Aplica-se a um só passo. |
| `discharge_soc_floor` | A descarga nesta sessão nunca leva a bateria abaixo deste SOC, por exemplo a energia necessária para a viagem seguinte. A carga não é afetada. |

Escritas inválidas lançam `ValueError` com o motivo: carregador ou veículo desconhecido, ID de
carregador usado por vários edifícios (escreva `"<edifício>/<carregador>"`), carregador com ficheiro
de calendário, veículo ligado a outro carregador no mesmo passo, carregador ocupado, `soc` numa
sessão em curso ou `set_vehicle_soc` para um veículo que continua a sessão, SOC fora de [0, 1],
contagem negativa ou fracionária e `connected_seconds` fora de [0, `seconds_per_time_step`].

## Ler resultados

| Chamada | Valor |
|---|---|
| `env.mobility.vehicle_soc(ev_id)` | O SOC que o CityLearn tem agora. Em `update` é o SOC com que o veículo inicia o novo intervalo, depois da carga do intervalo terminado e da perda em repouso. |
| `env.mobility.charger_energy_kwh(charger_id)` | Energia AC com sinal do último intervalo terminado, em kWh: positiva na carga, negativa em veículo-para-edifício. Qualquer carregador. |
| `env.mobility.charger_power_kw(charger_id)` | Potência AC média do último intervalo terminado. |
| `env.mobility.external_charger_ids`, `external_vehicle_ids`, `vehicle_ids` | Identificadores. |

## O que o controlador observa

As linhas escritas pelo fornecedor alimentam as observações habituais dos carregadores: estado ligado
e a chegar, contagem até à partida, SOC pedido, capacidade da bateria, hora e SOC de chegada
estimados e o SOC do veículo ligado. Esse SOC é o valor fechado do intervalo anterior, ou o SOC de
chegada ou comunicado no passo atual quando o fornecedor o escreveu antes da ação.
`connected_seconds` e `discharge_soc_floor` limitam a energia, mas não são observados.

## Referência business-as-usual

`evaluate_v2()` reconstrói uma referência BAU a partir do schema. Com um fornecedor, a referência
repete as linhas de calendário externas deste episódio e os SOC definidos pelo fornecedor. Um SOC
comunicado é aplicado com o mesmo valor quando o veículo da referência tinha o mesmo SOC antes da
escrita e, caso contrário, como a mesma variação (limitada a [0, 1]): a referência mantém o seu
próprio histórico de carga e vê o mesmo consumo de condução.

## Exemplo

```python
from citylearn.citylearn import CityLearnEnv


class Scripted:
    def reset(self, env):
        env.mobility.connect('charger_1_1', 'EV_1', soc=0.4, departure_steps=2, required_soc=0.9)

    def update(self, env, time_step):
        mobility = env.mobility
        if time_step == 2:  # o veículo saiu depois do intervalo 1 e está a conduzir
            mobility.away('charger_1_1')
            mobility.set_vehicle_soc('EV_1', mobility.vehicle_soc('EV_1') - 0.1)
        elif time_step == 3:  # chega a outro edifício, ligado durante 450 s de 900 s
            mobility.connect('charger_2_1', 'EV_1', departure_steps=3, required_soc=0.8,
                             connected_seconds=450, discharge_soc_floor=0.3)


env = CityLearnEnv(schema, central_agent=True, mobility_provider=Scripted())
observations, info = env.reset()
while not env.terminated:
    observations, reward, terminated, truncated, info = env.step(policy(observations))
```

`schema` declara os dois carregadores externos e o veículo externo acima; `policy` é o controlador.
