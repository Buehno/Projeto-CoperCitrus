# Projeto CoperCitrus — RPA de pesquisa de preços

Aplicacao Python que le uma lista de produtos em Excel, abre um Chromium controlado pelo Playwright e pesquisa diretamente nas paginas publicas do Google Shopping e da Shopee.

Nao utiliza SerpAPI, API de Afiliados da Shopee nem qualquer outra API de resultados.

## O que o RPA entrega

O Excel de saida possui tres abas:

- `Resultados`: todos os anuncios encontrados, com preco, marca, nome, quantidade/embalagem, loja e link;
- `Produtos similares`: alternativas com similaridade intermediaria em relacao ao produto solicitado;
- `Resumo`: total de ofertas, produtos compativeis, similares e menor preco por item.

### Campos principais

| Campo | Origem |
|---|---|
| Produto solicitado | Planilha de entrada |
| Quantidade solicitada | Planilha de entrada |
| Nome encontrado | Card visivel no marketplace |
| Marca encontrada | Validada no titulo do anuncio |
| Quantidade/embalagem | Extraida de textos como `10 un`, `500 ml` ou `2 kg` |
| Preco | Card visivel no marketplace |
| Link de compra | Link presente no card |

`Quantidade solicitada` representa quanto a CoperCitrus pretende comprar. `Quantidade/embalagem encontrada` representa o volume identificado no anuncio. O RPA nao inventa estoque quando o site nao exibe essa informacao.

## Planilha de entrada

| Coluna | Obrigatoria | Uso |
|---|---:|---|
| `Produto` | Sim | Nome principal da pesquisa |
| `Marca` | Nao | Refina a busca e a validacao |
| `Modelo` | Nao | Refina a busca e a validacao |
| `SKU` | Nao | Mantem rastreabilidade |
| `Quantidade` | Nao | Quantidade solicitada para compra |

Tambem sao reconhecidos cabecalhos como `Nome`, `Item`, `Codigo`, `Qtd` e `Qtde`.

## Instalacao no Windows 11 / Git Bash

