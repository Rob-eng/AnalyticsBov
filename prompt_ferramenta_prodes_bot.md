# Prompt para o Antigravity — ferramenta de análise PRODES no bot do Telegram

> Cole o conteúdo abaixo (a partir de "CONTEXTO") na conversa do Antigravity, com o
> repositório do bot aberto.

---

## CONTEXTO

Você vai implementar uma nova ferramenta em um bot de Telegram já existente
(`python-telegram-bot==22.5`). **Atenção a uma premissa importante, verificada no
repositório:** o bot **não** mantém uma tabela com o perímetro de cada imóvel
cadastrado por usuário. O que existe é uma tabela `favorite_locations` com um
**ponto** (lat/lon) salvo por usuário. O perímetro do CAR (polígono) é resolvido
**ao vivo, a cada consulta**, via Google Earth Engine, a partir desse ponto:
`fetch_car_perimeter(lat, lon)` (`app/environmental.py:59`) chama
`find_car_at_coordinate_gee(lat, lon)` (`app/gee_connector.py:697`), que consulta
um `ee.FeatureCollection` por UF no caminho `projects/ee-ranjos/assets/car_{uf}`
e devolve `(geometry_geojson, 'OFFICIAL', cod_imovel)`. Esse é o mesmo fluxo que o
comando `/ambiental` já usa hoje (`receive_env_mode`/`receive_env_location` em
`app/bot.py:1075-1310`) — reaproveite exatamente esse padrão para a nova
ferramenta, não invente um cadastro formal de imóveis que não existe.
(Uma tabela `car_properties`/PostGIS chegou a existir e foi removida da
produção — não a recrie; scripts na raiz que ainda a referenciam,
`migrate_car_to_postgis.py`, `ingest_ms_data.py`, `ingest_mt_wfs.py`, estão
legados/quebrados.)

A nova ferramenta cruza o perímetro do imóvel com os polígonos de desmatamento do
PRODES/INPE e, para cada apontamento encontrado, gera **dois mapas de satélite** —
uma cena **anterior** e uma **posterior** ao apontamento — mais um **PDF** com o
quadro de áreas e a procedência das cenas. O objetivo prático é instruir defesa
administrativa e judicial de autuações por desmatamento: o produto precisa ser
tecnicamente defensável, não apenas bonito.

Todo o processamento de imagem roda no **Google Earth Engine** (já existe service
account com acesso ao EE, credencial em variável de ambiente). **Não** use QGIS,
GDAL local nem download de cenas inteiras.

## CONTEXTO TÉCNICO JÁ LEVANTADO (não redescubra, use isto)

Estas respostas já foram verificadas diretamente no repositório — não gaste tempo
redescobrindo-as, apenas confirme se algo aqui parecer desatualizado:

- **Framework**: `python-telegram-bot==22.5`. Handlers registrados de forma
  monolítica em `app/bot.py` (não há pasta `handlers/`), via `CommandHandler` /
  `ConversationHandler` numa `Application` criada em `create_bot_application()`
  (`app/bot.py:2090`). Entry point em `main.py` (polling, usado em dev) e em
  `app/telegram_webhook.py` (webhook, usado em produção).
- **Banco/ORM**: Postgres no Railway + SQLAlchemy 2.0.43 (`app/models.py`),
  driver `psycopg2-binary`. A extensão **PostGIS já está habilitada**
  (`CREATE EXTENSION IF NOT EXISTS postgis;` em `app/models.py:190`), mas hoje
  **nenhuma tabela usa coluna de geometria** — será a primeira. Não há Alembic;
  "migrações" são `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` dentro de `init_db()`.
- **Fila/worker**: não existe hoje (sem Celery/RQ/arq/Redis). O padrão do
  projeto para não travar o handler é `loop.run_in_executor(None, func, ...)`
  dentro do mesmo processo (ex. `app/bot.py:1174-1178`), mais **APScheduler**
  (`app/scheduler.py`) só para jobs com horário fixo (cron). **Decisão já
  tomada para esta ferramenta**: tabela `prodes_jobs` no Postgres + um job do
  APScheduler fazendo polling — ver seção "ARQUITETURA E NÃO-FUNCIONAIS".
