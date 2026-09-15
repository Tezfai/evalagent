# Project Context: Incident Investigation Assistant

You are helping continue a Python project named `evalagent`. Treat this file as the working context for future changes.

## Goal

Build an incident investigation assistant for engineering teams. Users ask questions about incidents, deployments, architecture, engineering investigations, or runbooks. The system retrieves evidence from a Markdown corpus, uses Azure OpenAI to analyze it, and returns an answer/report with source references. Evidence-grounded answers are important: do not invent facts when the corpus or external systems do not establish them.

## Current Repository

- `app.py`: Streamlit UI and current application entry point.
- `backend/rag_ai_search.py`: active simple RAG question-answering path used by the UI.
- `backend/search_ai_search.py`: active Azure AI Search retrieval functions.
- `backend/ingest_ai_search.py`: creates/recreates the Azure AI Search vector index and uploads the Markdown corpus.
- `backend/investigation_runner.py`: multi-agent investigation workflow, currently exposed mainly as a CLI/module path rather than wired into `app.py`.
- `backend/investigator_agent.py`: creates a structured investigation plan with Azure OpenAI.
- `backend/deployment_agent.py`: analyzes deployment evidence and returns validated JSON.
- `backend/runbook_agent.py`: analyzes runbook content and returns validated JSON.
- `backend/critic_agent.py`: reviews the final report against the supplied evidence.
- `backend/tool_registry.py`: compatibility facade that dispatches incident, deployment, runbook, work item, pull request, and release retrieval through the direct or MCP provider.
- `backend/tool_implementations.py`: lower-level direct implementations shared by direct mode and the MCP server.
- `backend/evalagent_mcp_client.py`: synchronous MCP client that launches the local MCP server over stdio.
- `backend/evalagent_mcp_server.py`: MCP server exposing the investigation tools; it must not import `tool_registry.py`.
- `backend/azure_devops_client.py`: direct Azure DevOps REST client using a PAT.
- Application Insights is the next planned external investigation tool and is not implemented yet.
- `backend/model.py`: standalone Azure OpenAI chat smoke test; it performs a request at import/run time and is not part of the Streamlit flow.
- `backend/ingest.py`, `backend/rag.py`, `backend/search.py`, `vector_index.faiss`, and `documents.pkl`: older FAISS/local retrieval implementation. Azure AI Search is the current path; do not modify the legacy path unless explicitly working on migration or fallback support.
- `data/`: Markdown corpus.
- `requirements.txt`: currently empty, so dependency installation/documentation still needs attention.

## Data Corpus

The corpus currently contains these categories:

- `data/incidents/`: incident records, including `incident-1042.md` through `incident-1051.md`.
- `data/deployments/`: deployment records, including `deployment-882.md` through `deployment-886.md`.
- `data/runbooks/`: service runbooks for checkout, database failover, inventory, payment, and Redis cache operations.
- `data/architecture/`: service/platform architecture documents.
- `data/engineering/`: technical investigations and postmortems.

Documents link to one another with relative Markdown links. Important relationships include incident -> deployment, incident -> engineering investigation/runbook, and deployment -> Azure DevOps work item or pull request metadata.

Representative domain facts are in the documents, not hardcoded in the application. For example, incident 1042 concerns checkout latency caused by deployment 882's Redis connection-per-lookup behavior; deployment 882 was rolled back. Future answers must retrieve and cite the relevant documents rather than relying on this example as global knowledge.

## Active UI Flow

1. `streamlit run app.py` starts the application.
2. `app.py` calls `backend.rag_ai_search.ask_question(question)`.
3. The question is embedded with the Azure OpenAI embedding deployment.
4. `search_ai_search` queries Azure AI Search with a vector query (`k_nearest_neighbors=5`, `top=5`).
5. Retrieved chunks are concatenated into a prompt for the Azure OpenAI chat deployment.
6. The answer and retrieved `{file, chunk_id, content}` sources are shown in Streamlit.
7. The UI can load the complete local Markdown document by matching the source basename under `data/`.

The Streamlit UI does not currently call `investigation_runner.run_investigation`; therefore the planner, specialized agents, report formatting, critic, and Azure DevOps enrichment are not part of the normal browser workflow yet.

## Multi-Agent Investigation Flow

`backend/investigation_runner.py` coordinates this path:

1. `create_investigation_plan` asks GPT-5-mini for JSON containing investigation type, incident/deployment/runbook identifiers, and search flags.
2. Incident evidence is retrieved exactly by filename when an ID is available; otherwise semantic incident search is used.
3. Deployment and runbook references are extracted from retrieved Markdown and/or the plan.
4. Deployment and runbook documents are retrieved, deduplicated, and analyzed by their specialized agents.
5. Deployment text is scanned for `Azure DevOps Work Item`, `Azure DevOps Pull Request`, and `Azure DevOps Repository` markers.
6. Matching Azure DevOps work items and pull requests are fetched through `ToolRegistry`. The registry uses direct implementations by default or the MCP client when `EVALAGENT_TOOL_PROVIDER=mcp`.
7. Evidence is classified into primary and supporting evidence. Supporting evidence is limited to three distinct documents.
8. GPT-5-mini generates a JSON report with sections for primary evidence, deployment/runbook analysis, incident, root cause, impact, resolution, related documents, recommendations, Azure DevOps evidence, and report review.
9. The critic agent reviews the report against the gathered evidence and its result is appended to the report.

