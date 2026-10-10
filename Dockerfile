ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/evalagent

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt -c requirements.lock \
    && python -m pip check \
    && groupadd --gid 10001 evalagent \
    && useradd --uid 10001 --gid evalagent --create-home --shell /usr/sbin/nologin evalagent

COPY app.py frontend.py ./
COPY assets/dashboard.css ./assets/dashboard.css
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY backend/application_insights_client.py backend/azure_devops_client.py \
    backend/blob_storage_client.py backend/critic_agent.py backend/deployment_agent.py \
    backend/evalagent_mcp_client.py backend/evalagent_mcp_server.py \
    backend/investigation_runner.py backend/investigator_agent.py \
    backend/rag_ai_search.py backend/runbook_agent.py backend/search_ai_search.py \
    backend/tool_implementations.py backend/tool_registry.py ./backend/

USER 10001:10001
EXPOSE 8501
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3); raise SystemExit(0 if response.status == 200 else 1)"]

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"]