- **Segredos**: variáveis de ambiente direto no serviço Railway (sem `.env` no
  repo). A credencial do Google Earth Engine **já existe e está em uso**: em
  produção via `GEE_CREDENTIALS_JSON` (JSON completo da service account), em
  dev via arquivo `service_account.json` (gitignorado) — ambos lidos em
  `app/gee_connector.py:9-46`.
- **Perímetro do CAR**: não é tabela — é resolvido ao vivo via GEE. Ver
  CONTEXTO acima (`fetch_car_perimeter` / `find_car_at_coordinate_gee`).
- **Deploy**: Docker (`Dockerfile` na raiz) + Railway. `run_all.py` é o
  entrypoint único: em dev sobe dois processos (API FastAPI + bot em polling);
  em produção, se `TELEGRAM_WEBHOOK_URL` estiver setada, o bot roda integrado
  no mesmo processo/event loop da API via webhook. Isso importa para desenhar
  o poller do worker — não assuma dois processos independentes em produção.
- **Storage**: hoje nada é persistido — imagens são geradas em memória
  (`BytesIO`) e enviadas direto ao Telegram, depois descartadas. **Decisão já
  tomada para esta ferramenta**: usar um bucket no Google Cloud Storage
  (`google-cloud-storage` já é dependência do projeto) para os PDFs/PNGs
  gerados, permitindo cache real.
- **PDF**: não existe nenhuma geração de PDF no projeto hoje (nenhuma lib como
  `reportlab`/`fpdf`/`weasyprint` está no `requirements.txt`). Será construído
  do zero — adicione a dependência que escolher.

## ANTES DE ESCREVER QUALQUER CÓDIGO

1. Confirme o contexto técnico acima lendo o código citado; se algo estiver
   desatualizado (o repositório pode ter mudado), me avise antes de prosseguir.
2. Verifique especificamente estes dois pontos, que não foram confirmados com
   certeza durante o levantamento:
   - Se o GeoJSON devolvido por `find_car_at_coordinate_gee` já está em
     EPSG:4674 (SIRGAS 2000) — o código não faz reprojeção explícita, isso é
     presumido por ser o SRC nativo do CAR. Confirme antes de assumir.
   - Em qual projeto GCP os assets do PRODES devem ser publicados, caso decida
     usar assets GEE para algo além da imagem: a credencial atual é do projeto
     `analyticsbov`, mas os assets do CAR hoje vivem em `ee-ranjos` — são
     projetos diferentes.
3. Liste as convenções do projeto que você vai seguir (estrutura de pastas,
   estilo, testes, logging). Note que o projeto hoje não separa
   `handlers/`/`services/`, usa `print(..., flush=True)` com prefixo em vez de
   logging estruturado, e testes ficam soltos na raiz (não numa pasta `tests/`).
4. Faça as perguntas da seção "PERGUNTAS ANTES DE COMEÇAR". **Não invente
   respostas** — se algo não estiver no código, pergunte.
5. Só então proponha o plano de implementação, e espere meu aval antes de codar.

## ESCOPO DA FERRAMENTA

Comando novo, algo como `/prodes`, operando sobre uma localização favorita que o
usuário já tem cadastrada no bot:

1. Usuário aciona o comando e escolhe uma das localizações favoritas dele
   (reaproveite literalmente o seletor de `/ambiental` —
   `receive_env_mode`/`receive_env_location`, `app/bot.py:1075-1310` — não crie
   outro). O bot resolve o imóvel/perímetro correspondente via
   `fetch_car_perimeter(lat, lon)`, do mesmo jeito que `/ambiental` já faz.
2. O bot cruza esse perímetro (geometria devolvida pelo GEE, não uma tabela) com
   a base PRODES carregada no servidor e responde com
   a lista de apontamentos encontrados: ano, classe, área total do polígono e
   área **dentro** do imóvel.
3. Usuário escolhe um apontamento (ou "todos").
4. O bot enfileira a análise e responde imediatamente com um identificador de job.
5. O worker gera, por apontamento: mapa "antes", mapa "depois" e o PDF; envia os
   PNGs no chat e o PDF como documento.

