# Cost catalogue

Sourced cost, price, finance and emission figures for deep-geothermal heating and cooling plants,
collected 2026-11-01. [sources.csv](sources.csv) has 74 rows: 33 verified, 25 secondary and 16
placeholder.

**What it is.** Reference data for any gemini project. Each row gives a value, its price year, its
2015 value, its source with a verbatim quote, and the case key it would feed.

**What it is not.** It is not a set of defaults. No code in `gemini/` reads it, and no value here
applies by itself. A project copies the values it uses into its own scenario (`case.json`) and cites
the `id`. Several rows often share one key: choosing between them is a project decision.

## Columns

`path` is the key a scenario uses for the value, spelled as in
`inputs/examples/hackathon_2026/case.json`. It is empty when no case key takes the figure. `in_case`
is what that example case held for the key on 2026-11-01, so the gap between the example and the
evidence is visible. It is a snapshot, and the example is not changed to match. `note` says when the
units of a row and its key differ, in which case the two numbers cannot be compared directly.

`value` and `value_2015` share one unit, written in gemini's spelling. Four units have no entry in
the unit table, because no case key takes them: `EUR/MW/yr`, `EUR/MW/m`, `EUR/MW/km/yr` and `USD/W`.

## Status

- **verified**: the figure was read in the official source, dataset or report it is credited to.
- **secondary**: the figure is real and quoted, but comes from a thesis, a citing paper, an abstract,
  a proxy for a different item, or code.
- **placeholder**: no verified source. The row stays, with no value and empty source fields, so the
  gap is visible.

## Conversion to 2015

`value_2015 = value * 100 / HICP(price_year)`, with the euro-area all-items annual average index,
2015 = 100: Eurostat `prc_hicp_aind`, unit `INX_A_AVG`, coicop `CP00`, geo `EA`, dataset updated
2026-02-06, saved in [data/](data/).

| 2008 | 2010 | 2012 | 2013 | 2014 | 2015 | 2017 | 2019 | 2023 | 2025 |
|---|---|---|---|---|---|---|---|---|---|
| 91.38 | 93.14 | 98.05 | 99.38 | 99.81 | 100.00 | 101.78 | 104.80 | 123.15 | 128.75 |

The index ends in 2025, so 2026 prices use the 2025 index and their 2015 values run high. Where a
source gives no price year, the `note` says which year was assumed. HICP is consumer inflation, not a
capital-goods index: DEA notes that pipe prices rose faster than inflation, so 2015 values deflated
from 2025 are approximate. USD rows and rows without money have no 2015 value.
`tests/unit/test_cost_sources.py` recomputes every conversion within 0.5 %. The grid factors can be
reread from `data/ember_yearly_EU_CO2_intensity.csv`.

## Summary

| Group | Verified | Secondary | Placeholder | Main values |
|---|---:|---:|---:|---|
| drilling and wells | 9 | 3 | 0 | 1239 / 1833 / 2063 EUR/m at 2300 / 3000 / 4000 m (2013); plant 1.34-2.46 EUR/W heat |
| pumps | 0 | 4 | 0 | ESP 800,000 EUR per unit; 0.593 USD/W at 500 kW |
| heat pumps | 2 | 2 | 1 | 0.95 EUR/W heat at 10 MW (2025); Lorenz efficiency 0.50, range 0.4-0.6 |
| chillers | 0 | 7 | 0 | absorption 0.288, compression 0.196, adsorption 1.018 EUR/W (2023) |
| heat exchangers and coolers | 4 | 1 | 0 | DH station 0.14 EUR/W; dry cooler 0.049-0.107, wet tower 0.022-0.027 EUR/W (2014) |
| pipes and network | 3 | 0 | 0 | distribution 819-1479 EUR/m (2025); transmission 63 EUR/MW/m |
| gas treatment | 0 | 1 | 2 | hydrocarbon separation reserve 1 MEUR (2013) |
| operating costs | 8 | 4 | 13 | plant fixed O&M 55,000-60,000 EUR/MW/yr, 3.2 % of capex (DEA 2025) |
| energy prices | 0 | 0 | 0 | none collected |
| sale prices | 3 | 3 | 0 | heat 85-98 EUR/MWh (2019); cold 81-110 EUR/MWh |
| finance | 2 | 0 | 0 | discount rate 0.04 financial, 0.03 social, real |
| emissions | 2 | 0 | 0 | EU electricity 209.21 g/kWh (2025) |

