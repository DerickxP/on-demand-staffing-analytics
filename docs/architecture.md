# Arquitetura

## Camadas

1. **ETL** (`staffing_analytics.etl`): lê planilhas, normaliza e grava no SQLite. Não sabe
   nada sobre apresentação.
2. **Analytics** (`staffing_analytics.analytics`): regras de negócio em funções puras
   (`metrics.py`), relatório de terminal (`report.py`) e exportação do dashboard
   (`export.py`). Lê apenas o banco.
3. **Dashboard** (`staffing_analytics.dashboard.assets`): HTML, CSS e JavaScript
   embutidos em um arquivo único. Reproduz as regras de `metrics.py` no navegador para
   permitir filtros cruzados sem servidor.

`cli.py` amarra as camadas em subcomandos e `config.py` entrega um `Settings` imutável.

## Fluxo

```text
data/bookings/*.xlsx ──consolidate──► data/bookings_consolidated.xlsx
        (dedupe exato, CONFLITOS, validações V1-V4, abas auxiliares carregadas)

bookings_consolidated.xlsx ──load-bookings──► bookings + headcount
        (colunas tolerantes, datas mistas, catálogo de lojas, trava de futuro,
         dedupe pessoa+início+loja, chave de conteúdo, INSERT OR IGNORE)

data/revenue.xlsx ──load-revenue──► revenue
        (clientes excluídos, códigos de venda e devolução, lojas excluídas/ignoradas,
         apelidos, detecção de renomeação, consolidação do histórico já gravado)

staffing.db ──dashboard──► output/dashboard.html
staffing.db ──report──────► texto no terminal
```

## Por que a consolidação é conservadora

Exports mensais se sobrepõem por alguns dias, então duplicatas exatas são esperadas e
podem ser descartadas com segurança. Já a mesma referência com dados diferentes pode ser
uma correção legítima (status atualizado) ou um erro de export; descartar em silêncio
esconderia o problema. Por isso as duas linhas ficam e a referência é listada em
`CONFLITOS`. O dedupe final por pessoa+início+loja acontece na carga, mantendo a primeira
ocorrência.

## Por que o catálogo de lojas mora no ETL e não no dashboard

Os dois sistemas (plataforma e ERP) nomeiam lojas de forma diferente e o ERP renomeia
cadastros. Se o dashboard fizesse o cruzamento por nome, cada mudança quebraria as
visões. O catálogo resolve nomes na entrada, o banco só conhece nomes canônicos, e o
dashboard cruza custo e receita por igualdade simples.

## Tratamento de erros

- Configuração inválida: `ConfigError` com o campo; a CLI encerra com código 2.
- Validação da consolidação: `ConsolidationError`; o arquivo de saída não é gerado.
- Aba ou coluna obrigatória ausente: `ValueError` com o nome esperado.
- Datas não convertidas, agendamentos futuros, lojas não mapeadas e prováveis
  renomeações são registrados no log com contagens, nunca descartados em silêncio.