The runner remains deterministic about tool selection. MCP standardizes the tool boundary but does not give the LLM autonomous tool selection.

Primary evidence selection matters. An explicitly requested incident should remain primary; an explicitly requested deployment can become primary when no incident ID is present. Keep this behavior intact when changing retrieval or report generation.

## Azure Services and Configuration

The code uses Azure OpenAI and Azure AI Search with API version `2024-12-01-preview`. Required `.env` variable names are:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_CHAT_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- `AZURE_OPENAI_GPT5_MINI_DEPLOYMENT` (defaults to `gpt-5-mini` in agent modules)
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_KEY`
- `AZURE_SEARCH_INDEX` (the ingestion script defaults to `incident-index`, while retrieval expects it to be set)
- `AZDO_ORG`
- `AZDO_PROJECT`
- `AZDO_PAT`
- `EVALAGENT_TOOL_PROVIDER` (`direct` by default, or `mcp`)

Never print, commit, or include secret values in summaries, logs, or code. `.env` exists locally and should remain private.

## Indexing Details

`backend/ingest_ai_search.py`:

- Reads every `data/**/*.md` file.
- Chunks text into 500-character chunks with 100-character overlap.
- Creates embeddings using `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`.
- Deletes and recreates the configured Azure AI Search index.
- Stores `id`, `file`, `chunk_id`, `content`, and `embedding` fields.
- Uses an HNSW vector profile named `incident-vector-profile`.
- Uploads documents in batches of 1,000.

Because ingestion deletes the index, run it deliberately and only after confirming the target index and credentials.

## Local Commands

Typical commands, assuming dependencies and environment variables are configured:

```powershell
python backend/ingest_ai_search.py
streamlit run app.py
python backend/investigation_runner.py
```

The repository has no committed test suite visible in the current structure. Before making broad changes, add focused tests for pure parsing/selection/formatting functions where practical. Do not call Azure services in unit tests; mock clients and responses.

## MCP Integration

The local MCP flow is:

```text
investigation_runner
	-> ToolRegistry
	-> direct implementation OR MCP client
	-> evalagent_mcp_server over stdio
	-> tool_implementations
	-> Azure AI Search or Azure DevOps
```

The MCP server exposes `get_incident`, `get_deployment`, `get_runbook`, `get_work_item`, `get_pull_request`, and `get_release`. It calls `tool_implementations.py`, not `ToolRegistry`, to avoid circular calls. The safe local tool-listing command is:

```powershell
python -m backend.evalagent_mcp_client
```

Application Insights is the next planned tool. Add it through the same lower-level implementation -> MCP server tool -> client/registry facade -> runner path. Keep returned telemetry evidence normalized and clearly distinguish retrieved telemetry from unverified hypotheses.

## Known Gaps and Risks

- `requirements.txt` is empty, so the project does not currently document installable dependencies. Imports indicate at least `streamlit`, `openai`, `python-dotenv`, `azure-core`, `azure-search-documents`, and, for the legacy FAISS path, `faiss-cpu` and `numpy`.
- The active Streamlit UI uses simple RAG, not the richer multi-agent investigation workflow.
- `search_document` retrieves all indexed documents with `search_text="*"` and filters by basename in Python. This is functionally simple but inefficient and should eventually use an Azure AI Search filter/query.
- Retrieval uses vector search only; there is no hybrid text/vector ranking, score threshold, reranking, or explicit no-result handling beyond the prompt.
- Azure DevOps calls require all `AZDO_*` settings and can fail the investigation if configured incompletely or unavailable.
- MCP mode starts a local server subprocess for each tool call and is currently intended for local development/portfolio use.
- Application Insights is planned but unavailable until its tool and tests are implemented.
- The report generator and specialized agents depend on strict JSON output and validate selected enum fields, but there is no schema library or retry/repair loop.
- Several modules use a dual relative/absolute import fallback so they can run both as package imports and direct scripts. Preserve this compatibility unless deliberately standardizing execution.
- The data and generated FAISS files are local development artifacts. Do not assume `documents.pkl` or `vector_index.faiss` represent the active Azure Search index.

## Working Conventions for Future Changes

- Start by identifying whether a requested behavior belongs to the active Streamlit RAG path or the multi-agent investigation path.
- Prefer the existing Azure SDK/OpenAI patterns and evidence shapes over introducing a new abstraction.
- Preserve source metadata: `file`, `chunk_id`, `content`, `category`, and `primary` where applicable.
- Keep LLM prompts evidence-grounded and explicitly require missing/unknown information instead of allowing unsupported conclusions.
- Validate structured LLM responses before using them, especially risk/confidence enum values and list fields.
- Keep Azure calls behind small functions that can be mocked.
- Keep MCP server tools below the registry boundary to prevent circular calls.
- Preserve direct mode while adding and verifying new MCP tools.
- Treat Application Insights results as evidence only when the tool actually returns them.
- Avoid changing the legacy FAISS modules while fixing Azure AI Search behavior.
- Do not expose `.env` values or commit credentials.
