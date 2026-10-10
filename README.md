# EvalAgent: AI-Powered Incident Investigation & Triage Assistant

**EvalAgent** is an enterprise-grade, multi-agent incident investigation system designed for site reliability engineering (SRE) and DevOps teams. It automates root-cause analysis (RCA), correlates live production telemetry, links code deployments with Azure DevOps work items/pull requests, and synthesizes runbook guidance into actionable investigation reports using **Azure OpenAI**, **Azure AI Search**, **Azure Blob Storage**, and **Model Context Protocol (MCP)**.

---

## 🌟 Key Capabilities

- **🤖 Multi-Agent Orchestration**:
  - **Investigator / Planner Agent**: Generates structured investigation strategies and extracts incident/deployment identifiers.
  - **Deployment Agent**: Analyzes release notes, configuration changes, and blast radiuses from deployment manifests.
  - **Runbook Agent**: Evaluates operational procedures, risk levels, and mitigation steps.
  - **Critic / Reviewer Agent**: Validates investigation reports against primary evidence to prevent hallucinations and enforce factual grounding.
- **☁️ Cloud Document Corpus (Azure Blob Storage)**:
  - Centralized, cloud-backed storage for engineering documentation, incident postmortems, architecture guides, and service runbooks.
  - Integrated with Azure identity (`DefaultAzureCredential` / RBAC).
- **🔍 Vector Retrieval & Hybrid RAG (Azure AI Search)**:
  - Embeddings powered by Azure OpenAI (`text-embedding-3-small` / Ada) with HNSW vector indexing.
  - Chunks, indexes, and retrieves semantically relevant documentation with exact source citations.
- **📊 Real-Time Observability (Azure Monitor / Application Insights)**:
  - Executes dynamic KQL queries against Azure Monitor Logs across requests, dependencies, exceptions, and traces for correlated incident time windows.
- **🔄 DevOps & SCM Integration (Azure DevOps)**:
  - Automatically fetches linked Work Items, Pull Requests, and release pipelines associated with problematic deployments.
- **🔌 Model Context Protocol (MCP) Architecture**:
  - Modular tool provider enabling standardized tool invocation across local and distributed MCP servers.
- **💻 Interactive Streamlit UI**:
  - Full-featured web interface for interactive incident Q&A, source inspection, and document verification.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph Data Layer
        LocalCorpus[data/ corpus] -->|upload_data_to_blob.py| BlobStorage[Azure Blob Storage\nevalagent-documents]
        BlobStorage -->|ingest_ai_search.py| Embeddings[Azure OpenAI\nEmbeddings]
        Embeddings --> AISearch[(Azure AI Search\nVector Index)]
    end

    subgraph User & Presentation Layer
        User[User / SRE] --> StreamlitUI[Streamlit UI\napp.py]
        User --> CLI[CLI Runner\ninvestigation_runner.py]
    end

    subgraph RAG & Simple Q&A
        StreamlitUI --> RAG[RAG Pipeline\nrag_ai_search.py]
        RAG --> AISearch
        RAG --> LLMChat[Azure OpenAI Chat\nGPT-4o / GPT-5-mini]
        LLMChat --> StreamlitUI
    end

    subgraph Multi-Agent Investigation Workflow
        CLI --> Planner[Investigator / Planner Agent]
        StreamlitUI -->|Investigate mode| Planner
        Planner --> ToolRegistry[Tool Registry\nDirect / MCP Provider]
        
        ToolRegistry --> AISearch
        ToolRegistry --> AppInsights[Azure Monitor / App Insights]
        ToolRegistry --> AzDO[Azure DevOps REST API]
        
        ToolRegistry --> DepAgent[Deployment Agent]
        ToolRegistry --> RunbookAgent[Runbook Agent]
        
        DepAgent --> ReportGen[Report Generator]
        RunbookAgent --> ReportGen
        
        ReportGen --> CriticAgent[Critic / Verification Agent]
        CriticAgent --> FinalReport[Structured Incident RCA Report]
    end