Evidence against the example case, in 2015 prices where the key and the rows share a unit:

| Key | `in_case` | Evidence |
|---|---|---|
| `capex.drilling` | 1239.13 EUR/m | 1247-2075 EUR/m drilled, rising with depth |
| `capex.heat_pump` | 0.73786 EUR/W | 0.738 EUR/W, the same figure |
| `capex.absorption_chiller` | 0.3 EUR/W | 0.234-0.438 EUR/W |
| `capex.compression_chiller` | 0.3 EUR/W | 0.159 EUR/W |
| `capex.adsorption_chiller` | 0.3 EUR/W | 0.827-0.859 EUR/W |
| `capex.cooler` | 0.1 EUR/W | 0.022-0.107 EUR/W |
| `capex.pipe` | 500 EUR/m | 636-1149 EUR/m |
| `capex.degasser` | 1,000,000 EUR | 1,006,240 EUR, a subsidy reserve |
| `revenue.heat` | 60 EUR/MWh | 81-115 EUR/MWh, consumer tariffs |
| `revenue.cold` | 60 EUR/MWh | 81-110 EUR/MWh |
| `discount_rate` | 0.05 | 0.03-0.04, real |
| `emissions.CO2.electricity` | 300 g/kWh | 209-212 g/kWh |

## Gaps

- 19 rows have no case key: the 11 plant benchmarks for capex and O&M, the drill location, the
  variable O&M, the ESP replacement interval, abandonment, and four heat pump rows. The Lorenz rows
  feed the plant parameter `HeatPump.lorenz_fraction`, not the case.
- No row covers `opex.electricity`, `opex.gas`, `opex.co2`, `capex.boiler`, `capex.chp`, `lifetime`,
  `allocation.heat_cost_share` or `emissions.CH4.gwp`, so the energy prices group is empty.
- No source was found for flare or gas makeup capex, scale and corrosion inhibitor prices, geothermal
  waste disposal, or fixed O&M per equipment kind. Sources give plant totals only.
- No source gives an ESP or injection pump in EUR/W of shaft power, a district cooling tariff for an
  EU country, or a current EU-wide heat price. DEA has no chiller or district cooling sheet.

## Known doubtful rows

- **DEA fixed O&M of 500,000 EUR/MW/yr** (sheets 45.1.a and 45.2.a) looks like a catalogue error,
  against 60,000 in 45.1.b and about 20 % of capex. No row carries it. The same sheets are titled
  1200 m while their depth row reads 2000 m (`plant-dea-2025-1200m-15mw`).
- **Drilling** figures are 2013 prices and rise with depth: 1,239 / 1,833 / 2,063 EUR/m at
  2,300 / 3,000 / 4,000 m. The per-doublet reading is inferred. Check a resulting plant total against
  the DEA and PBL plant benchmarks.
- **ECN curve rows** are per metre of depth of a project total, while gemini prices `capex.drilling`
  on the measured length of each well, so for a doublet divide by two.
- **Arpagaus 10-80 K lift range** is not confirmed: the paper could not be opened, and it stays a
  placeholder. The 2018 slides give 130 to 40 K on p.13 and 130 to 25 K in their conclusions on p.30.
- **Chiller prices** are secondary only. The ECOS authors say few reliable prices exist, and large
  district-scale units are not covered.
- **PBL rows** state costs at the expected investment decision, 2026 plus one year (p.4, p.96); the
  geothermal chapter names no price year. 2026 is assumed, so their 2015 values run high.
- **Springer rows** (`drilling-location-surface`, `esp-unit-2019`, `opex-plant-share-of-capex`,
  `esp-replacement-interval`) keep the 2026-11-01 reading, but the paper ends at a sign-in page and
  could not be rechecked. The ECN thesis p.21 confirms the 5 %, and DEA note E the 5 years; the
  300,000 and 800,000 EUR and their assumed 2019 price year have no second source.
- **DEA transport catalogue** p.27 says 2020 prices, while the workbook Index says DH data is in 2025
  EUR. The workbook is used.
- **Regulation 480/2014 Art. 19** applies to the 2014-2020 funds and was read in the UK-retained text.

## Source documents

DEA PDFs and workbooks are not kept here, for size and licence. Every row has its public URL.

