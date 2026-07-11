# Arquitectura de Metis

**Versión 0.1.0** · [MIT License](https://opensource.org/licenses/MIT) · Orquestador de razonamiento multiagente sobre cualquier LLM

Metis es la **capa de razonamiento y orquestación** en el [ecosistema alexar76](ECOSYSTEM.md). Envuelve cualquier endpoint de modelo — Ollama local, APIs compatibles con OpenAI, Anthropic o nodos worker distribuidos — con un stack cognitivo estructurado: Understanding Council, Disagreement-Gated Pipeline Depth (DGPD), Mixture-of-Agents (MoA) en capas, ejecución de herramientas/MCP, verificación, memoria, medición económica y seguridad de producción.

Metis es **solo API** (sin interfaz de chat integrada). Los clientes se conectan mediante el endpoint compatible con OpenAI `/v1/chat/completions`, la clase Python `Metis` o el CLI `metis`. Use VS Code Continue, Cursor o `curl` contra el endpoint serve.

---

## Tabla de contenidos

1. [Design Principles](#design-principles)
2. [System Overview](#system-overview)
3. [Query-to-Answer Data Flow](#query-to-answer-data-flow)
4. [Core Components](#core-components)
   - [Metis Exoskeleton](#metis-exoskeleton)
   - [Router](#router)
   - [Understanding Council](#understanding-council)
   - [Confidence Gate](#confidence-gate)
   - [DGPD — Pipeline Depth L0–L3](#dgpd--pipeline-depth-l0l3)
   - [Layered Mixture-of-Agents](#layered-mixture-of-agents)
   - [Verifier](#verifier)
   - [Agent Loop](#agent-loop)
   - [Memory and RAG](#memory-and-rag)
   - [Search Pipeline](#search-pipeline)
   - [Tool Registry](#tool-registry)
   - [MCP Integration](#mcp-integration)
5. [Distributed Cluster](#distributed-cluster)
6. [Economy and Billing](#economy-and-billing)
7. [Security Layers](#security-layers)
8. [OpenAI-Compatible API](#openai-compatible-api)
9. [IDE Integration](#ide-integration)
10. [Module Registry and Providers](#module-registry-and-providers)
11. [Ecosystem Integration](#ecosystem-integration)
12. [Configuration Reference](#configuration-reference)
13. [Component Tables](#component-tables)
14. [Related Documentation](#related-documentation)

---

## Principios de diseño

| Principio | Implementación |
|-----------|----------------|
| **Agnóstico al modelo** | Cada módulo del cerebro se resuelve en un `ModelSlot` — Ollama, OpenAI-compat, Anthropic o nodo remoto |
| **Comprensión fail-closed** | El confidence gate bloquea rutas de resolución costosas cuando la confianza o ambigüedad de `TaskSpec` es insuficiente |
| **Profundidad por desacuerdo** | DGPD escala el coste del pipeline solo cuando los agentes paralelos no coinciden |
| **Seguridad nunca omitida** | Escaneo de inyección, palabras clave sensibles y tokens canary fuerzan L3 en entradas riesgosas |
| **Límites no confiables** | Salida de herramientas y MCP envuelta en `<untrusted>`; protección SSRF en HTTP saliente |
| **Gasto observable** | Medición de uso por llamada con puertas de presupuesto de sesión y exportación webhook |

---

## Descripción general del sistema

La clase `Metis` (alias `CognitiveExoskeleton`, `Superbrain`) es el único punto de entrada de orquestación. Posee memoria de trabajo, episódica y vectorial; construye el registro de herramientas integrado; carga opcionalmente herramientas MCP; y conecta la medición económica en cada llamada `run()`.

```mermaid
flowchart TB
    subgraph clients [Clients]
        CLI[metis_CLI]
        PyAPI[Python_Metis_API]
        OpenAI[OpenAI_compat_clients]
    end

    subgraph apiLayer [API_Layer]
        FastAPI[FastAPI_app]
        Bridge[OpenAIMetisBridge]
        Auth[Bearer_auth]
    end

    subgraph exo [Metis_Exoskeleton]
        DepthGate[DepthGate_DGPD]
        Router[Query_router]
        BudgetGate[Session_budget_gate]
        Meter[UsageMeter]
        Council[Understanding_Council]
        ConfGate[Confidence_gate]
        MoA[Layered_MoA]
        AgentLoop[Agent_loop]
        Verifier[Judge_verifier]
        Memory[Memory_RAG]
    end

    subgraph tools [Tool_Layer]
        CodeInterp[Code_interpreter]
        WebSearch[Web_search]
        MCP[MCP_tools]
    end

    subgraph llm [LLM_Providers]
        Local[Ollama_local]
        Cloud[OpenAI_DeepSeek_Anthropic]
        Nodes[Distributed_nodes]
    end

    CLI --> exo
    PyAPI --> exo
    OpenAI --> FastAPI
    FastAPI --> Auth
    Auth --> Bridge
    Bridge --> exo

    exo --> DepthGate
    DepthGate --> Router
    Router --> BudgetGate
    BudgetGate --> Meter
    Meter --> Council
    Council --> ConfGate
    ConfGate --> MoA
    ConfGate --> AgentLoop
    MoA --> Verifier
    AgentLoop --> Verifier
    AgentLoop --> tools
    Memory --> Council
    Memory --> MoA

    Council --> llm
    MoA --> llm
    AgentLoop --> llm
    Verifier --> llm
    Router --> llm
```

---

## Flujo de datos de consulta a respuesta

Cada solicitud pasa por sanitización, enrutamiento, verificación opcional de presupuesto y ejecución específica de ruta. Las ejecuciones exitosas de council/agent pueden persistir en memoria vectorial a largo plazo.

```mermaid
sequenceDiagram
    participant Client
    participant API as OpenAI_API
    participant Exo as Metis
    participant DGPD as DepthGate
    participant Rtr as Router
    participant ECO as EcosystemBridge
    participant UC as Council
    participant CG as ConfidenceGate
    participant MoA as Layered_MoA
    participant VR as Verifier
    participant MEM as VectorMemory

    Client->>API: POST /v1/chat/completions
    API->>Exo: run(query, route)
    Exo->>DGPD: sanitize_and_gate(query)
    DGPD-->>Exo: sanitized, depth, security_reason
    Exo->>Rtr: route_query(config, query)
    Rtr-->>Exo: RouteMode
    Exo->>ECO: check_budget_before_route
    ECO-->>Exo: CostEstimate or BudgetExceeded

    alt fast_or_L0
        Exo->>Exo: single LLM completion
    else thinking
        Exo->>Exo: extended_thinking
    else council_or_agent
        Exo->>MEM: context_for(query)
        Exo->>UC: run_understanding_council
        UC-->>Exo: TaskSpec
        Exo->>CG: evaluate_confidence_gate
        alt needs_clarification
            CG-->>Client: NEEDS_CLARIFICATION
        else proceed
            Exo->>MoA: run_layered_moa + agentic_rag
            MoA-->>Exo: answer
            Exo->>VR: verify_answer
            alt verify_fail
                VR-->>Exo: feedback
                Exo->>MoA: retry with feedback
            else verify_pass
                VR-->>Exo: passed
                Exo->>MEM: add(Q, A)
                Exo-->>Client: SUCCESS + answer
            end
        end
    end
```

### Valores de estado de ejecución

| Estado | Significado |
|--------|---------|
| `success` | Respuesta producida (el verificador puede emitir advertencias tras reintentos máximos) |
| `needs_clarification` | El confidence gate o council señaló ambigüedades sin resolver |
| `error` | Presupuesto excedido o fallo irrecuperable |

---

## Componentes principales

### Exoesqueleto Metis

`metis/exoskeleton.py` define `Metis`, la clase de orquestación. Responsabilidades clave:

- **Inicialización** — crea `WorkingMemory`, `EpisodicMemory`, `VectorMemory`, `ToolRegistry` integrado, `DepthGate`, `EscalationPolicy` y opcionalmente `EcosystemBridge`
- **`run(query, route=None)`** — sanitiza la entrada, enruta, mide el uso, delega a `_execute`, finaliza el informe económico
- **Manejadores de ruta** — `_run_fast`, `_run_thinking`, `_run_council`, `_run_agent`

```python
# Punto de entrada principal
result = await Metis(config).run("Explain CAP theorem", route=RouteMode.COUNCIL)
```

`ExoskeletonResult` carries `answer`, `status`, `route`, `task_spec`, `verify_score`, `depth`, `clarifications`, and `metadata` (usage, security_reason, proposer_agreement, etc.).

### Enrutador

`metis/router/classifier.py` selects among four `RouteMode` values when `default_route: council`:

| Mode | When |
|------|------|
| `fast` | Factual, low ambiguity, no tools |
| `thinking` | Razonamiento sin herramientas — cadena de pensamiento extendida |
| `agent` | Código, búsqueda, APIs, marcadores oracle/MCP |
| `council` | Planificación, alta ambigüedad, tareas multipaso |

El router LLM (rol del módulo `router`) devuelve JSON con `mode`, `task_type` y `scores`. Las anulaciones deterministas se aplican cuando `tools_needed ≥ 7` o `ambiguity ≥ 7`. Los marcadores oracle/ecosistema (`oracle`, `vdf`, `verifiable`, etc.) enrutan a `agent` cuando las herramientas MCP están habilitadas. Si el router LLM falla, se ejecuta un fallback heurístico.

### Understanding Council

`metis/agents/council.py` runs **six parallel isolated agents** (no peer visibility — reduces sycophantic drift), then a synthesizer:

```mermaid
flowchart LR
    Query[User_query] --> P1[intent_parser_a]
    Query --> P2[intent_parser_b]
    Query --> P3[intent_parser_c]
    Query --> CE[constraint_extractor]
    Query --> AH[ambiguity_hunter]
    Query --> RT[red_team]
    P1 --> Synth[synthesizer]
    P2 --> Synth
    P3 --> Synth
    CE --> Synth
    AH --> Synth
    RT --> Synth
    Synth --> TS[TaskSpec]
```

| Agent | Role |
|-------|------|
| `intent_parser_a/b/c` | Interpretación paralela de intención (modelos heterogéneos si se configuran) |
| `constraint_extractor` | Restricciones explícitas e implícitas, requisitos de formato |
| `ambiguity_hunter` | Lecturas alternativas y problemas sin resolver |
| `red_team` | Interpretación adversarial — trampas y lecturas incorrectas |
| `synthesizer` | Fusión en un único `TaskSpec` con puntuación de confianza |

El resultado es un `TaskSpec` (`metis/schemas/task_spec.py`) — el contrato entre comprensión y resolución:

| Field | Purpose |
|-------|---------|
| `goal` | Lo que el usuario quiere como salida |
| `constraints` / `non_goals` | Límites y exclusiones |
| `ambiguities` | Problemas que requieren resolución o entrada del usuario |
| `success_criteria` | Cómo juzgar una respuesta correcta |
| `required_tools` | `code`, `search`, or none |
| `confidence` | 0–1 synthesizer confidence |

### Confidence Gate

`metis/gates/` evaluates a composite score from `TaskSpec.confidence`, ambiguity penalties, and structural bonuses **before** MoA or agent execution. When `enforce_confidence_gate: true` (default), low composite score or unresolved ambiguities return `NEEDS_CLARIFICATION` with `clarification_questions()` — a fail-closed gate, not a correctness guarantee.

Fórmula de puntuación compuesta:

```
composite = clamp(confidence - ambiguity_penalty + criteria_bonus + constraint_bonus, 0, 1)
```

| Signal | Effect |
|--------|--------|
| Unresolved ambiguity (`needs_user_input`) | −0.1 each |
| `success_criteria` present | +0.05 |
| `constraints` present | +0.03 |
| Below `confidence_hard_floor` (0.35) | `CLARIFY` |
| Below `confidence_threshold` (0.7) | `CLARIFY` |

### DGPD — profundidad del pipeline L0–L3

**Disagreement-Gated Pipeline Depth** (`metis/pipeline/`) skips expensive layers when parallel agents agree. Security-sensitive queries always escalate to L3.

| Level | Enum | Baseline LLM calls | Pipeline behavior |
|-------|------|-------------------|-------------------|
| **L0** | `L0_FAST` | 1 | Single completion — `fast` route or simple query |
| **L1** | `L1_QUICK_CONSENSUS` | 4 | Quick consensus path — `thinking` route |
| **L2** | `L2_STANDARD` | 8 | MoA proposers; **refiner skipped** when agreement ≥ threshold |
| **L3** | `L3_FULL` | 14 | Full MoA (propose → refine → aggregate) + verify retries |

```mermaid
flowchart TD
    query[UserQuery] --> sanitize[Input_sanitizer]
    sanitize --> secCheck{Security_gate?}
    secCheck -->|"inyección / código / secretos"| forceL3[Force_L3_FULL]
    secCheck -->|limpio| dgpdEnabled{DGPD_enabled?}
    dgpdEnabled -->|no| forceL3
    dgpdEnabled -->|sí| routeMode[Route_classifier]

    routeMode -->|fast_simple| L0[L0_FAST_1_call]
    routeMode -->|thinking| L1[L1_QUICK_CONSENSUS]
    routeMode -->|council_agent| L3start[L3_FULL]

    L1 --> l1Agree{L1_agreement >= 0.85?}
    l1Agree -->|sí| L1solve[L1_solve_path]
    l1Agree -->|no| L2[L2_STANDARD]

    L2 --> moaProposers[MoA_3_proposers]
    moaProposers --> l2Agree{proposer_agreement >= 0.85?}
    l2Agree -->|sí| skipRefiner[Skip_refiner_to_aggregator]
    l2Agree -->|no| L3[L3_FULL_refiner_plus_aggregate]

    forceL3 --> L3
    L3start --> L3
    skipRefiner --> verify[Judge_verifier]
    L3 --> verify
    L0 --> done[Answer]
    L1solve --> done
    verify --> done
```

**Agreement scoring** (`metis/pipeline/agreement.py`):

- Council parsers: weighted blend of goal similarity (0.5), constraint Jaccard (0.35), ambiguity penalty (0.15)
- MoA proposers: pairwise normalized text similarity via `SequenceMatcher`

**Escalation** (`metis/pipeline/escalation.py`): `after_l1_consensus` and `after_l2_proposers` compare agreement to `dgpd.agreement_threshold` (default 0.85). L2 proposer disagreement triggers L3 mid-pipeline via `_escalation.after_l2_proposers()`.

**Force-full-depth triggers** (never skipped):

- `dgpd.force_full_depth_keywords`: delete, execute, password, api key, secret, production, deploy
- Code execution patterns: `run code`, `python`, `bash`, `eval(`
- Sensitive patterns: password, api_key, secret, token, credential
- Injection detection when `enforce_injection_scan: true`

**Calls saved** — `DepthGate.calls_saved(chosen)` reports baseline savings vs L3 (14 calls).

### Mixture-of-Agents en capas

`metis/agents/moa.py` implements a three-layer MoA (Wang et al., ICLR 2025):

```mermaid
flowchart TB
    TS[TaskSpec] --> L1A[logician_proposer]
    TS --> L1B[pragmatist_proposer]
    TS --> L1C[skeptic_proposer]
    L1A --> agree{Agreement_score}
    L1B --> agree
    L1C --> agree
    agree -->|bajo_o_sensible| L2[moa_refiner]
    agree -->|alto_DGPD| skipL2[Skip_to_aggregator_input]
    L2 --> L3[moa_aggregator]
    skipL2 --> L3
    L3 --> answer[Unified_answer]
```

| Layer | Module roles | Role |
|-------|-------------|------|
| 1 | `moa_proposer_logician`, `moa_proposer_pragmatist`, `moa_proposer_skeptic` | Parallel diverse proposals (temp 0.7) |
| 2 | `moa_refiner` | Merge strengths; skipped at L2 when proposers agree |
| 3 | `moa_aggregator` | Final unified answer aligned to TaskSpec (temp 0.3) |

La aplicación de modelos heterogéneos (`enforce_heterogeneous_agents`, `min_unique_council_models`) advierte o genera error cuando la diversidad del conjunto es débil. Base investigadora: Yang et al. (2026) — diversidad sobre escala homogénea.

### Verificador

`metis/verify/critic.py` runs the `judge` module against the TaskSpec contract:

1. Does the answer achieve the **goal**?
2. Are **constraints** respected?
3. Are **non_goals** avoided?
4. Are **success_criteria** met?

Devuelve `Verdict(passed, score, feedback)`. La ruta council reintenta hasta `max_verify_retries` (por defecto 3) con retroalimentación del judge inyectada en los prompts MoA. Un pase opcional de self-consistency (`thinking_samples > 1`) se ejecuta antes de la verificación en tareas difíciles.

### Bucle de agente

`metis/agents/loop.py` implements **Plan → Act → Observe → Reflect** for `RouteMode.AGENT`:

1. **Plan** — decompose task into steps (JSON)
2. **Act** — `agentic_tool_step` decides tool use or direct answer
3. **Observe** — record tool results in `EpisodicMemory`
4. **Reflect** — assess progress; `continue`, `retry`, or `finish`

Se ejecuta hasta `max_agent_iterations` (por defecto 5). Las herramientas MCP se cargan de forma perezosa vía `_ensure_mcp_tools()` antes de la ejecución del agente. La ruta agent siempre se ejecuta en `DepthLevel.L3_FULL`.

### Memoria y RAG

`metis/memory/store.py` provides three tiers:

| Tier | Class | Scope | Storage |
|------|-------|-------|---------|
| Working | `WorkingMemory` | Current session | In-memory turns + scratchpad (max 20 turns, last 10 in context) |
| Episodic | `EpisodicMemory` | Current session tool attempts | In-memory action/outcome log |
| Long-term | `VectorMemory` | Cross-session | JSON file (`data/memory/vectors.json`) with TF-IDF retrieval |

`metis/rag/agentic.py` performs **agentic RAG** on council path:

1. Decompose query into 1–3 sub-queries
2. Iteratively search `VectorMemory` (up to 2 iterations)
3. Synthesize answer with document citations `[1]`, `[2]`

Las respuestas exitosas de council/agent se persisten en memoria a largo plazo cuando `enable_long_term_memory: true`.

### Pipeline de búsqueda

La búsqueda web es una herramienta de primera clase, no un microservicio separado. El pipeline de búsqueda se ejecuta dentro del bucle del agente o como invocación directa de herramienta.

```mermaid
flowchart LR
    Agent[Agent_loop_or_tool_step] --> Decide{Tool_decision}
    Decide -->|web_search| WS[WebSearchTool]
    WS --> SSRF[validate_url_plus_safe_post]
    SSRF --> DDG[DuckDuckGo_HTML]
    DDG --> Parse[Extract_snippets]
    Parse --> Sanitize[sanitize_tool_output]
    Sanitize --> Wrap["wrap_untrusted salida_herramienta"]
    Wrap --> Observe[EpisodicMemory_record]
    Observe --> Reflect[Reflect_step]

    Decide -->|code_interpreter| CI[CodeInterpreterTool]
    CI --> Sandbox[subprocess_sandbox]
    Sandbox --> Sanitize
```

| Step | Module | Notes |
|------|--------|-------|
| URL validation | `security/ssrf.py` | Blocks private IPs, localhost, metadata endpoints |
| HTTP fetch | `safe_post` | Manual redirect validation per hop (max 3) |
| Output sanitization | `security/injection.py` | Truncate to 50 KB; wrap in `<untrusted>` |
| Metering | `economy/meter.py` | `record_mcp_tool` for latency tracking |

Default search URL: `https://html.duckduckgo.com/html/` (configurable via `web_search_url`).

### Registro de herramientas

`metis/tools/registry.py` centralizes tool execution:

| Builtin tool | Class | Description |
|-------------|-------|-------------|
| `code_interpreter` | `CodeInterpreterTool` | Python via `metis.tools.sandbox` subprocess (timeout configurable) |
| `web_search` | `WebSearchTool` | DuckDuckGo HTML scrape with SSRF protection |

`ToolRegistry.execute()` sanitizes successful output and records MCP/tool latency on the active `UsageMeter`. `agentic_tool_step()` drives JSON-based tool-or-answer decisions in the agent loop.

### Integración MCP

`metis/mcp/` bridges external MCP servers into `ToolRegistry`:

```mermaid
sequenceDiagram
    participant Exo as Metis
    participant Load as load_mcp_tools
    participant Client as MCPClient_stdio_SSE
    participant Reg as ToolRegistry
    participant Srv as External_MCP_server

    Exo->>Load: resolved_mcp_servers
    Load->>Client: connect
    Client->>Srv: initialize plus tools/list
    Srv-->>Client: tool_descriptors
    Client->>Reg: register MCPTool per tool
    Note over Reg: Con espacio de nombres prefix__toolname

    Exo->>Reg: execute oracle__get_random
    Reg->>Client: tools/call
    Client->>Srv: invoke
    Srv-->>Client: content blocks
    Client-->>Reg: wrapped ToolResult
```

| Transport | Client | Config |
|-----------|--------|--------|
| stdio | `MCPClient` | `command` + `args` |
| SSE | `MCPSSEClient` | `url` |

**Ecosystem presets** (`mcp_ecosystem_presets`):

| Preset | Tools | Prefix |
|--------|-------|--------|
| `aimarket-oracle-gateway` | 35 verifiable oracle tools | `oracle__` |
| `aimarket-plugins` | 15 hub plugins | `hub__` |

---

## Clúster distribuido

Cuando `distributed: true` y `cluster_config` está configurado, los módulos del cerebro con `node_id` enrutan a través de `RemoteLLMProvider` en lugar del `create_provider` local.

```mermaid
flowchart TB
    subgraph coord [Coordinator]
        MetisApp[Metis_or_CLI]
        DistCoord[DistributedCoordinator]
        NodeReg[NodeRegistry]
        RemoteProv[RemoteLLMProvider]
    end

    subgraph eu [Region_EU]
        NodeEU[node_eu_1]
        ModelEU[qwen3_8b]
        NodeEU --> ModelEU
    end

    subgraph us [Region_US]
        NodeUS[node_us_1]
        ModelUS[phi4_mini]
        NodeUS --> ModelUS
    end

    subgraph asia [Region_Asia]
        NodeASIA[node_asia_1]
        ModelASIA[mistral_7b]
        NodeASIA --> ModelASIA
    end

    MetisApp --> DistCoord
    DistCoord --> NodeReg
    NodeReg -->|"health_check /metis/health"| NodeEU
    NodeReg -->|"health_check /metis/health"| NodeUS
    NodeReg -->|"health_check /metis/health"| NodeASIA

    RemoteProv -->|"POST /metis/invoke TLS_Bearer_HMAC"| NodeEU
    RemoteProv -->|"POST /metis/invoke TLS_Bearer_HMAC"| NodeUS
    RemoteProv -->|"POST /metis/invoke TLS_Bearer_HMAC"| NodeASIA
```

**Worker node server** (`metis/distributed/server.py`):

| Endpoint | Purpose |
|----------|---------|
| `GET /metis/health` | Health probe — returns models, roles, version |
| `POST /metis/invoke` | Secure RPC — `InvokeRequest` → `InvokeResponse` |
| `POST /v1/chat/completions` | OpenAI-compat proxy on the node |

**Node resolution** (`NodeRegistry.resolve_for_slot`): explicit `node_id` → role match → model match → healthy failover. `failover_candidates` excludes failed nodes and prefers role/model matches.

**Cross-node security**: Bearer token (`METIS_NODE_*_KEY`), optional HMAC request signing (`X-Metis-Timestamp`, `X-Metis-Signature`), TLS verification, rate limiting, 512 KB body limit, structured audit logs without prompt content.

**DistributedCoordinator** (`metis/distributed/coordinator.py`) dispatches parallel agent calls across nodes and can run MoA layers with proposers on different workers.

Vea [DISTRIBUTED.md](DISTRIBUTED.md) para la configuración del clúster de producción.

---

## Economía y facturación

La capa de economía se alinea con la medición **pay-per-call** de alexar76 ([AIMarket Hub](https://github.com/alexar76/aimarket-hub), oracle gateway).

```mermaid
flowchart LR
  subgraph metisRun [Metis_run]
    Start[run_begins] --> BudgetCheck[check_budget_before_route]
    BudgetCheck --> SetMeter[set_current_meter]
    SetMeter --> LLMCalls[Tracked_LLM_calls]
    LLMCalls --> ToolCalls[MCP_and_tool_calls]
    ToolCalls --> Finalize[finalize_meter]
  end

  subgraph economy [Economy_module]
    Meter[UsageMeter]
    Calc[CostCalculator]
    Bridge[EcosystemBridge]
    Webhook[webhook_export]
    Hub[AIMarket_Hub]
  end

  SetMeter --> Meter
  LLMCalls --> Meter
  ToolCalls --> Meter
  Finalize --> Calc
  Calc --> Bridge
  Bridge --> Webhook
  Webhook --> Hub
  Bridge --> SessionBudget[Session_budget_accumulator]
```

| Component | Module | Responsibility |
|-----------|--------|----------------|
| `UsageMeter` | `economy/meter.py` | Context-var scoped per-run event collection |
| `CostCalculator` | `economy/cost.py` | Token-based cost from `economy.models` pricing table |
| `EcosystemBridge` | `economy/bridge.py` | Budget gate, finalize, webhook POST |
| `TrackedProvider` | `economy/tracked.py` | Wraps LLM providers to record token/latency events |

**Budget gate**: when `economy.enabled` and `session_budget_usd` are set, routes in `require_budget_for_routes` (default: `council`, `agent`) are blocked if estimated cost would exceed the session cap — raises `BudgetExceededError`.

**Route cost estimates** (for pre-flight checks):

| Route | Estimated LLM calls |
|-------|---------------------|
| `fast` | 1 |
| `thinking` | 2 |
| `agent` | 6 |
| `council` | 12 |

Usage reports attach to `result.metadata["usage"]` as `UsageReport.to_dict()`.

---

## Capas de seguridad

Defensa en profundidad en la entrada, transporte, salida de herramientas y RPC distribuido.

```mermaid
flowchart TB
    subgraph inputLayer [Input_Layer]
        Sanitize[sanitize_user_input]
        InjectionScan[injection_pattern_scan]
        RoleStrip[role_marker_removal]
        Canary[canary_token_injection]
        Truncate[max_user_input_chars]
    end

    subgraph promptLayer [Prompt_Layer]
        SysPrompt[build_system_prompt]
        Boundary[SECURITY_BOUNDARY_rules]
        UntrustedWrap[wrap_untrusted_delimiters]
    end

    subgraph networkLayer [Network_Layer]
        SSRF[validate_url]
        SafeHTTP[safe_get_safe_post]
        RedirectCheck[per_hop_redirect_validation]
    end

    subgraph apiLayer [API_Layer]
        BearerAuth[Bearer_API_key]
        RateLimit[token_bucket_limiter]
        BodyLimit[max_request_body_bytes]
        CORS[cors_origins_lockdown]
    end

    subgraph distLayer [Distributed_Layer]
        TLS[TLS_verification]
        HMAC[HMAC_request_signing]
        mTLS[optional_mTLS]
        Audit[audit_log_no_PII]
    end

    UserInput[User_input] --> Sanitize
    Sanitize --> InjectionScan
    InjectionScan -->|"detectado"| ForceL3[Force_L3_depth]
    Sanitize --> SysPrompt
    SysPrompt --> Boundary
    ToolOutput[Tool_MCP_output] --> UntrustedWrap

    WebSearch[Outbound_HTTP] --> SSRF
    SSRF --> SafeHTTP
    SafeHTTP --> RedirectCheck

    APIRequest[API_request] --> BearerAuth
    BearerAuth --> RateLimit
    RateLimit --> BodyLimit

    NodeRPC[Node_RPC] --> TLS
    TLS --> HMAC
    HMAC --> Audit
```

| Control | Default | Config key |
|---------|---------|------------|
| Max user input | 100,000 chars | `security.max_user_input_chars` |
| Max tool output | 50,000 chars | `security.max_tool_output_chars` |
| Max request body | 512,000 bytes | `security.max_request_body_bytes` |
| Injection scan | enabled | `security.enforce_injection_scan` |
| Rate limit | 60 req/min, burst 10 | `security.rate_limit` |
| CORS | empty (deny) | `security.cors_origins` |
| mTLS | optional | `security.mtls_cert_path`, `mtls_key_path`, `mtls_ca_path` |

**Injection patterns** detected in `security/injection.py`: ignore previous instructions, jailbreak, role spoofing, system tag injection, and similar adversarial markers.

Los eventos de seguridad se registran vía `log_security_event()` — JSON estructurado sin contenido de prompts, claves API ni secretos.

---

## API compatible con OpenAI

`metis/api/` exposes a FastAPI application compatible with OpenAI chat completions.

| Endpoint | Handler | Notes |
|----------|---------|-------|
| `GET /health` | `app.py` | Service health |
| `GET /v1/models` | `openai_compat.py` | Lists `metis`, `metis-fast`, `metis-thinking`, `metis-council`, `metis-agent` |
| `POST /v1/chat/completions` | `openai_compat.py` | Sync or SSE streaming |

**Model → route mapping** (`api/bridge.py`):

| Model | Route |
|-------|-------|
| `metis` | Auto (classifier) |
| `metis-fast` | `fast` |
| `metis-thinking` | `thinking` |
| `metis-council` | `council` |
| `metis-agent` | `agent` |

Legacy aliases `superbrain-*` are supported.

**Authentication** (`api/auth.py`): Bearer token required when `METIS_PRODUCTION=true` or `METIS_API_KEY` is set. Accepts `METIS_API_KEY`, `SUPERBRAIN_API_KEY`, or `COGNITIVE_API_KEY`.

**Start server**:

```bash
export METIS_API_KEY=sk-your-secret-key
export METIS_PRODUCTION=true
metis-serve --host 0.0.0.0 --port 8080 --config config.yaml
```

O configure `METIS_CONFIG_PATH` para cargar la configuración YAML.

---

## Integración con IDE

Metis has no bundled UI. IDEs connect as OpenAI-compatible clients.

```mermaid
flowchart LR
    subgraph ide [IDE_Clients]
        VSCode[VS_Code_Continue]
        Cursor[Cursor]
        Curl[curl_scripts]
    end

    subgraph metisApi [Metis_API_8080]
        Models["GET /v1/models"]
        Chat["POST /v1/chat/completions"]
        Stream[SSE_streaming]
    end

    subgraph brain [Metis_Brain]
        AutoRoute[Auto_route_or_forced_model]
        Council[metis_council]
        Agent[metis_agent]
    end

    VSCode --> Chat
    Cursor --> Chat
    Curl --> Chat
    Chat --> AutoRoute
    Stream --> Chat
    AutoRoute --> Council
    AutoRoute --> Agent
```

### VS Code (Continue)

```json
{
  "models": [{
    "title": "Metis Council",
    "provider": "openai",
    "model": "metis-council",
    "apiBase": "http://localhost:8080/v1",
    "apiKey": "your-key"
  }]
}
```

### Cursor

1. **Settings → Models**
2. Enable **Override OpenAI Base URL** → `http://localhost:8080/v1`
3. Set API key to your `METIS_API_KEY`

### curl

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-secret-key" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Explain async/await in Python"}]
  }'
```

---

## Registro de módulos y proveedores

`metis/modules/registry.py` maps brain roles to `ModelSlot` configurations. Unconfigured roles fall back to `base_model` / `base_url`.

```mermaid
flowchart LR
    subgraph api [API_Layer]
        CC["/v1/chat/completions"]
    end

    subgraph brain [Metis_Brain]
        R[router]
        UC[Council]
        MOA[MoA]
        J[judge]
    end

    subgraph endpoints [Per_Module_Endpoints]
        OLL[Ollama_local]
        OAI[OpenAI_API]
        DS[DeepSeek_API]
        ANT[Anthropic_API]
        N1[Remote_node_a]
        N2[Remote_node_b]
    end

    CC --> R
    R -->|router_model| OAI
    CC --> UC
    UC -->|intent_parser_a| DS
    UC -->|intent_parser_b| OAI
    UC -->|red_team| N2
    UC -->|synthesizer| ANT
    CC --> MOA
    MOA -->|logician| N1
    MOA -->|skeptic| OLL
    MOA -->|aggregator| ANT
    MOA --> J
    J -->|judge| DS
```

### Matriz de proveedores

| Provider | `provider` value | Typical `base_url` | Notes |
|----------|------------------|-------------------|-------|
| Ollama (local) | `ollama` | `http://localhost:11434/v1` | Free local inference |
| OpenAI | `openai_compat` | `https://api.openai.com/v1` | GPT models |
| DeepSeek | `openai_compat` | `https://api.deepseek.com/v1` | OpenAI-compatible |
| Anthropic | `anthropic` | (native API) | Claude models |
| Distributed node | `openai_compat` | node URL | Set `node_id` + `cluster_config` |
| vLLM / LiteLLM | `openai_compat` | your proxy URL | Any OpenAI-compatible proxy |

Validar e inspeccionar:

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

---

## Integración del ecosistema

Metis se sitúa en la **capa de razonamiento** entre endpoints LLM en bruto y agentes de demanda.

| Repository | Role | Metis relationship |
|------------|------|-------------------|
| [cognitive-runtime](https://github.com/alexar76/cognitive-runtime) | Prior exoskeleton reference implementation | Shared DGPD, council, and MoA concepts; Metis is the production successor |
| [argus](https://github.com/alexar76/argus) | Demand-side agent with payments | Uses Metis as reasoning backend; WARDEN MCP filters |
| [aimarket-hub](https://github.com/alexar76/aimarket-hub) | Marketplace and usage metering | Webhook export via `economy.webhook_url` and `aimarket_hub_url` |
| [aimarket-oracle-gateway](https://github.com/alexar76/aimarket-oracle-gateway) | Verifiable oracle MCP tools (oracles) | `mcp_ecosystem_presets: [aimarket-oracle-gateway]` — 35 pay-per-call tools |
| [aimarket-plugins](https://github.com/alexar76/aimarket-plugins) | Hub plugin MCP server | `mcp_ecosystem_presets: [aimarket-plugins]` |

```mermaid
flowchart TB
    subgraph demand [Demand]
        ARGUS[argus]
    end

    subgraph reasoning [Reasoning]
        METIS[metis]
        COG[cognitive_runtime]
    end

    subgraph marketplace [AIMarket]
        HUB[aimarket_hub]
        ORACLES[aimarket_oracle_gateway]
        PLUGINS[aimarket_plugins]
    end

    COG -.->|"conceptos evolucionaron a"| METIS
    ARGUS -->|"solicitudes de razonamiento"| METIS
    METIS -->|"herramientas MCP"| ORACLES
    METIS -->|"herramientas MCP"| PLUGINS
    METIS -->|"eventos de uso"| HUB
    ORACLES -->|"pago por llamada"| HUB
    ARGUS --> HUB
```

Mapa completo del ecosistema: [ECOSYSTEM.md](ECOSYSTEM.md).

---

## Referencia de configuración

### Nivel superior `RuntimeConfig`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `production` | bool | `false` | Enforce production security |
| `base_model` | str | `qwen3:8b` | Fallback model |
| `base_url` | str | `http://localhost:11434/v1` | Fallback endpoint |
| `provider` | enum | `ollama` | `openai_compat`, `ollama`, `anthropic` |
| `default_route` | enum | `council` | `fast`, `thinking`, `agent`, `council` |
| `thinking_samples` | int | `3` | Self-consistency sample count |
| `thinking_temperature` | float | `0.8` | Self-consistency temperature |
| `max_agent_iterations` | int | `5` | Agent loop cap |
| `max_verify_retries` | int | `3` | Verifier retry cap |
| `confidence_threshold` | float | `0.7` | Confidence gate threshold |
| `confidence_hard_floor` | float | `0.35` | Fail-closed floor |
| `enforce_confidence_gate` | bool | `true` | Mandatory gate |
| `enforce_heterogeneous_agents` | bool | `false` | Error on weak diversity |
| `min_unique_council_models` | int | `2` | Minimum unique models |
| `memory_dir` | path | `data/memory` | Vector memory directory |
| `enable_long_term_memory` | bool | `true` | TF-IDF vector store |
| `rag_top_k` | int | `5` | RAG retrieval count |
| `enable_code_interpreter` | bool | `true` | Builtin sandbox tool |
| `enable_web_search` | bool | `true` | Builtin search tool |
| `code_timeout_seconds` | int | `10` | Code interpreter timeout |
| `web_search_url` | str | DuckDuckGo HTML | Search endpoint |
| `enable_mcp_tools` | bool | `false` | Load MCP servers |
| `distributed` | bool | `false` | Enable remote providers |
| `cluster_config` | path | — | Cluster YAML path |

### Configuración DGPD (`dgpd:`)

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Enable disagreement-gated depth |
| `agreement_threshold` | `0.85` | Skip refiner / stay at L2 when above |
| `force_full_depth_keywords` | delete, execute, password, api key, secret, production, deploy | Always escalate to L3 |

### Configuración de economía (`economy:`)

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable metering and budget |
| `currency` | `USD` | Cost currency |
| `session_budget_usd` | — | Per-session spend cap |
| `require_budget_for_routes` | `council`, `agent` | Routes subject to budget gate |
| `webhook_url` | — | Usage report POST target |
| `aimarket_hub_url` | — | Hub integration URL |
| `export_events` | `true` | Log usage events |
| `models` | `{}` | Per-model `input_per_1m` / `output_per_1m` pricing |

### Configuración de seguridad (`security:`)

| Key | Default | Description |
|-----|---------|-------------|
| `max_user_input_chars` | `100000` | Input truncation |
| `max_tool_output_chars` | `50000` | Tool output cap |
| `max_request_body_bytes` | `512000` | API body cap |
| `enforce_injection_scan` | `true` | Pattern-based injection detection |
| `rate_limit.requests_per_minute` | `60` | Token bucket rate |
| `rate_limit.burst` | `10` | Burst allowance |
| `cors_origins` | `[]` | Allowed CORS origins |

### Configuración por módulo (`modules:`)

```yaml
modules:
  intent_parser_a:
    provider: openai_compat
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
    temperature: 0.5
    node_id: node-eu-1

  synthesizer:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY

  judge:
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
```

### Variables de entorno

| Variable | Purpose |
|----------|---------|
| `METIS_API_KEY` | API authentication |
| `METIS_PRODUCTION` | Require API key |
| `METIS_CONFIG_PATH` | YAML config for serve |
| `METIS_MAX_REQUEST_BYTES` | API body limit override |
| `METIS_RATE_LIMIT_PER_MINUTE` | API rate limit |
| `METIS_HMAC_SECRET` | Distributed request signing |
| `METIS_NODE_*_KEY` | Per-node Bearer tokens |

---

## Tablas de componentes

### Roles de módulos del cerebro

| Role | Pipeline stage |
|------|----------------|
| `intent_parser_a/b/c` | Understanding Council — parallel interpretation |
| `constraint_extractor` | Council — constraints |
| `ambiguity_hunter` | Council — ambiguities |
| `red_team` | Council — adversarial reading |
| `synthesizer` | Council — TaskSpec merge |
| `moa_proposer_logician/pragmatist/skeptic` | MoA layer 1 |
| `moa_refiner` | MoA layer 2 |
| `moa_aggregator` | MoA layer 3 |
| `judge` | Verifier |
| `router` | Query classifier |

### Estructura de paquetes

| Package | Responsibility |
|---------|----------------|
| `metis/exoskeleton.py` | Main orchestrator |
| `metis/agents/` | Council, MoA, agent loop, diversity |
| `metis/pipeline/` | DGPD depth, agreement, escalation |
| `metis/verify/` | Judge verifier |
| `metis/memory/` | Working, episodic, vector memory |
| `metis/rag/` | Agentic RAG |
| `metis/tools/` | Tool registry, sandbox, web search |
| `metis/mcp/` | MCP client, registry, ecosystem presets |
| `metis/distributed/` | Coordinator, nodes, remote provider, protocol |
| `metis/economy/` | Metering, cost, budget bridge |
| `metis/security/` | Injection, SSRF, rate limit, audit |
| `metis/api/` | OpenAI-compatible FastAPI |
| `metis/modules/` | Per-role provider registry |
| `metis/router/` | Query classifier |
| `metis/gates/` | Confidence gate |
| `metis/models/` | LLM provider abstraction |

### Expectativas de fiabilidad (honestas)

| Mechanism | Guarantee level |
|-----------|-----------------|
| Confidence gate | Likely — early stop, not correctness guarantee |
| Verifier + retry | Likely — judge is still an LLM |
| Heterogeneous MoA (≥2 models) | Likely with real diversity |
| MCP tool transport | Guaranteed for tool access |
| Injection sanitization | Likely — reduces attack surface |
| Session budget gate | Guaranteed for spend caps |
| DGPD depth skip | Guaranteed cost reduction on agreement |

---

## Documentación relacionada

- [API.md](API.md) — referencia de endpoints compatibles con OpenAI
- [DISTRIBUTED.md](DISTRIBUTED.md) — configuración de clúster multinodo
- [ECOSYSTEM.md](ECOSYSTEM.md) — mapa de integración alexar76
- [RESEARCH.md](RESEARCH.md) — citas sobre diversidad y MoA
- [BENCHMARKS.md](BENCHMARKS.md) — mediciones de rendimiento
- [NAMING.md](NAMING.md) — historial de nombres Metis / Superbrain
