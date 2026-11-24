# Geração PV e colunas de previsão para datasets

`citylearn.pv_dataset` escreve `solar_generation` e as colunas de irradiância `*_predicted_{1,2,3}` de um dataset antes de uma simulação. O `CityLearnEnv` lê as colunas como antes, pelo que a ferramenta não acrescenta custo em execução.

Versão em inglês: [../pv_dataset_tools.md](../pv_dataset_tools.md).

Instale a dependência opcional com `pip install citylearn[pvlib]`. Nenhuma função abre uma ligação de rede, exceto `fetch_pvgis_tmy` (`--pvgis-tmy`) e `quartz_pv_forecast`.

## Gerar

```console
python -m citylearn.pv_dataset generate DATASET_DIR --out NEW_DIR     --latitude 30.27 --longitude -97.74 --tilt 25 --azimuth 180 --loss-percent 14     --utc-offset-hours -6 --forecast statistical --seed 0
```

O dataset é copiado para `NEW_DIR`. Cada `Building_*.csv` recebe um novo `solar_generation` e o `weather.csv` recebe novas colunas de irradiância prevista. O ficheiro `pv_provenance.json` regista o modelo, a localização, os parâmetros PV, o método de previsão e a semente. Em Python, `generate(..., specs={'Building_1': PVSpec(tilt=20), '*': PVSpec()})` define parâmetros por edifício.

- **Unidade.** `solar_generation` é a potência AC média em W por kW de PV instalado (modo `per_kw` do CityLearn). A `nominal_power` do schema escala-a, pelo que `--kwp` não altera o ficheiro.
- **Modelo.** pvlib `ModelChain.with_pvwatts` com montagem fixa inclinada, perda angular física, temperatura da célula SAPM em estrutura aberta, `gamma_pdc = -0.004 /K`, rácio DC/AC de 1,2 e uma perda escalar (por omissão 14 %) aplicada à saída AC. A posição solar usa o ponto médio do intervalo.
- **Meteorologia.** O `weather.csv` do dataset (`direct_solar_irradiance` é lida como DNI, `diffuse_solar_irradiance` como DHI, `ghi = dhi + dni cos(zenith)`), ou o TMY do PVGIS com `--pvgis-tmy`. Os ficheiros do CityLearn não têm ano nem localização: as datas vêm de `month` e `hour` (ficheiros horários; `--start` para os restantes). `--utc-offset-hours` indica o desvio de hora padrão do dataset (por omissão `longitude / 15`, a hora solar média, que difere da zona civil até cerca de 1 h; defina-o explicitamente).

## Colunas de previsão

A ferramenta indica em `pv_provenance.json` e na saída padrão qual a previsão executada.

- **Quartz.** O Quartz Solar Forecast usa dados NWP do Open-Meteo e devolve previsão apenas para os últimos 90 dias; para datas anteriores usa silenciosamente dados de reanálise. `quartz_pv_forecast` recusa essas datas, pelo que o Quartz não gera colunas de previsão para os períodos históricos dos datasets incluídos. As dependências fixadas do Quartz (`xarray==2022.12.0`, NumPy 1) também entram em conflito com os ambientes atuais do CityLearn: execute-o num ambiente separado.
- **Modelo estatístico (por omissão).** `predicted_k[t] = x[t+k] exp(e_k[t])` para `x` a irradiância direta e difusa, com erros logarítmicos AR(1) de desvio-padrão `sigma[k]` e correlação de atraso 1 `rho`. Os valores noturnos ficam em 0. `scripts/manual/fit_quartz_forecast_error.py` ajusta `sigma` e `rho` a partir de previsões recentes do Quartz face a uma simulação pvlib com irradiância ERA5 do Open-Meteo (`--forecast-params` recebe o seu JSON). O valor por omissão (`method: default-assumption`) não é ajustado e está assim identificado na proveniência. Uma execução para latitude 51,5 e longitude -0,1, 14 dias de novembro de 2026 (156 amostras diurnas, limiar 50 W/kW), deu `sigma = 0,59` para todos os horizontes e `rho = 0,25`, um erro maior e menos persistente do que o valor por omissão (0,15 a 0,25, `rho = 0,8`); por isso o valor por omissão não é ajustado ao Quartz e uma quinzena de inverno num só local não justifica substituí-lo. Os valores ajustados comparam o Quartz com uma simulação baseada em reanálise, não com PV medido.

## Validação

```console
python -m citylearn.pv_dataset validate DATASET_DIR --latitude 30.27 --longitude -97.74 --tilt 20 --utc-offset-hours -6
```

imprime o r de Pearson, o rácio de energia, o nMBE e o nRMSE do pvlib face ao `solar_generation` do dataset. Para `Building_1` de `citylearn_challenge_2022_phase_all` (latitude e longitude de Austin, Texas, assumidas, inclinação 20, UTC-6, horário) o r é 0,82 e a energia do pvlib é 95 % da energia do dataset. A concordância é limitada pelo dataset: a sua `diffuse_solar_irradiance` chega a 1017 W/m2, valor que uma componente difusa não atinge, pelo que as colunas de irradiância não são uma entrada limpa para o pvlib.
