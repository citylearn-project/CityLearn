# Datasets REC de Portugal

Quatro datasets sintéticos de comunidades de energia renovável (CER/REC) portuguesas,
com 4, 15, 30 e 100 membros residenciais e comerciais. Abrangem 2023-2024 com passo
de 15 minutos. O consumo dos edifícios e a produção fotovoltaica estão ligados a
pedidos explícitos de carregamento de VE e de aparelhos, meteorologia, preços e
intensidade carbónica. Os cenários acrescentam alterações de membros, limites de
importação restritos, interrupções da rede, falhas de equipamentos e observações em
falta, todos identificados. Os cenários de comparação retiram condições individuais;
cada um difere do cenário principal só na condição que retira. Permitem assim verificar se um controlador continua a
prestar os serviços pedidos, com entradas idênticas e reprodutíveis.

São a edição v3.4 de *Synthetic electricity demand and flexibility datasets for
Portuguese energy communities* (Fonseca et al.), distribuída com o CityLearn a
partir da 3.5.0. As séries temporais são ficheiros Parquet, pelo que o CityLearn
deve ser instalado com o extra `parquet`, `pip install "citylearn[parquet]"`, que
junta o pyarrow.

Versão inglesa: [../portugal_rec_datasets.md](../portugal_rec_datasets.md).

## Datasets

REC-4 e REC-15 são residenciais. REC-30 e REC-100 acrescentam membros comerciais,
carregamento no local de trabalho e veículos visitantes.

| | REC-4 | REC-15 | REC-30 | REC-100 |
|---|---:|---:|---:|---:|
| Nome do dataset | `pt_rec_4` | `pt_rec_15` | `pt_rec_30` | `pt_rec_100` |
| Membros residenciais / comerciais | 4 / 0 | 15 / 0 | 24 / 6 | 80 / 20 |
| Ligações trifásicas | 0 | 1 | 7 | 28 |
| Soma dos limites de importação (kW) | 28,8 | 107,0 | 324,3 | 1 168,4 |
| Membros com FV / capacidade (kWp) | 1 / 3,8 | 4 / 16,8 | 10 / 89,5 | 36 / 312,5 |
| Membros com bateria / capacidade (kWh) | 1 / 10,2 | 1 / 10,2 | 3 / 25,6 | 20 / 220,2 |
| Carregadores (kW) | 2 (3,7-7,4) | 6 (3,7-7,4) | 15 (3,7-22,1) | 65 (3,7-22,1) |
| VE: residentes / visitantes | 2 / 0 | 6 / 0 | 9 / 10 | 37 / 48 |
| Aparelhos: controlados / fixos | 2 / 5 | 10 / 18 | 19 / 27 | 64 / 84 |
| Tamanho da descarga | 7 MB | 13 MB | 84 MB | 113 MB |

São os inventários fixos; Topology, Combined e All-in acrescentam ou retiram membros e
equipamentos. A maioria dos membros tem ligação monofásica com limite de importação
de 6,9 kW; algumas casas maiores e membros comerciais têm ligações trifásicas até 82,8 kW.

## Cenários

Um cenário é um schema que escolhe os membros, o período, os ficheiros de dados e o
programa de eventos. Os caminhos são relativos à pasta do dataset, pelo que os
cenários partilham os mesmos registos. O `schema.json` na raiz de cada dataset é um
alias do seu cenário Normal.

| Cenário | Dataset | Schema em `evaluation/` | Condições |
|---|---|---|---|
| REC-4 Normal | `pt_rec_4` | `rec_4.json` | Condições normais |
| REC-15 Normal | `pt_rec_15` | `rec_15.json` | Condições normais |
| REC-30 Normal | `pt_rec_30` | `rec_30_normal.json` | Condições normais |
| REC-30 Topology | `pt_rec_30` | `rec_30_topology.json` | Alterações de membros e equipamentos |
| REC-30 Safety | `pt_rec_30` | `rec_30_safety.json` | Limites de importação restritos em membros escolhidos |
| REC-30 Robustness | `pt_rec_30` | `rec_30_robustness.json` | Perturbações e interrupções da rede |
| REC-30 Combined | `pt_rec_30` | `rec_30_combined.json` | Topology, Safety e Robustness em conjunto |
| REC-100 Normal | `pt_rec_100` | `rec_100_normal.json` | Condições normais |
| REC-100 All-in | `pt_rec_100` | `rec_100_allin.json` | Alterações de membros, perturbações, interrupções da rede e resposta da procura |