## BASE PRODES NO SERVIDOR

A base do PRODES será carregada uma vez por mim (arquivo vetorial do INPE,
tipicamente GeoPackage ou shapefile do bioma). Implemente:

- Um comando de ingestão (CLI ou script de manutenção, fora do fluxo do bot) que
  lê o arquivo, valida geometrias, reprojeta para o SRC da base do CAR e grava na
  tabela `prodes_apontamentos`, com índice espacial.
- Campos mínimos a preservar: `class_name` (ex.: `d2008`), `main_class`,
  `year`, `image_date`, `satellite`, `sensor`, `path_row`, `uuid`, `source`,
  `geom`. Preserve o `uuid` do INPE — é o que dá rastreabilidade ao apontamento.
- Registre a **versão da base** (o nome do arquivo do INPE traz a data da versão,
  ex.: `prodes_biome_pantanal_v20260528`) numa tabela de metadados, e cite essa
  versão em todo relatório gerado. Sem isso, o laudo não é reproduzível.
- O arquivo do INPE costuma vir com nomes de campo truncados e acentuação
  corrompida. Normalize na ingestão; não propague `Ã¡rea` para o produto final.
- O arquivo já está disponível na raiz do repositório:
  `prodes_biome_pantanal_v20260528.gpkg` (~114 MB). Nenhum código do projeto o
  referencia ainda — o script de ingestão é para ser criado do zero.
- **Importante**: como o perímetro do imóvel não vem de uma tabela (é resolvido
  em tempo de request via GEE, ver CONTEXTO), o cruzamento na prática é
  "geometria solta (GeoJSON devolvido pelo GEE) × tabela `prodes_apontamentos`"
  — por exemplo `ST_Intersects(prodes.geom, ST_GeomFromGeoJSON(:perimetro))` —
  e não um JOIN entre duas tabelas persistidas.

## CRUZAMENTO E CÁLCULO DE ÁREAS

- Selecione os apontamentos que **intersectam** o perímetro, não os que estão
  contidos: um polígono de desmatamento frequentemente atravessa a divisa.
- Para cada apontamento reporte **duas áreas**: a do polígono inteiro e a da
  interseção com o imóvel. São números diferentes e confundi-los invalida a peça.
- Calcule área por método geodésico sobre o elipsoide GRS80 (SIRGAS 2000), não em
  graus e não em projeção Mercator. No PostGIS use `ST_Area(geom::geography)`;
  em Python, `pyproj.Geod(ellps="GRS80").geometry_area_perimeter`. Confira contra
  o campo `area_km` do INPE e registre a divergência se passar de 1%.
- Trabalhe em **EPSG:4674 (SIRGAS 2000)**, sistema geodésico oficial brasileiro.
  O Earth Engine opera em WGS 84; a diferença é submétrica e irrelevante aqui,
  mas **declare** isso no rodapé do relatório em vez de silenciar.

## ESCOLHA DAS CENAS — a parte que não pode ser feita "no olho"

Esta seção contém as regras que separam um produto defensável de um bonito.
Implemente-as literalmente.

### Qual sensor por período

| Período | Coleção no GEE | Resolução |
|---|---|---|
| 1984 – abr/2012 | `LANDSAT/LT05/C02/T1_L2` (Landsat 5 TM) | 30 m |
| 1999 – 2024 | `LANDSAT/LE07/C02/T1_L2` (Landsat 7 ETM+) | 30 m |
| abr/2013 – hoje | `LANDSAT/LC08/C02/T1_L2` (Landsat 8 OLI) | 30 m |
| out/2021 – hoje | `LANDSAT/LC09/C02/T1_L2` (Landsat 9) | 30 m |
| 28/03/2017 – hoje | `COPERNICUS/S2_SR_HARMONIZED` | 10 m |

