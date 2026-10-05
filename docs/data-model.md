# Modelo de dados

## `bookings`

| Coluna | Descrição |
| --- | --- |
| `booking_key` | SHA-1 da referência da plataforma; sem referência, de pessoa+início+loja |
| `booking_ref` | Referência original do agendamento |
| `worker_name`, `state`, `store`, `role` | Prestador, UF, loja canônica e função |
| `start_at`, `end_at` | Início e término (`YYYY-MM-DD HH:MM:SS`) |
| `scheduled_at`, `started_at`, `completed_at` | Marcos do ciclo de vida |
| `cost`, `computed_hours` | Custo cobrado e horas computadas pela plataforma |
| `status`, `cancelled_at`, `cancel_reason`, `cancelled_by` | Situação e cancelamento |
| `source_file` | Export de origem, para auditoria |

Agendamentos cancelados ficam no banco (aparecem na lista recente e nos totais de
agendamentos) mas não entram em custo, horas, distribuição por hora nem recorrência.

## `revenue`

| Coluna | Descrição |
| --- | --- |
| `revenue_key` | SHA-1 de loja+data+hora+código+quantidade+valor líquido |
| `store` | Loja canônica |
| `sale_date`, `weekday`, `hour` | Data, dia da semana e hora do dia |
| `operation_code` | Código de operação do ERP; só os configurados entram |
| `quantity`, `gross`, `discount`, `net` | Quantidade e valores; devoluções têm `net` negativo |

## `headcount`

| Coluna | Descrição |
| --- | --- |
| `store` | Loja canônica |
| `permanent` | Efetivos da função de referência (ex.: empacotadores CLT) |

## Regras aplicadas no dashboard

- **Turno**: 6–11 Manhã, 12–17 Tarde, 18–23 Noite, demais Madrugada.
- **Custo por hora/turno**: o custo de cada agendamento é repartido pelas horas que ele
  atravessa a partir da hora de início (`metrics.distribute_hours`).
- **Custo / faturamento**: soma do custo ativo ÷ soma do `net` no mesmo recorte de filtros.
- **Recorrência**: dias distintos por semana ISO por prestador; risco pelo pico.
- **Contratação**: `fte = horas / jornada_mensal`; para a função de referência, sugere
  contratar quando o custo sob demanda ≥ `hire_cost_ratio` × custo dos efetivos
  equivalentes, avaliar quando as horas passam de `evaluate_threshold_hours`, e mantém
  sob demanda abaixo de `on_demand_max_hours`.