- [Danish Energy Agency, Technology Data for Generation of Electricity and District Heating, v0019](https://ens.dk/en/analyses-and-statistics/technology-data-generation-electricity-and-district-heating)
- [Danish Energy Agency, Technology Data for Energy Transport, v8](https://ens.dk/en/analyses-and-statistics/technology-data-transport-energy)
- [PBL, Eindadvies basisbedragen SDE++ 2026](https://www.pbl.nl/downloads/pbl-2026-eindadvies-sde-plus-plus-2026-5698-1pdf)
- [Mijnlieff et al., Geothermal energy and support schemes in The Netherlands, EGC 2013](https://www.nlog.nl/sites/default/files/presentation_egc_mijnlieff_et_al_2013.pdf)
- [Straathof, Costs of Deep Geothermal Energy in the Netherlands, ECN-O--12-043](https://publications.tno.nl/publication/34632176/5j1C7E/o12043.pdf)
- [Economic and fault stability analysis of geothermal field development, Geothermal Energy 2021, Table 4](https://link.springer.com/article/10.1186/s40517-021-00193-0/tables/4)
- [ECOS 2023, Techno-economic comparison of a solar absorption chiller and photovoltaic compression chiller](https://proceedings.com/content/069/069564-0239open.pdf)
- [arXiv 1910.07028, citing Kim and Infante Ferreira 2008](https://arxiv.org/pdf/1910.07028)
- [bigEE Buildings Guide, active cooling options](https://bigee.net/en/buildings/guide/services/options/active/OASC/testing_b/impacts/)
- [The cost of manufacturing adsorption chillers, 2023](https://www.research.ed.ac.uk/en/publications/the-cost-of-manufacturing-adsorption-chillers-2/)
- [GEOPHIRES-X, Economics.py](https://raw.githubusercontent.com/NREL/GEOPHIRES-X/main/src/geophires_x/Economics.py)
- [IEA SHC Task 48, Heat Rejection Systems for solar cooling](https://task48.iea-shc.org/data/sites/1/publications/Task%2048%20-%20Activity%20A3%20Final%20Report%20-%20November%20%202014.pdf)
- [ACM, maximale warmtetarieven 2026](https://www.acm.nl/nl/publicaties/acm-stelt-maximale-warmtetarieven-2026-vast)
- [Copenhagen Economics, District Heating Tariffs in Europe](https://open.overheid.nl/documenten/ronl-ec66e0006b7e0acc22629091d63b448a4af5b0c3/pdf)
- [Statistics Norway, Increased district heating](https://www.ssb.no/en/energi-og-industri/artikler-og-publikasjoner/increased-district-heating)
- [IIR, District Cooling and the customers' alternative cost](https://iifiir.org/en/fridoc/district-cooling-and-the-customers-alternative-cost-4643)
- [Commission Delegated Regulation (EU) No 480/2014, Art. 19](https://www.legislation.gov.uk/eur/2014/480/chapter/II/section/III/data.html)
- [Better Regulation Toolbox, December 2025](https://commission.europa.eu/document/download/9c8d2189-8abd-4f29-84e9-abc843cc68e0_en?filename=BR%20toolbox%20-%20December%202025.pdf)
- [Arpagaus et al., High temperature heat pumps, Chillventa 2018](https://www.ost.ch/fileadmin/dateiliste/3_forschung_dienstleistung/institute/ies/projekte/projekte_tes/204_bfe_annex_48/arpagaus_et_al._2018_high_temperature_heat_pumps_chillventa_congress_nuernberg_15_oct_2018.pdf)
- [Ember Yearly Electricity Data](https://storage.googleapis.com/emb-prod-bkt-publicdata/public-downloads/yearly_full_release_long_format.csv)
- [Eurostat HICP, prc_hicp_aind](https://ec.europa.eu/eurostat/databrowser/product/page/prc_hicp_aind)

## Adding a row

1. Read the figure in the source itself and copy the sentence or table cell into `quote`.
2. Pick a short, stable `id` of the form `<item>-<source>-<year>-<detail>`; never reuse or change an
   existing one, since projects cite it.
3. Write `value` and `unit` in gemini's spelling and say any change of unit in `conversion`.
4. Compute `value_2015` as above with the row's `price_year`, and leave it empty for USD or no money.
5. Spell `path` as in the case file, leave it empty if no key fits, and fill `in_case` from that file.
6. Put the row in its group, set `status`, and run `pytest tests/unit/test_cost_sources.py`.