Seis cenários de comparação em `evaluation/references/` retiram condições individuais.
Cada um difere do cenário principal só na condição que retira; todos os outros
ficheiros, incluindo todos os pedidos de serviço, são partilhados. No disturbances
retira em conjunto as perturbações e as interrupções da rede.

| Comparação | De | Alteração |
|---|---|---|
| `rec_30_combined_no_disturbances`, `rec_100_allin_no_disturbances` | Combined, All-in | Retira perturbações e interrupções da rede |
| `rec_30_combined_nominal_limits` | Combined | Repõe os limites de importação dos três membros restritos |
| `rec_100_allin_no_dr` | All-in | Retira os pedidos de resposta da procura |
| `rec_30_topology_frozen_2024`, `rec_100_allin_frozen_2024` | Topology, All-in | Mantém as alterações de membros de 2023 e suprime as de 2024 |

Para ajustar em 2023 e avaliar em 2024, termine a janela de simulação no passo 35039,
o último intervalo de 2023 em UTC.

O cenário Safety só restringe limites de importação; não modela tensão, proteções ou
segurança da rede por fase. Os cenários Robustness, Combined e All-in identificam as
perturbações; em estudos de deteção de falhas, essas etiquetas devem ficar ocultas ao controlador.

## Carregar

Passe o nome do dataset para usar o cenário Normal. A primeira chamada descarrega o
dataset para a cache do CityLearn:

```python
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv('pt_rec_30', episode_time_steps=96)
```

Carregue outro cenário a partir da pasta do dataset em cache:

```python
from pathlib import Path
from citylearn.data import DataSet

root = Path(DataSet().get_dataset('pt_rec_30')).parent
env = CityLearnEnv(str(root/'evaluation'/'rec_30_combined.json'), episode_time_steps=96)
```

Todos os cenários usam a interface de entidades e têm o mercado comunitário ativo.
Comece com uma janela curta: as corridas completas de dois anos sem referência BAU
demoraram de 6 a 127 minutos, do REC-4 ao REC-100, no CityLearn 3.3.0. Uma janela com
*n* estados guardados permite *n* - 1 transições.

## Convenções

- **Calendário:** 70 176 instantes de início de intervalo, de 1 de janeiro de 2023 às
  00:00 UTC a 31 de dezembro de 2024 às 23:45 UTC. Os dias civis de Lisboa têm 92 ou
  100 intervalos nas mudanças de hora.
  As colunas `month`, `hour` e `minutes` estão em hora civil de Lisboa, tal como os
  instantes exportados, que levam o seu desvio UTC (`2023-06-27T03:00:00+01:00`). A
  coluna `day_type` codifica fins de semana e feriados como 1 e segunda a sexta-feira
  como 2 a 6, e não 1 segunda-feira a 7 domingo.
- **Unidades:** consumo, FV e perfis de programas em kWh por intervalo (multiplicar por
  quatro para kW médio); capacidade das baterias em kWh; limites de potência em kW;
  preços em EUR/kWh; intensidade carbónica em kg CO2e/kWh; SOC como fração.
  As observações em falta usam -9999.
- **Campos anuais:** os campos de resumo anual dos catálogos referem-se a 2023; as séries cobrem os dois anos.
- **Sessões de carregamento:** uma sessão de carregamento vai do intervalo de chegada
  até ao de partida, exclusive. Sessões ainda ligadas no fim do registo são censuradas
  à direita; o fim do ficheiro não é um prazo.
- **Informação antecipada:** por omissão, cada carregador anuncia o veículo que chega
  uma hora (quatro intervalos) antes, com a hora e o SOC de chegada previstos; à
  ligação, cada sessão indica a hora de partida e o SOC alvo.
- **Preços:** a compra à rede é `max(preço OMIE diário português / 1000, 0)` EUR/kWh,
  sem tarifas de acesso, impostos ou margens de retalho. As trocas locais liquidam a
  80 % desse preço e a exportação para a rede vale zero.
- **Identificadores:** os identificadores de membros e equipamentos só são únicos dentro de cada dataset.

## Conteúdo das pastas

O CityLearn inclui apenas os ficheiros que os schemas leem:

| Caminho | Conteúdo |
|---|---|
| `schema.json` | Alias do cenário Normal |
| `evaluation/*.json`, `evaluation/references/*.json` | Cenários principais e de comparação |
| `evaluation/native_inputs/<cenário>/` | Séries dos membros, carregadores e eventos de cada cenário |
| `evaluation/campaign_2024/` | Entradas da campanha de 2024 |
| `shared/` | Meteorologia, preço OMIE e intensidade carbónica |
| `catalogs/`, `deferrables/` | Serviços elétricos e perfis de aparelhos lidos pelos schemas |

