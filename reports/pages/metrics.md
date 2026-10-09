---
title: Metric definitions
---

Every KPI on this site, and every answer from the AI analyst, comes from one definition in the dbt semantic layer
(MetricFlow). Change a definition there and it changes everywhere.

```sql catalog
select label, name, description, dimensions from ridgeline.metric_catalog order by name
```

<DataTable data={catalog} search=true rows=all>
  <Column id=label title="Metric"/>
  <Column id=name title="Name in code"/>
  <Column id=description title="Definition" wrap=true/>
  <Column id=dimensions title="Can be broken down by" wrap=true/>
</DataTable>
