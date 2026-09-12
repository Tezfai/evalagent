from pathlib import Path

import streamlit as st
from backend.rag_ai_search import ask_question

DATA_DIR = Path(__file__).parent / "data"


def load_source_document(source_file):
    if not source_file:
        return None

    source_name = Path(source_file).name
    matches = DATA_DIR.rglob(source_name)

    for match in matches:
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

with st.container(border=True):
    st.title("🔍 Incident Investigation Assistant")
    st.caption("Azure OpenAI + Azure AI Search + RAG")
    st.markdown(
        "Ask a question about incidents, deployments, architecture, or runbooks."
    )

with st.container():
    st.subheader("💬 Conversation")
    for message in st.session_state.messages:
        role_label = "🤖 Assistant" if message["role"] == "assistant" else "👤 You"
        with st.chat_message(message["role"]):
            st.caption(role_label)
            st.markdown(message["content"])
            if message["role"] == "assistant":
                display_sources(message["sources"])

question = st.chat_input(
    "What caused the checkout latency incident?"
)

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
        answer, sources = ask_question(question)

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources or []
    })

    with st.chat_message("assistant"):
        st.caption("🤖 Assistant")
        st.markdown(answer)
        display_sources(sources or [])