As tabelas de dados descritas no artigo (usos finais dos membros, sessões de
carregamento, pedidos de aparelhos, catálogos), os registos de proveniência, os
checksums e a documentação estão no depósito do dataset, não no CityLearn. O «2023» em alguns
caminhos internos vem do gerador.

## Reportar resultados

Reporte energia, custo e carbono juntamente com o serviço prestado: um consumo menor
pode vir de um veículo que partiu abaixo do alvo ou de um aparelho que nunca funcionou.
Avalie o serviço pedido a pedido, comparando a energia entregue a cada VE com a pedida
e o arranque de cada aparelho com a sua janela e prazo.

| Limitação | Consequência |
|---|---|
| Inventários desenhados; membros partilhados entre datasets | Adequados a comparações controladas; não representam as CER portuguesas e os datasets não são amostras independentes. |
| Alvos de carregamento e janelas de aparelhos prescritos | Os requisitos de serviço são pressupostos de modelação, não preferências medidas. |
| Consumo residencial 30-36 % acima das medições SHEERM | A autossuficiência é provavelmente menor do que nas casas medidas; normalize ou teste a sensibilidade quando os níveis absolutos importam. |
| Ligações de VE mais longas do que nas sessões medidas | Pode favorecer controladores baseados em agendamento. |
| SOC de chegada prescrito em cada sessão de carregamento | A continuidade das deslocações entre dias não é testada. |
| Regras de preço experimentais; intensidade carbónica média | Os resultados não são poupanças com uma tarifa real nem reduções marginais de emissões. |
| Taxas de eventos derivadas de comunidades piloto | Estudos de robustez devem também fazê-las variar. |

## Licença e atribuição

Os dados e a documentação originais dos autores estão licenciados sob
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt). Dê o devido crédito,
indique a licença e assinale as alterações. A CC BY 4.0 não é uma licença global para
a coleção: o material derivado de fontes de terceiros mantém os seus próprios termos.

| Fonte | Utilização | Termos |
|---|---|---|
| [OMIE](https://www.omie.es/), preços diários portugueses | Referência de preço transformada (convertida, limitada a zero); não são observações originais do OMIE | Termos de informação pública do OMIE; creditar a fonte |
| [REN](https://datahub.ren.pt/en/api-instructions), [REE](https://www.ree.es/en/datos/apidata) e [APA](https://apambiente.pt/clima/fator-de-emissao-de-gases-de-efeito-de-estufa-para-eletricidade-produzida-em-portugal) | Série calculada de intensidade carbónica | Termos dos fornecedores; respostas brutas não incluídas |
| [PVGIS](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en), JRC da Comissão Europeia | Irradiância e meteorologia | Termos de utilização livre do JRC; agradecimento pedido |
| [ERA5](https://doi.org/10.24381/cds.adbb2d47) via [Open-Meteo](https://open-meteo.com/) | Humidade e meteorologia | CC BY 4.0; creditar Copernicus C3S e Open-Meteo |
| [E-REDES](https://www.e-redes.pt/), perfis de consumo padrão | Prior histórico das habitações | Termos do fornecedor; folhas de origem não incluídas |
| [SHEERM](https://doi.org/10.5281/zenodo.13972210) | Calibração e comparação do consumo doméstico | CC BY 4.0 |
| [REFIT](https://doi.org/10.5281/zenodo.5063428), Murray e Stankovic | Programas de aparelhos domésticos | CC BY 4.0 |
| [Building Data Genome 2](https://doi.org/10.1038/s41597-020-00712-x) | Apenas estatísticas de calibração comercial | Licença BDG2 de origem; sem extratos horários |
| [SINTEF, carregamento residencial de VE](https://doi.org/10.5281/zenodo.13896176), [FIKElectricity](https://doi.org/10.1038/s41597-023-02698-8) | Comparação | CC BY 4.0 |

O depósito do dataset contém o mapa de licenças por ficheiro, a atribuição completa,
o gerador e as ferramentas de reconstrução, o dicionário de dados e os relatórios de
validação.

## Citação

Quando usar os dados, cite o dataset e o seu artigo:

- Fonseca et al., *Synthetic electricity demand and flexibility datasets for
  Portuguese energy communities*, edição v3.4 do dataset. Zenodo, DOI
  10.5281/zenodo.24182353 (reservado; só resolve depois de o registo ser
  publicado, por isso ainda não tem ligação).
- Fonseca et al., "Synthetic electricity demand and flexibility datasets for
  Portuguese energy communities", *Scientific Data* (em revisão).
