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

## Docker

```bash
docker build -t copercitrus-rpa .
docker run --rm --ipc=host \
  -v "$PWD/dados:/dados" \
  copercitrus-rpa collect /dados/produtos.xlsx --output /dados/resultados.xlsx
```

## Testes

Os testes usam cards simulados e nao acessam Google ou Shopee.

```bash
python -m unittest discover -s tests -v
```

## Uso responsavel

Automacao de sites deve ser executada somente quando houver autorizacao e de acordo com os termos e instrucoes automatizadas de cada pagina. Os termos atuais do Google restringem acesso automatizado que contrarie instrucoes legiveis por maquina. Antes de colocar o lote em producao, valide a permissao de uso com o responsavel juridico/contratual e mantenha intervalos conservadores entre pesquisas.