```

---

## 🛠️ Tech Stack

| Domain | Technology / Service |
| :--- | :--- |
| **Language & Frameworks** | Python 3.11+, Streamlit, Pydantic |
| **Generative AI & LLMs** | Azure OpenAI (GPT-4o, GPT-5-mini, text-embedding-3-small) |
| **Vector Search & Indexing** | Azure AI Search (HNSW Vector Profiles, Hybrid Search) |
| **Cloud Storage** | Azure Blob Storage (`azure-storage-blob`) |
| **Cloud Identity & Security** | Microsoft Entra ID (`DefaultAzureCredential` / RBAC) |
| **Observability & Telemetry** | Azure Monitor Logs / Application Insights (`azure-monitor-query`, KQL) |
| **DevOps & Issue Tracking** | Azure DevOps REST API (Work Items, Pull Requests, Releases) |
| **Agent Tool Protocol** | Model Context Protocol (MCP SDK) |
| **Testing & CI** | `unittest`, `unittest.mock` (Comprehensive offline mocked test suite) |

---

## 📂 Project Structure

```
evalagent/
├── app.py                            # Streamlit web UI & interactive chat
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment variables template
├── backend/
│   ├── blob_storage_client.py        # Azure Blob Storage client & document manager
│   ├── ingest_ai_search.py           # Corpus ingestion & Azure AI Search indexer
│   ├── search_ai_search.py           # Vector search & document retrieval module
│   ├── rag_ai_search.py              # End-to-end RAG question-answering pipeline
│   ├── investigation_runner.py       # Multi-agent investigation workflow coordinator
│   ├── investigator_agent.py         # Investigation planning & intent parsing agent
│   ├── deployment_agent.py           # Deployment risk & release analysis agent
│   ├── runbook_agent.py              # Operational runbook analysis agent
│   ├── critic_agent.py               # Factual review & grounding verification agent
│   ├── application_insights_client.py# Azure Monitor KQL query engine
│   ├── azure_devops_client.py        # Azure DevOps REST integration
│   ├── tool_registry.py              # Dispatcher for Direct vs. MCP tool providers
│   ├── tool_implementations.py       # Core tool execution logic
│   ├── evalagent_mcp_client.py       # MCP client interface
│   └── evalagent_mcp_server.py       # Standardized MCP stdio server
├── data/                             # Engineering documentation corpus
│   ├── architecture/                 # Service architecture diagrams and specs
│   ├── deployments/                  # Deployment release manifests
│   ├── engineering/                  # Historical RCA postmortems and deep-dives
│   ├── incidents/                    # Incident logs and timeline records
│   └── runbooks/                     # Operational runbooks and mitigation guides
├── scripts/
│   ├── upload_data_to_blob.py        # Sync local data/ corpus to Azure Blob Storage
│   └── generate_appinsights_telemetry.py # Synthetic telemetry generator for testing
└── tests/
    ├── test_application_insights.py  # Application Insights client tests
    ├── test_blob_storage.py          # Azure Blob Storage integration & mock tests
    └── test_investigation_runner.py  # Multi-agent workflow and tool tests
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.10+**
- **Azure Subscription** with:
  - Azure OpenAI Service (Chat & Embedding models deployed)
  - Azure AI Search Service
  - Azure Storage Account with a Blob container (`evalagent-documents`)
  - *(Optional)* Azure Monitor / Log Analytics Workspace & Azure DevOps organization

### 1. Installation

Clone the repository and install the required dependencies:

```bash
git clone https://github.com/your-username/evalagent.git
cd evalagent
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the project root based on `.env.example`:

```env
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<your-openai-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_GPT5_MINI_DEPLOYMENT=gpt-5-mini

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://<your-search-service>.search.windows.net
AZURE_SEARCH_KEY=<your-search-admin-key>
AZURE_SEARCH_INDEX=incident-index

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME=<your-storage-account-name>
AZURE_STORAGE_CONTAINER_NAME=evalagent-documents

