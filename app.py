from pathlib import Path

import streamlit as st
from backend.rag_ai_search import ask_question

DATA_DIR = Path(__file__).parent / "data"
FALLBACK_DATA_DIR = Path(__file__).parent / "data_backup"


def get_data_directories():
    directories = [DATA_DIR]
    if FALLBACK_DATA_DIR.exists():
        directories.append(FALLBACK_DATA_DIR)
    return directories


def load_source_document(source_file):
    if not source_file:
        return None

    source_name = Path(source_file).name
    for data_directory in get_data_directories():
        for match in data_directory.rglob(source_name):
            if match.is_file():
                return match.read_text(encoding="utf-8")

    return None


def display_source(source):
    if isinstance(source, dict):
        source_file = source.get("file", "Unknown source")
        chunk_id = source.get("chunk_id", "Unknown")
        source_content = source.get("content", "")
    else:
        source_file = source
        chunk_id = "Unknown"
        source_content = ""

    full_document = load_source_document(source_file)

    with st.expander(f"{source_file} (chunk {chunk_id})"):
        st.markdown(f"**Chunk ID:** {chunk_id}")
        if full_document:
            st.markdown("**Full source document**")
            st.markdown(full_document)
        else:
            st.markdown("**Retrieved chunk text**")
            st.markdown(source_content or "No source content was returned.")


def display_sources(sources):
    if not sources:
        return

    with st.container(border=True):
        st.subheader("📄 Sources")
        for source in sources:
            display_source(source)

st.set_page_config(
    page_title="Incident Investigation Assistant",
    page_icon="🔍",
    layout="wide"
)

st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] { background: #f5f7fb; }
    [data-testid="stHeader"] { background: rgba(245, 247, 251, 0.85); }
    [data-testid="stSidebar"] { background: #111827; }
    [data-testid="stSidebar"] * { color: #e5e7eb; }
    .hero {
        background: linear-gradient(135deg, #172554 0%, #0f766e 100%);
        border-radius: 14px;
        color: white;
        padding: 1.6rem 1.8rem;
        margin-bottom: 1rem;
    }
    .hero h1 { color: white; margin: 0; }
    .hero p { color: #dbeafe; margin: 0.4rem 0 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    with st.container(border=True):
        st.markdown("## 🔍 Search")
        st.caption("Incident Investigation Assistant")
        st.button(
            "Clear Conversation",
            on_click=lambda: st.session_state.update(messages=[]),
            use_container_width=True
        )

    with st.container(border=True):
        st.metric("Messages", len(st.session_state.messages))
        st.caption("Conversation turns in this session")

    with st.container(border=True):
        st.subheader("About")
        st.write(
            "Investigate incidents, deployments, architecture, and runbooks "
            "with Azure OpenAI, Azure AI Search, and RAG."
        )

st.markdown(
    """
    <section class="hero">
        <h1>Incident Investigation Assistant</h1>
        <p>Grounded answers across incidents, deployments, architecture, and runbooks.</p>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.container():
    if not st.session_state.messages:
        st.subheader("Start an investigation")
        st.caption("Try one of these focused questions, or write your own below.")
        prompt_columns = st.columns(3)
        prompts = [
            "What caused the checkout latency incident?",
            "Which deployment is linked to incident 1042?",
            "What are the recovery steps for a payment outage?",
        ]
        for column, prompt in zip(prompt_columns, prompts):
            if column.button(prompt, use_container_width=True):
                st.session_state.pending_question = prompt
                st.rerun()
    else:
        st.subheader("Conversation")

    for message in st.session_state.messages:
        role_label = "🤖 Assistant" if message["role"] == "assistant" else "👤 You"
        with st.chat_message(message["role"]):
            st.caption(role_label)
            st.markdown(message["content"])
            if message["role"] == "assistant":
                display_sources(message["sources"])

question = st.chat_input("Ask about an incident, deployment, runbook, or service")
question = question or st.session_state.pop("pending_question", None)

if question and question.strip():
    st.session_state.messages.append({
        "role": "user",
        "content": question,
        "sources": []
    })

    with st.chat_message("user"):
        st.caption("👤 You")
        st.markdown(question)

    with st.spinner("Investigating..."):
        try:
            answer, sources = ask_question(question)
        except Exception as error:
            answer = (
                "I couldn't complete that investigation. Check the Azure OpenAI "
                "and Azure AI Search configuration, then try again."
            )
            sources = []
            st.error(str(error))

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources or []
    })

    with st.chat_message("assistant"):
        st.caption("🤖 Assistant")
        st.markdown(answer)
        display_sources(sources or [])