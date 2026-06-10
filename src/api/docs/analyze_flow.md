# Analyze Flow

`POST /api/analyze` returns a `Job` immediately and runs data fetching and chart
generation as a background task. The client polls `GET /api/jobs/{id}` until
the job completes, then follows `resource_url` to retrieve the results.

## Sequence

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant Analyze as routers/analyze.py<br/>POST /api/analyze
    participant Jobs as routers/jobs.py<br/>GET /api/jobs/{id}
    participant Insights as GET /api/insights/{id}
    participant BG as AnalysisJobRunner (background)
    participant Analytics as GFW Analytics API
    participant DB as Database

    FE->>Analyze: POST /api/analyze<br/>{aois, dataset_id, start_date, end_date}
    Analyze->>DB: create Job (status=pending)
    Analyze-->>FE: {id, type, status: "pending", resources: []}
    Analyze--)BG: start background task

    par background task
        BG->>DB: update Job (status=running)
        BG->>Analytics: POST analytics endpoint<br/>(dataset, aois, date range)
        Analytics-->>BG: raw data (area_ha, emissions, etc.)
        BG->>BG: TCLChartGenerator → chart dicts
        BG->>DB: create Insight + InsightCharts
        BG->>DB: create JobResource<br/>{resource_url: "/api/insights/{id}"}
        BG->>DB: update Job (status=completed)
    and client polling
        loop until status=completed
            FE->>Jobs: GET /api/jobs/{id}
            alt pending or running
                Jobs-->>FE: 200 + Retry-After: 1<br/>{status: "pending"|"running", resources: []}
                Note over FE: wait 1s then retry
            else completed
                Jobs-->>FE: 200<br/>{status: "completed", resources: [{resource_url}]}
            end
        end
    end

    FE->>Insights: GET /api/insights/{id}
    Insights-->>FE: {charts: [{title, chart_type, x_axis, y_axis, chart_data}]}
```

## Example

**Request**
```json
POST /api/analyze
{
  "aois": [{"source": "gadm", "src_id": "BRA", "subtype": "country"}],
  "dataset_id": 4,
  "start_date": "2020-01-01",
  "end_date": "2022-12-31"
}
```

**Immediate response** (`status: pending`)
```json
{
  "id": "3ac814f6-5065-4da2-beb5-b683c2740c02",
  "type": "analysis",
  "status": "pending",
  "thread_id": null,
  "resources": [],
  "created_at": "2026-06-08T16:21:51.777511"
}
```

**Poll response** (`status: completed`)
```json
{
  "id": "3ac814f6-5065-4da2-beb5-b683c2740c02",
  "type": "analysis",
  "status": "completed",
  "resources": [
    {
      "id": "aa774e4b-f866-4f47-976b-fd4d42dd68f7",
      "resource_url": "/api/insights/e7021a4c-21ae-440a-a847-874cca10890c",
      "status": "completed",
      "created_at": "2026-06-08T16:21:52.480180"
    }
  ]
}
```

**Follow resource_url**
```json
GET /api/insights/e7021a4c-21ae-440a-a847-874cca10890c

{
  "id": "e7021a4c-21ae-440a-a847-874cca10890c",
  "insight_text": "",
  "charts": [
    {
      "title": "Annual Tree Cover Loss",
      "chart_type": "bar",
      "x_axis": "tree_cover_loss_year",
      "y_axis": "area_ha",
      "chart_data": [
        {"tree_cover_loss_year": 2020, "area_ha": 2603663.52, ...},
        {"tree_cover_loss_year": 2021, "area_ha": 2323559.31, ...},
        {"tree_cover_loss_year": 2022, "area_ha": 2571705.05, ...}
      ]
    },
    {
      "title": "Annual GHG Emissions from Tree Cover Loss",
      "chart_type": "bar",
      "x_axis": "tree_cover_loss_year",
      "y_axis": "carbon_emissions_MgCO2e",
      "chart_data": [...]
    }
  ]
}
```
