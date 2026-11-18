# Dinâmica das sessões de carga

Por omissão, um carregador de EV entrega a potência comandada durante todo o tempo em que um veículo
está ligado, do primeiro ao último segundo da sessão. As sessões reais são mais lentas: o veículo tem
de ser acoplado e o carregador e o veículo negociam antes de a potência fluir, um novo *set-point* só
tem efeito após um atraso, a potência varia a uma taxa limitada e a transferência termina antes de o
veículo partir. Cinco atributos opcionais do carregador modelam estas fases. Com passos de controlo
curtos (um minuto ou menos) alteram visivelmente a energia de uma sessão; com passos horários contam
sobretudo nas paragens curtas.

## Atributos

Definem-se em `buildings.<edifício>.chargers.<carregador>.attributes`. Atributos omitidos mantêm o
comportamento atual: sem atraso e rampa ilimitada.

| Atributo | Unidade | Significado |
|---|---:|---|
| `start_delay_seconds` | s | Tempo após a ligação do veículo antes de a energia fluir: acoplamento mais o arranque da comunicação. |
| `setpoint_delay_seconds` | s | Tempo após o início de um passo antes de o comando desse passo ter efeito; entretanto mantém-se o *set-point* anterior. Um atraso maior do que o passo leva o comando para um passo seguinte. |
| `ramp_up_kw_per_second` | kW/s | Taxa máxima de subida do valor absoluto da potência. |
| `ramp_down_kw_per_second` | kW/s | Taxa máxima de descida do valor absoluto da potência. Uma inversão entre carga e descarga passa por zero: desce a esta taxa e depois sobe à taxa de subida. |
| `stop_delay_seconds` | s | Tempo antes de uma partida conhecida em que o carregador termina a transferência: o *set-point* passa a zero e a potência desce em rampa. |

```json
"chargers": {
  "hub_1": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": "chargers/hub_1.csv",
    "attributes": {
      "max_charging_power": 11.0,
      "max_discharging_power": 10.0,
      "start_delay_seconds": 51.0,
      "setpoint_delay_seconds": 4.0,
      "ramp_up_kw_per_second": 3.35,
      "ramp_down_kw_per_second": 3.31,
      "stop_delay_seconds": 22.0
    }
  }
}
```

## Valores medidos

O exemplo usa valores medidos. Descrevem equipamento concreto; escolha valores para os carregadores
que modela.

| Fase | Valor | Fonte |
|---|---:|---|
| Acoplamento automático (robótico) | 24 s | Walzel, Hirz, Brunner e Kreutzer (2019), *Robot-Based Fast Charging of Electric Vehicles*, SAE Technical Paper 2019-01-0869, doi:10.4271/2019-01-0869: ligação robótica cerca de 24 s, desligação cerca de 22 s. |
| Arranque da comunicação (DC, ISO 15118-2 / DIN SPEC 70121) | 27 s mediana (quartis 12,05 s e 43,08 s) | Watt, Bani Shamseh e Gadamsetty (2025), *Quantifying Time to Charge*, National Charging Experience Consortium (ChargeX), NREL, julho de 2025: tempo do início do SLAC até Power Delivery em 162 sessões de teste (mediana 26,99 s). |
| Atraso de ativação do *set-point* | 4 s local, 7 s remoto | Zecchino, Thingvad, Andersen e Marinelli (2019), *Test and Modelling of Commercial V2G CHAdeMO Chargers to Assess the Suitability for Grid Services*, World Electric Vehicle Journal 10(2):21, doi:10.3390/wevj10020021. |
| Rampas de subida / descida | 3,35 / 3,31 kW/s (cerca de 1,8 a 9,2 kW/s nos ensaios) | Zecchino et al. (2019), como acima. |
| Desacoplamento automático (robótico) | 22 s | Walzel et al. (2019), como acima. |

`start_delay_seconds = 24 + 27 = 51` cobre o acoplamento robótico e o arranque DC; `stop_delay_seconds = 22`
cobre o desacoplamento robótico. Uma sessão ligada manualmente usaria apenas o tempo de arranque.

## Modelo

Os tempos contam-se a partir do início de um passo de controlo com duração `seconds_per_time_step`.

- Uma sessão começa quando o veículo se liga, no início do seu primeiro passo. Um [fornecedor de
  mobilidade](mobility_provider.md) pode indicar `connected_since_seconds` ao iniciar uma sessão: um valor
  positivo significa que o veículo se ligou esse tempo antes do passo (o tempo decorrido conta para o
  atraso de arranque), um valor negativo que se liga esse tempo depois do início do passo (sem energia
  antes disso). Uma sessão já em curso quando um episódio começa é tratada como começando no início do
  episódio.
- O comando de um passo é emitido no início do passo e tem efeito `setpoint_delay_seconds` depois. O
  primeiro comando de uma sessão tem o mesmo atraso; até lá o *set-point* é zero.
- A energia flui a partir de `start_delay_seconds` após a ligação. A potência segue o *set-point* dentro
  dos limites de rampa.
- A partida é conhecida pela contagem até à partida (uma contagem de 1 significa que o veículo sai no
  fim do passo) ou por uma ligação que termina dentro do passo (`connected_seconds`). A transferência
  termina `stop_delay_seconds` antes. A potência é zero quando o veículo está desligado.

A potência AC é portanto linear por troços no tempo. A energia de um passo é o seu integral exato, uma
soma de trapézios sobre os troços lineares, calculada em forma fechada sem subpassos
(`citylearn.internal.charger_dynamics.integrate_step`). As partes de carga e de descarga de um passo
são aplicadas à bateria por ordem temporal. A eficiência de cada parte lê-se na curva de eficiência
do carregador à potência média da parte, e os limites de potência e a eficiência dependente da
potência da bateria referem-se à duração da parte. Os limites da bateria (bateria cheia, profundidade
de descarga, o `discharge_soc_floor` de uma sessão, a curva de potência da bateria) podem reduzir mais
a energia; não alteram o estado de rampa do carregador, que segue o perfil comandado.

A auditoria de partidas de EV e os KPI de viabilidade das partidas repetem um comando de carga máxima
com o mesmo perfil, pelo que um objetivo inatingível por causa do arranque ou da paragem conta como
inviável.

## O que o controlador observa

Nada de novo. As observações e os espaços de ação não mudam. O controlador vê as observações habituais
do carregador (estado de ligação, contagem até à partida, SOC pedido, SOC do veículo ligado) e a
energia efetivamente entregue no último intervalo (`last_charged_kwh` na interface flat, a energia
aplicada no *feedback* de ações da interface entity). O estado de rampa, o *set-point* pendente e o
tempo de arranque restante não são observados, mas resultam dos parâmetros documentados, dos comandos
anteriores do próprio controlador e do histórico de ligações observado, pelo que não é exposta
informação sobre o futuro. `connected_seconds` e `connected_since_seconds`, que um fornecedor de
mobilidade pode conhecer antes de o controlador agir, limitam a energia mas não são observações.

Com a dinâmica de sessão ativa, um carregador sem veículo ligado regista energia comandada zero nesse
passo.