Requisitos: Python 3.12+ e Git Bash.

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -e .
python -m playwright install chromium
cp .env.example .env
```

O arquivo `.env` serve como referencia. As configuracoes podem ser exportadas no terminal; nenhuma credencial e necessaria.

## Uso

Crie uma planilha-modelo:

```bash
copercitrus-price template produtos.xlsx
```

Primeiro teste com o navegador visivel:

```bash
copercitrus-price collect produtos.xlsx --headed --limit 5
```

Depois execute em segundo plano:

```bash
copercitrus-price collect produtos.xlsx --output resultados/precos.xlsx
```

Somente uma fonte:

```bash
copercitrus-price collect produtos.xlsx --providers google
copercitrus-price collect produtos.xlsx --providers shopee
```

Para usar o Chrome ou Edge instalado:

```bash
copercitrus-price collect produtos.xlsx --headed --browser-channel chrome
copercitrus-price collect produtos.xlsx --headed --browser-channel msedge
```

## Classificacao dos resultados

- `COMPATIVEL`: similaridade de 80% ou mais;
- `SIMILAR`: similaridade entre 50% e 79,9%;
- `DIVERGENTE`: similaridade abaixo de 50%.

A marca e o modelo informado na entrada aumentam a precisao. A aba `Produtos similares` contem somente os resultados classificados como `SIMILAR`.

A classificacao e a similaridade continuam sendo calculadas, mas nao aparecem na aba `Resultados`: as colunas `Classificacao`, `Similaridade (%)` e `Possivel produto parecido` foram removidas dessa aba, junto com o realce de cor de `SIMILAR` e `DIVERGENTE`.

## Produtos excluidos do relatorio

`PRODUTOS_EXCLUIDOS`, em `src/copercitrus_price_collector/spreadsheet.py`, lista produtos que nao devem sair no Excel por apresentarem valor discrepante na coleta. A comparacao ignora acentos, maiusculas e pontuacao. Para excluir outro item, acrescente o nome do produto ao conjunto.

## Bloqueios e mudancas de pagina

O RPA usa seletores alternativos porque o HTML dos marketplaces pode mudar. Caso detecte CAPTCHA, trafego incomum, verificacao humana ou acesso negado, a fonte e registrada como erro e o lote continua.

O projeto nao tenta:

- resolver ou contornar CAPTCHA;
- usar modo stealth, proxies rotativos ou falsificacao de identidade;
- acessar paginas autenticadas;
- extrair dados que nao estejam visiveis ao usuario.

## Banco de dados (PostgreSQL)

Alem do Excel, cada execucao pode ser registrada em PostgreSQL. A gravacao e
ativada apenas pela presenca da variavel `DATABASE_URL`; sem ela o RPA funciona
exatamente como antes.

### Tabelas

O schema e criado sozinho, de forma idempotente (`CREATE TABLE IF NOT EXISTS`),
na subida da API ou no primeiro `collect`. Nao existe passo manual de migracao.

| Tabela | Conteudo |
|---|---|
| `coletas` | Uma linha por execucao: origem (`cli`/`api`), status, inicio/fim, totais e os parametros usados em `jsonb` |
| `buscas` | Uma linha por produto x fonte pesquisada: dados da entrada, termo pesquisado, status (`OK`, `SEM_RESULTADO`, `ERRO`) e a mensagem de erro |
| `resultados` | Uma linha por oferta encontrada: titulo, marca, quantidade/embalagem, preco, moeda, link, vendedor, similaridade e classificacao |

`buscas` referencia `coletas` e `resultados` referencia `buscas`, ambos com
`ON DELETE CASCADE`: apagar uma coleta remove todo o historico dela.

### Comandos

```bash
copercitrus-price db check   # testa a conexao
copercitrus-price db init    # cria as tabelas
copercitrus-price db runs    # lista as ultimas coletas
```

A coleta grava no banco automaticamente quando `DATABASE_URL` esta definida:

```bash
export DATABASE_URL="postgresql://usuario:senha@host:5432/banco"
copercitrus-price collect produtos.xlsx
```

Para gerar apenas o Excel, ignorando o banco:

```bash
copercitrus-price collect produtos.xlsx --no-db
```

O banco e um registro paralelo: se o PostgreSQL estiver fora, a coleta emite um
aviso e o Excel continua sendo gerado normalmente.

## Dashboard

`copercitrus_price_collector.web:app` e a aplicacao que fica no ar. Ela e
**somente leitura**: le o PostgreSQL e apresenta os insights. Nao existe
entrada de dados pela web — nenhuma rota `POST`, `PUT` ou `DELETE`.

A ingestao continua sendo o CLI (`copercitrus-price collect`), que grava nas
mesmas tabelas. Isso mantem o Playwright fora do processo web.

O dashboard mostra:

- indicadores gerais: produtos, ofertas, buscas, coletas, preco medio e erros;
- ofertas por fonte e aderencia ao produto pedido (`COMPATIVEL`/`SIMILAR`/`DIVERGENTE`);
- **maior economia potencial**: produtos com maior diferenca entre a oferta mais cara e a mais barata;
- **menor preco por produto**, com o titulo e o link do proprio anuncio;
- buscas que nao retornaram oferta, com o motivo.

| Rota | Uso |
|---|---|
| `GET /` | O dashboard (HTML) |
| `GET /health` | Healthcheck; `200` com banco ok, `503` degradado |
| `GET /api/resumo` | Indicadores, ofertas por fonte e classificacao (JSON) |
| `GET /api/precos` | Menor preco por produto (JSON) |
| `GET /api/coletas` | Historico de coletas (JSON) |
| `GET /api/coletas/{id}/resultados` | Ofertas de uma coleta (JSON) |
| `GET /api/docs` | Documentacao interativa |

Titulos, vendedores e links vem de paginas de terceiros: o HTML e escapado e
somente URLs `http`/`https` viram link.

Localmente:

```bash
uvicorn copercitrus_price_collector.web:app --reload
```

## Deploy no Railway

1. Crie o servico apontando para este repositorio. O `railway.json` ja seleciona
   o `Dockerfile`, define o healthcheck em `/health` e o start command.
2. No projeto, adicione um banco **PostgreSQL**. O Railway injeta `DATABASE_URL`
   no servico automaticamente — nao e preciso copiar nada.
3. Faca o commit. O deploy sobe, as tabelas sao criadas na primeira conexao e o
   healthcheck responde `200`.

Variaveis opcionais: `RESULT_LIMIT`, `REQUEST_DELAY_SECONDS`,
`RPA_BROWSER_TIMEOUT_SECONDS`. `PORT` e `RPA_HEADLESS` ja vem prontos.

Como a aplicacao nao escreve nada, alimente o banco rodando o CLI com a mesma
`DATABASE_URL` do servico.

## Docker

A imagem sobe o dashboard por padrao:

```bash
docker build -t copercitrus-rpa .
docker run --rm --ipc=host -p 8000:8000 \
  -e DATABASE_URL="postgresql://usuario:senha@host:5432/banco" \
  copercitrus-rpa
```

Para usar o CLI, basta sobrescrever o comando:

```bash
docker run --rm --ipc=host \
  -v "$PWD/dados:/dados" \
  copercitrus-rpa \
  copercitrus-price collect /dados/produtos.xlsx --output /dados/resultados.xlsx
```

## Testes

Os testes usam cards simulados e um banco falso: nao acessam Google, Shopee nem
PostgreSQL.

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

## Uso responsavel

Automacao de sites deve ser executada somente quando houver autorizacao e de acordo com os termos e instrucoes automatizadas de cada pagina. Os termos atuais do Google restringem acesso automatizado que contrarie instrucoes legiveis por maquina. Antes de colocar o lote em producao, valide a permissao de uso com o responsavel juridico/contratual e mantenha intervalos conservadores entre pesquisas.
