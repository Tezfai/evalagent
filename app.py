import streamlit as st
from backend.rag_ai_search import ask_question

st.set_page_config(
    page_title="Incident Investigation Assistant",
    page_icon="🔍"
)

with st.container():
    st.title("🔍 Incident Investigation Assistant")
    st.markdown(
        "Ask a question about incidents, deployments, architecture, or runbooks."
    )

question = st.text_input(
    "Question",
    placeholder="What caused the checkout latency incident?"
)

if question.strip():
    with st.spinner("Investigating the available incident context..."):
        answer, sources = ask_question(question)

    with st.container():
        st.markdown("## Answer")
        st.markdown(answer)

    with st.container():
        st.markdown("## Sources")
        if sources:
            for source in sources:
                st.markdown(f"- `{source}`")
        else:
            st.markdown("No sources were returned.")