# Optional: Azure DevOps & Telemetry
AZDO_ORG=<your-org>
AZDO_PROJECT=<your-project>
AZDO_PAT=<your-pat>
APPLICATIONINSIGHTS_WORKSPACE_ID=<your-workspace-id>
EVALAGENT_TOOL_PROVIDER=direct
```

Authenticate to Azure locally:

```bash
az login
```

---

## 📦 Data Ingestion & Azure Blob Storage Setup

EvalAgent uses **Azure Blob Storage** as the centralized, cloud-backed source for the incident and engineering corpus. Follow these steps to upload your documentation and index it into Azure AI Search:

### Step 1: Upload Corpus to Azure Blob Storage

The project includes an automated sync script ([scripts/upload_data_to_blob.py](scripts/upload_data_to_blob.py)) that discovers all Markdown files from your local corpus directory and uploads them to the private Azure Blob container (`evalagent-documents`), preserving folder hierarchy (such as `incidents/`, `deployments/`, `runbooks/`, `architecture/`, and `engineering/`):

1. **Authenticate to Azure** (uses `DefaultAzureCredential`):
   ```bash
   az login
   ```

2. **Run the Upload Script**:
   ```bash
   # Uploads files from the local data/ folder by default
   python scripts/upload_data_to_blob.py
   ```

   > **Custom Directory Support**: If your markdown corpus is in a backup or custom directory (e.g. `data_backup/`), you can pass the path or call the sync utility directly:
   > ```bash
   > python -c "from scripts.upload_data_to_blob import sync_local_data_to_blob; sync_local_data_to_blob('data_backup')"
   > ```

3. **Verify Uploaded Blobs in Azure**:
   ```bash
   az storage blob list --account-name <your-storage-account-name> --container-name evalagent-documents --auth-mode login --output table
   ```

### Step 2: Ingest from Blob Storage into Azure AI Search

Once the documents are stored in Azure Blob Storage, run the ingestion pipeline. It downloads the corpus directly from the Blob container in memory, creates chunk embeddings via Azure OpenAI, and builds/updates the Azure AI Search index:

```bash
python backend/ingest_ai_search.py
```

---

## 💡 Running the Application

### 1. Interactive Streamlit Web Interface

Launch the EvalAgent dashboard from the repository root:

```bash
python -m streamlit run app.py
```

Open http://localhost:8501. The dashboard has two workspaces:

- **Investigate** calls the existing multi-agent runner. Azure DevOps defaults to excluded. Application Insights defaults to **Auto** (the backend plan decides), with **Include** and **Exclude** mapping to the existing boolean arguments. Including an integration is a request, not a connection-health check or a guarantee that evidence is available.
- **Conversation** retains RAG Q&A, suggested questions, chat history, and expandable sources. Investigation and conversation histories are separate and remain available when switching modes. Each workspace has its own clear-history action.

Investigation results are organized into **Overview**, **Deployment**, **Runbook**, **Evidence**, and **Review**. Unknown report sections remain visible in Overview. The complete original Markdown is accessible and downloadable without changing its content. Critic review is explicitly labeled as a model-generated assessment, not independent verification.

Overview displays explicitly labeled incident metadata, including severity and status badges, without inferring missing facts. Deployment, runbook, impact, and critic fields receive labeled presentation where their formatting is recognized. Unknown, ambiguous, duplicate, or unfamiliar field formats fall back to original section text. Recommendations retain their content and order while recognized list markers receive readable numbering. No risk rating is inferred from incident severity, and critic confidence labels are never converted into numerical scores.

Original-report viewing and Markdown download controls occupy one report-actions area above the tabs. Example investigation requests populate the input without executing a request. Submission is disabled while an investigation runs; failed requests retain their input and offer a retry using the same integration choices. Conversation remains independent document Q&A: displayed message history and investigation reports are not automatically passed as context to its backend.

Evidence retains filenames, available chunk identifiers, category, and retrieved text. Full documents are shown separately when a local copy exists in `data/` or `data_backup/`; otherwise retrieved text remains available. The dashboard does not fetch full documents from Blob Storage.

Execution feedback reflects only the synchronous request's running, completed, or failed state. The backend exposes no agent-stage events or percentage progress. Errors shown to users are sanitized; Streamlit's internal error details are disabled. The dashboard does not display credentials or environment configuration beyond the recognized tool-provider label.

Presentation helpers live in `frontend.py`, custom styling in `assets/dashboard.css`, and native theming in `.streamlit/config.toml`. Runtime dependency versions are pinned in `requirements.txt`, with transitive constraints in `requirements.lock`; review CSS selectors and browser behavior before upgrading Streamlit.

Frontend tests replace both backend entry-point modules with mocks, so they do not invoke Azure:

All offline test modules initialize `tests/offline_bootstrap.py` before importing backend clients. It disables dotenv loading, removes inherited service credentials, installs fake test-only OpenAI configuration, and rejects external socket connections. Loopback remains available for Python's event loop. This bootstrap is not imported by the application or production backend. MCP regression tests also initialize a real stdio server and list tools without invoking Azure tools.

```bash
python -m unittest discover -s tests -p test_frontend.py -v
```

**Deployment considerations:** Histories are session-only, not durable storage. Long investigations remain synchronous and cannot be cancelled through the UI. Multi-replica hosting needs WebSocket/session routing considerations. Authentication, Azure ingress, secret management, persistence, and Azure Container Apps deployment are not implemented. Local Docker support is described below.

### Local Docker Execution

The image contains one Streamlit application and its Python backend. MCP tools run as on-demand stdio child processes in the same container, using the same Python interpreter and `/app` working directory. No ingestion, index rebuilds, synthetic telemetry, auxiliary servers, Azure CLI, or developer authentication caches are included.

The base is the official `python:3.13-slim-bookworm` image pinned by digest, verified as Linux/amd64 with Python 3.13.16. Local tests use Python 3.13.5. All 65 pinned runtime packages have compatible, non-yanked CPython 3.13 Linux x86_64 wheels in public PyPI metadata. The image installs binary wheels only and runs `pip check`; no compiler or OS development packages are added. Constraints pin current installed versions rather than upgrading SDKs. The base digest and dependency constraints must be reviewed together for future security updates; artifact hashes are not enforced by this version lock.

Docker was not available in the implementation environment. Dependency metadata, wheel availability, copy paths, exclusion rules, startup configuration, and offline tests were verified, but image build, Linux execution, image health, and container shutdown remain local verification gates. An intentionally fixed base digest is used rather than silently following tag updates.

#### Build And Credential-Free Startup

Install Docker Desktop separately and select Linux containers. Run these Windows PowerShell commands from the repository root:

```powershell
docker version
docker build --platform linux/amd64 --tag evalagent:local .
docker run --detach --init --name evalagent --stop-timeout 30 --cap-drop ALL --security-opt no-new-privileges:true --publish 127.0.0.1:8501:8501 evalagent:local
```

Open http://127.0.0.1:8501. Use another host port, such as `127.0.0.1:8503:8501`, if 8501 is already occupied. Credential-free startup supports inspecting the interface and tool discovery, not running live questions. Requests needing Azure credentials will fail with the existing sanitized error handling.

Streamlit uses exec-form startup, binds to `0.0.0.0:8501` inside the container, disables file watching and usage-statistics collection, and receives `SIGTERM` on stop. Docker's `--init` forwards signals and reaps child processes; the existing MCP context managers handle normal stdio cleanup. Shutdown during an active Linux tool call still needs runtime verification.

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health).StatusCode
docker inspect --format '{{.State.Health.Status}}' evalagent
docker exec evalagent python -B -m backend.evalagent_mcp_client
docker exec evalagent python -c "from pathlib import Path; import os; assert os.getuid() == 10001; assert Path('assets/dashboard.css').is_file(); assert Path('.streamlit/config.toml').is_file(); assert not list(Path('/app').rglob('.env*')); assert not Path('/app/.git').exists(); assert not Path('/app/documents.pkl').exists(); assert not Path('/app/vector_index.faiss').exists(); print('Non-root identity, assets and excluded local files verified')"
docker stop --time 30 evalagent
docker inspect --format '{{.State.ExitCode}}' evalagent
docker rm evalagent
```

