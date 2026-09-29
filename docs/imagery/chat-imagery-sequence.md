# Imagery wire contract: `/api/chat` sequence

Where contract imagery is built, validated, serialized and read. Classes: [class-diagram.md](class-diagram.md). Why: [ADR 0001](../adr/0001-imagery-wire-contract.md).

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend
    participant API as POST /api/chat<br/>stream_chat
    participant G as LangGraph agent
    participant T as show_imagery /<br/>show_planet_imagery
    participant P as Planet or Sentinel-2<br/>provider
    participant W as wire.from_payload
    participant R as readers<br/>(widget config, session block,<br/>view context)

    FE->>API: ChatRequest(query, thread_id)
    API->>G: astream(state, stream_mode="updates")
    G->>T: tool call(target_date, ...)
    T->>T: build_request(state) → ImageryRequest

    alt show_planet_imagery and Planet covers the AOI for a complete month
        T->>P: PlanetImageryProvider.get_imagery(request)
    else otherwise (show_imagery, or Planet not servable → fallback)
        T->>P: Sentinel2ImageryProvider.get_imagery(request)
    end
    Note over P: builds PlanetImagery / Sentinel2Imagery.<br/>Pydantic validates it here (strict: extra = forbid),<br/>so a missing or stray field fails on the backend
    P-->>T: ImageryProviderResult(imagery: Imagery | None)

    T->>T: provider_command: imagery.model_dump(mode="json")
    T-->>G: Command(update={messages, imagery})
    G-->>API: {"tools": {messages, imagery}}
    API-->>FE: pack({"node": "tools", "update": dumps(update)})
    Note over FE: phase 1 of the rollout: read v1 when "period"<br/>is present, legacy otherwise, then switch on provider

    opt a later turn reads state["imagery"]
        R->>W: from_payload(state["imagery"])
        alt contract v1
            W-->>R: PlanetImagery | Sentinel2Imagery
            R->>R: use label() / model_dump(mode="json")
        else legacy flat payload
            W-->>R: None
            R->>R: legacy fallback (flat keys)
        end
    end
```

## Notes

- **One writer.** `provider_command` (`src/agent/tools/show_imagery.py:48`) is the only code that puts imagery into the state update. JSON mode matters, because langchain `dumps` turns a `date` into a `"not_implemented"` placeholder.
- **Validation happens when the model is built, not when it's dumped.** Every provider builds a strict contract model, and `provider_command` just serializes it.
- **Readers try the contract first.** `from_payload` returns `None` for legacy payloads, which still arrive from replayed checkpoints and older widget configs. Phase 3 of the rollout converts legacy on read, and the fallbacks go away in phase 5.
- **Not yet done:** `DashboardWidgetCreateRequest.validate_map_config` (`src/api/schemas.py:724`) checks only `tile_url`, not the contract.
- **Payload reference for the frontend:** [wire-contract-schema.md](wire-contract-schema.md). **Deploy order:** [rollout-plan.md](rollout-plan.md).
