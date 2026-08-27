# Projeto CoperCitrus — Coletor de preços

Serviço Python que lê uma lista de produtos em Excel, consulta Google Shopping e Shopee e gera outro Excel com preços, descrição comercial, loja e link de compra.

## Decisão de integração

O projeto não automatiza páginas nem tenta contornar CAPTCHA. A busca do Google usa a [Google Shopping API da SerpAPI](https://serpapi.com/google-shopping-api), porque as rotas de pesquisa/Shopping do Google não permitem coleta automatizada em `robots.txt`. A Shopee usa a API GraphQL oficial do [Programa de Afiliados Shopee](https://affiliate.shopee.com.br/open_api).

Isso reduz quebras por mudanças de HTML, risco de bloqueio e exposição jurídica. As credenciais são lidas apenas de variáveis de ambiente.

## Entrada

Arquivo `.xlsx` com uma coluna obrigatória:

| Coluna | Obrigatória | Uso |
|---|---:|---|
| `Produto` | Sim | Nome principal usado na pesquisa |
| `Marca` | Não | Refina a consulta |
| `Modelo` | Não | Refina a consulta |
| `SKU` | Não | Refina a consulta e mantém rastreabilidade |

Os cabeçalhos não diferenciam maiúsculas, minúsculas ou acentos. Também são aceitos `Nome`, `Item`, `Código` e `Código do produto`.

## Saída

O Excel gerado contém:

- aba `Resultados`: uma linha por oferta, com fonte, preço mínimo/máximo, descrição, loja, avaliação, link, imagem, data e status;
- aba `Resumo`: quantidade de ofertas e menor preço encontrado por produto;
- erros e ausência de resultados registrados por produto e por fonte, sem interromper o restante do lote.

> A “descrição” é o título/snippet comercial disponibilizado pelo provedor. O sistema não abre a página do anúncio para copiar a descrição integral.

## Configuração

Requisitos: Python 3.12+ e uma conta em cada provedor que será usado.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -e .
cp .env.example .env
```

Exporte as credenciais no terminal. O arquivo `.env` está ignorado pelo Git, mas o aplicativo não o carrega automaticamente para evitar leitura acidental de segredos.

```bash
export SERPAPI_KEY="sua-chave"
export SHOPEE_APP_ID="seu-app-id"
export SHOPEE_APP_SECRET="seu-app-secret"
```

Para obter as credenciais da Shopee, a empresa precisa estar aprovada no Programa de Afiliados e habilitar a Open API. Para executar somente uma fonte, configure apenas a credencial correspondente e informe `--providers`.

## Uso

Crie uma planilha-modelo:

```bash
copercitrus-price template produtos.xlsx
```

Consulte as duas fontes:

```bash
copercitrus-price collect produtos.xlsx --output resultados/precos.xlsx
```

Somente Google ou somente Shopee:

```bash
copercitrus-price collect produtos.xlsx --providers google --limit 3
copercitrus-price collect produtos.xlsx --providers shopee --limit 10
```

Opções úteis:

```text
--sheet NOME           aba de entrada; por padrão usa a aba ativa
--limit N              resultados por produto e fonte (1 a 20)
--max-products N       limite de linhas de entrada (padrão: 1000)
--delay SEGUNDOS       espera entre chamadas (padrão: 1,0)
```

## Docker

```bash
docker build -t copercitrus-price-collector .
docker run --rm \
  -e SERPAPI_KEY \
  -e SHOPEE_APP_ID \
  -e SHOPEE_APP_SECRET \
  -v "$PWD/dados:/dados" \
  copercitrus-price-collector collect /dados/produtos.xlsx --output /dados/resultados.xlsx
```

## Testes

Os testes usam respostas simuladas: não consomem créditos nem chamam Google ou Shopee.

```bash
python -m unittest discover -s tests -v
```

## Operação e segurança

- nunca versione `.env`, chaves, planilhas de clientes ou arquivos de resultado;
- use uma identidade/segredo separado por ambiente e rotacione credenciais periodicamente;
- mantenha `REQUEST_DELAY_SECONDS` maior que zero e respeite os limites contratuais dos provedores;
- preços e disponibilidade mudam: considere sempre `Coletado em UTC` antes de tomar uma decisão de compra;
- valide termos, limites e custos dos provedores antes de colocar a rotina em produção.