The health status can initially be `starting`; the probe checks `/_stcore/health` every 30 seconds. It does not call Azure or establish that a deployment, index, credential, or optional integration is usable. Tool discovery should list all seven tools without an API key or Azure CLI login. Observe the stop behavior and exit status rather than assuming shutdown succeeded. No container-image verification is claimed until these commands have been run.

#### Live Azure Testing

Use a separately maintained environment file at runtime only. An existing `.env` or a local `.env.docker` works; both are excluded from the build context and ignored by Git. Use Docker env-file syntax with `NAME=value` entries; avoid shell interpolation and unnecessary surrounding quotes. Do not use build arguments for secrets.

```powershell
docker run --detach --init --name evalagent --stop-timeout 30 --cap-drop ALL --security-opt no-new-privileges:true --env-file .\.env.docker --publish 127.0.0.1:8501:8501 evalagent:local
```

The image disables dotenv file loading: credentials must be injected into the process environment, not copied into an image layer. OpenAI and AI Search retain their existing API-key contracts, and Azure DevOps retains its optional PAT contract. Application Insights queries require an authorized `DefaultAzureCredential` identity; a host Azure CLI login is not inherited. For explicit local live testing, supply a least-privilege authorized service principal through `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`, or an explicitly configured certificate/federated credential. Do not mount developer Azure CLI caches. Eventual Azure managed identity can use the existing credential chain after hosting identity and permissions are configured; this Docker change does not create them.