Regra de seleção: para uma data-alvo, prefira **Sentinel-2 a partir de
28/03/2017** (é quando começa a coleção de reflectância de superfície no GEE —
antes disso só há L1C, que não é comparável); entre 2013 e 2017, Landsat 8;
até 2011, Landsat 5. **Landsat 7 é último recurso**: opera em modo SLC-off desde
2003, com faixas sem dado sempre na mesma posição da cena — mosaicar cenas do
mesmo path/row não preenche essas faixas. Quando só houver Landsat 7 (na prática,
o intervalo nov/2011 – abr/2013), gere o mapa mesmo assim e **imprima a
limitação no rodapé**: "Landsat 7 ETM+ em modo SLC-off; as faixas sem dado são
falha conhecida do sensor desde 2003, não ausência de imagem".

### Nuvem e cobertura: medir sobre o polígono, nunca pela cena

O metadado `CLOUD_COVER` / `CLOUDY_PIXEL_PERCENTAGE` se refere à cena inteira e
engana: uma cena "com 40% de nuvem" pode estar limpa sobre o imóvel, e uma "com
0%" pode ter a única nuvem exatamente em cima do apontamento. Para cada
candidata, calcule por `reduceRegion` sobre a geometria do imóvel:

- **Landsat C2 L2, banda `QA_PIXEL`**: bit 0 = fill, bit 1 = nuvem dilatada,
  bit 3 = nuvem, bit 4 = sombra de nuvem.
- **Sentinel-2, banda `SCL`**: 0 = sem dado; 3 = sombra; 8 e 9 = nuvem;
  10 = cirrus. Opcionalmente cruze com `COPERNICUS/S2_CLOUD_PROBABILITY`
  (s2cloudless) para nuvem fina, que o SCL costuma perder.

Critérios de aprovação, nesta ordem:

1. **Cobertura ≥ 99%** da área do imóvel com pixel válido. Isso descarta cena de
   órbita/ponto vizinho, que cobre uma borda do imóvel e passaria como "sem
   nuvem" porque só conta os pixels que existem. É um erro real e silencioso.
2. **Nuvem ≤ 5%** sobre o imóvel; se nenhuma candidata passar, aceite a melhor
   até 25% e **marque o mapa** com o percentual medido.
3. Empate: prefira a estiagem regional (no Pantanal e Cerrado, junho a setembro —
   menos nuvem e menos área alagada, o que também evita confundir inundação
   sazonal com solo exposto).

Registre no log e no PDF, para cada cena usada: `system:index` (o id da cena),
data, plataforma, sensor, nuvem medida sobre o imóvel e cobertura.

### Qual data é "antes" e qual é "depois"

O ano PRODES não é o ano civil: o mapeamento cobre de agosto do ano anterior a
julho do ano de referência, e o campo `image_date` do apontamento traz a data da
imagem em que o INPE detectou a supressão.

- **Antes** = melhor cena aprovada **anterior ao início da janela de detecção**
  (aproximadamente `image_date` − 12 meses), buscando numa janela de 12 meses para
  trás. É a cena que mostra a situação que antecede o período de detecção.
- **Depois** = melhor cena aprovada **posterior a `image_date`**, buscando numa
  janela de 12 meses para frente.
- Permita que o usuário force outras datas (`/prodes ... antes=2008-05-06`), e
  registre no rodapé quando a data foi escolhida manualmente.
- **Alerta jurídico automático:** se a cena "antes" for anterior a **22/07/2008**,
  destaque isso no relatório — é o marco temporal de área rural consolidada da
  Lei 12.651/2012, art. 3º, IV. Apenas sinalize o fato objetivo (data da cena
  anterior ao marco); não escreva conclusão jurídica no documento.

### Composição em cor natural

- Landsat C2 nível 2: reflectância de superfície = `DN × 0,0000275 − 0,2`.
  Bandas: `SR_B3/B2/B1` no Landsat 5 e 7; `SR_B4/B3/B2` no 8 e 9 — a numeração
  muda entre gerações, trate isso num mapa de bandas por coleção.
- Sentinel-2 `S2_SR_HARMONIZED`: `B4/B3/B2`, dividir por 10000. Essa coleção já
  reverte o deslocamento de −1000 do *processing baseline* 04.00 (cenas após
  25/01/2022), por isso use a versão HARMONIZED e não a antiga `S2_SR`.
- **Realce fixo, idêntico em todas as datas: reflectância 0 a 0,35, gamma 0,85.**
  Não use realce por percentis da cena. Percentil muda o critério de cor a cada
  data e torna a comparação visual contestável — "a imagem antiga parece mais
  escura porque você esticou o contraste diferente" é um argumento que derruba a
  peça. O realce fixo é reprodutível e verificável.

## OS MAPAS

Layout A5 paisagem (210 × 148 mm), 300 dpi, um por data, no modelo já validado:

- Imagem de satélite **recortada no perímetro do imóvel** (fora do imóvel fica
  branco), ocupando a metade esquerda da página.
- Moldura zebrada preta e branca com coordenadas geográficas em grau e minuto
  (ex.: `57°36'W`, `18°18'S`), sem casas decimais.
- Perímetro do imóvel em amarelo; apontamento PRODES em vermelho; ambos só
  contorno, sem preenchimento.
- Quadro ampliado (inset) do apontamento no canto superior direito, com moldura
  preta, retângulo indicador no mapa principal e seta ligando os dois.
- Textos na coluna direita: "Área do apontamento — X,XX ha (Y,YY ha dentro do
  imóvel)", data da cena em destaque, legenda, e nota de procedência com fonte,
  id da cena, sensor, resolução, nuvem medida e versão da base PRODES.

Renderização: `ee.Image.visualize(...).getThumbURL({region, dimensions, format:'png'})`
para trazer só o retângulo de interesse já renderizado, e composição do layout no
servidor com Pillow ou matplotlib. Não tente exportar GeoTIFF nem usar
`Export.image.toDrive` no caminho síncrono — é assíncrono e lento demais para um
bot. Se a resolução do thumbnail não bastar para o imóvel inteiro, mosaique
alguns thumbnails adjacentes em vez de aumentar `dimensions` indefinidamente.

## O PDF

Um documento por análise, contendo: identificação do imóvel (CAR, município, UF,
área), quadro de áreas dos apontamentos, os dois mapas, e uma seção de
procedência com todas as cenas usadas, coleções, datas, nuvem medida, versão da
base PRODES e data de geração. Rodapé com a citação das fontes: PRODES/INPE,
USGS/NASA (Landsat) e Copernicus/ESA (Sentinel-2).

Não há biblioteca de geração de PDF no projeto hoje (nenhuma lib como
`reportlab`/`fpdf`/`weasyprint` está no `requirements.txt`) — adicione a
dependência que escolher. `reportlab` é uma boa opção por combinar bem com o
padrão de composição de imagem via Pillow já usado em `app/environmental.py` e
`app/charts.py`.

## ARQUITETURA E NÃO-FUNCIONAIS

- **Assíncrono.** O handler do Telegram responde em segundos; a análise vai para
  um worker. **Não existe fila hoje no projeto** (sem Celery/RQ/arq/Redis) — o
  padrão atual é `loop.run_in_executor` dentro do mesmo processo, mais
  APScheduler só para jobs com horário fixo. Para esta ferramenta, implemente:
  uma tabela `prodes_jobs` (id, localização/imóvel, apontamento(s) selecionados,
  status, resultado, timestamps) e um job do APScheduler (mesmo mecanismo já
  usado em `app/scheduler.py`) fazendo polling a cada N segundos e processando
  as pendências. Sem Redis — mantenha consistente com o resto do projeto e com
  o ambiente Railway atual. Lembre que em produção o bot roda dentro do mesmo
  processo/event loop da API (via webhook, ver `run_all.py`) — desenhe o
  poller sabendo disso, não assuma processos separados garantidos.
- **Storage.** Hoje nada é persistido no projeto (imagens são geradas em
  memória e enviadas direto ao Telegram, depois descartadas). Para esta
  ferramenta, persista os PDFs/PNGs gerados num bucket do Google Cloud Storage
  (`google-cloud-storage` já é dependência do projeto) — use o projeto GCP já
  configurado (`analyticsbov`) ou crie um bucket dedicado, o que for mais
  simples de provisionar.
- **Idempotência e cache.** Chave por (id da localização/imóvel, uuid do
  apontamento, datas escolhidas, versão da base) — hash dessa chave como nome
  do objeto no bucket. Reexecutar o mesmo pedido devolve o arquivo já gerado
  (buscando no bucket) em vez de gastar quota do EE.