MCP forwards only its existing configuration allowlist, including identity endpoint/header discovery and relevant proxy/CA settings. It does not log forwarded values. Its stdout is reserved for JSON-RPC; retrieval diagnostics go to stderr. Production live credentials are not used by offline tests. Avoid printing complete `docker inspect` output or environment variables on credential-bearing containers.

The strict default-deny `.dockerignore` and explicit `COPY` instructions exclude secrets, Git metadata, tests, corpus backups, scripts, virtual environments, bytecode, and legacy FAISS/pickle files. Azure AI Search remains the retrieval source. Full local source documents are therefore unavailable by default; evidence inspection still shows retrieved chunks and clearly labels the absence of a full document. If needed, explicitly mount a sanitized document folder read-only at `/app/data` or `/app/data_backup`. This is optional and not needed for normal investigations.

#### Offline Tests In The Image

Host tests remain available with `python -B -m unittest discover tests`. To validate the Linux image with the same offline suite, mount only tests and packaging manifests read-only; do not supply an environment file or live credentials:

```powershell
docker run --rm --init --network none --cap-drop ALL --security-opt no-new-privileges:true --entrypoint python --mount "type=bind,source=$($PWD.Path)\tests,target=/app/tests,readonly" --mount "type=bind,source=$($PWD.Path)\Dockerfile,target=/app/Dockerfile,readonly" --mount "type=bind,source=$($PWD.Path)\.dockerignore,target=/app/.dockerignore,readonly" evalagent:local -B -m unittest discover tests -v
```

The test bootstrap supplies fake configuration and blocks external socket connections. The real stdio discovery regression lists tools without invoking cloud tools. Live investigations and the real evaluation harness remain opt-in and may consume paid Azure services; they are not run by image startup or offline tests. No authentication or public access restrictions are provided by local Docker: keep the host port bound to loopback until the Azure hosting/security phase.

### 2. Multi-Agent Investigation CLI

Run an autonomous end-to-end incident investigation with multi-agent planning and critic review:

```bash
python backend/investigation_runner.py
```

---

## 🧪 Testing

The repository includes a comprehensive, offline unit test suite that mocks Azure services and LLM responses:

```bash
python -m unittest discover tests
```

The test command works without a local `.env` file, API keys, PATs, or an Azure CLI login. Live investigations and the real evaluation harness are separate, opt-in operations; do not invoke them as offline tests.

MCP subprocesses receive an explicit configuration allowlist for Search, OpenAI embeddings, Azure DevOps, Azure Monitor, Azure identity discovery, proxy/CA settings, and dotenv/bytecode controls. The MCP SDK retains its safe OS environment defaults. Unrelated environment variables are not forwarded, and credentials are never printed by the forwarding code. Managed identity and injected settings therefore do not depend on a local `.env` file; certificate and federated-token file paths still require the referenced files to be available in the process environment.

---

## 🛡️ Factual Grounding & Design Principles

1. **Strict Grounding**: The system explicitly identifies missing context rather than fabricating incident timelines, code changes, or mitigation steps.
2. **Zero-Secret Cloud Auth**: Leverages Azure Managed Identity / `DefaultAzureCredential` for secure access to Azure Blob Storage and Azure Monitor.
3. **Decoupled Architecture**: Separation of concerns between storage (Blob), retrieval (AI Search), orchestration (Runner/Agents), and presentation (Streamlit).