- **Resiliência.** O EE devolve erro transitório com alguma frequência; retry com
  backoff exponencial, no máximo 4 tentativas, e mensagem clara ao usuário quando
  esgotar. Registre a causa.
- **Quota.** Limite a concorrência de requisições ao EE por service account e
  enfileire o excedente. Documente o limite adotado.
- **Credenciais.** Chave da service account só por variável de ambiente ou
  secret manager; nada de arquivo JSON no repositório, nem em log, nem em
  mensagem de erro enviada ao usuário.
- **Limites do Telegram.** Foto até 10 MB e documento até 50 MB por envio; PNG de
  A5 a 300 dpi passa folgado como foto, mas envie também como documento quando o
  usuário pedir qualidade original (o Telegram recomprime fotos).
- **Autorização.** A ferramenta só pode acessar localizações/imóveis do próprio
  usuário. Verifique isso na camada de dados, não só na interface.
- **Log estruturado** com o id de cada cena usada — é o que permite reconstruir a
  análise meses depois, quando alguém contestar o mapa.

## TESTES

- Unitários, com resposta do EE mockada, para: escolha de sensor por data, leitura
  dos bits de `QA_PIXEL`, classes do `SCL`, cálculo de cobertura e nuvem sobre o
  polígono, seleção de "antes"/"depois" a partir de `image_date`, e conversão de
  reflectância.
- Teste de área geodésica contra valor conhecido.
- **Caso-teste de referência (validado manualmente, use como regressão):**
  imóvel CAR `MS-5003207-1B4C085E5E8C452A9708585194C7BFC1`, Corumbá/MS,
  66.607,81 ha. Apontamento PRODES `d2008` com dois polígonos somando
  **473,92 ha** (315,12 + 158,80), `image_date` 26/08/2008, Landsat 5 TM.
  Resultado esperado: área calculada dentro de ±0,5% desses valores; cena "antes"
  aprovada e **anterior a 22/07/2008** (a cena Landsat 5 de 06/05/2008 tem 1,9%
  de nuvem sobre o imóvel e 100% de cobertura); cena "depois" posterior a
  26/08/2008. A cena exata pode variar conforme o filtro; a asserção é sobre o
  intervalo, a cobertura e a área.
- Teste de integração com o EE marcado para rodar sob demanda, não no CI comum.

## O QUE NÃO FAZER

- Não filtre cena por `CLOUD_COVER` da cena e pare por aí.
- Não use realce por percentis, nem ajuste "no olho" o brilho de uma data.
- Não preencha as faixas do Landsat 7 por interpolação: numa peça técnica isso é
  fabricação de dado. Declare a limitação.
- Não escreva conclusão jurídica no relatório ("área consolidada", "não houve
  infração"). O produto apresenta fatos: data da cena, o que a imagem mostra,
  procedência. A conclusão é do responsável técnico e do advogado.
- Não misture polígonos de anos diferentes numa camada rotulada com um único ano.
- Não commite a chave da service account.

## PERGUNTAS ANTES DE COMEÇAR

(Framework/fila/perímetro do CAR/storage já estão respondidos na seção
"CONTEXTO TÉCNICO JÁ LEVANTADO" acima — as perguntas abaixo são as que
realmente dependem de mim.)

1. Qual o volume esperado — quantos usuários e análises por dia? (Isso calibra
   o intervalo do polling da tabela `prodes_jobs` e o limite de concorrência
   contra a quota do EE.)
2. O arquivo `prodes_biome_pantanal_v20260528.gpkg` cobre todo o bioma Pantanal
   ou só MS/MT? A base inicial é só esse bioma, ou outros virão depois? (Muda o
   tamanho da tabela e a janela de estiagem — jun-set — usada como critério de
   desempate; em outros biomas essa janela é diferente.)
3. Nome/projeto do bucket do Google Cloud Storage a usar: criar um bucket novo
   dedicado, ou usar um já existente do projeto `analyticsbov`?
4. O bot já tem internacionalização ou o texto pode ser fixo em português?
   (Hoje o resto do bot é 100% pt-BR sem i18n — presumo que pode seguir fixo,
   mas confirme.)
