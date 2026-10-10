import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from frontend import INTEGRATION_CHOICES, SUGGESTED_QUESTIONS, display_report, display_sources


load_dotenv()
st.set_page_config(page_title="EvalAgent", page_icon=":material/manage_search:", layout="wide")
stylesheet = Path(__file__).parent / "assets" / "dashboard.css"
st.markdown(f"<style>{stylesheet.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

for name, default in (
    ("messages", []), ("investigations", []), ("selected_investigation", None),
    ("mode", "Investigate"), ("include_azure_devops", False),
    ("application_insights", "Auto"), ("investigation_running", False),
):
    if name not in st.session_state:
        st.session_state[name] = default

for name in ("include_azure_devops", "application_insights", "investigation_question"):
    if name in st.session_state:
        st.session_state[name] = st.session_state[name]


def clear_conversation():
    st.session_state.messages = []
    st.session_state.pop("pending_question", None)


def clear_investigations():
    st.session_state.investigations = []
    st.session_state.selected_investigation = None


def select_investigation(widget_key):
    st.session_state.selected_investigation = st.session_state[widget_key]


def choose_example(prompt):
    st.session_state.investigation_question = prompt


def start_investigation():
    if not st.session_state.investigation_running:
        st.session_state.execute_requested = True
        st.session_state.investigation_running = bool(st.session_state.get("investigation_question", "").strip())


def retry_investigation(result):
    st.session_state.investigation_question = result["question"]
    st.session_state.include_azure_devops = result["azure_devops"]
    st.session_state.application_insights = result["application_insights"]
    start_investigation()


with st.sidebar:
    st.markdown('<div class="sidebar-brand"><span class="brand-mark">EA</span><div>EvalAgent<span class="brand-subtitle">INCIDENT INTELLIGENCE</span></div></div>', unsafe_allow_html=True)
    st.radio("Workspace", ["Investigate", "Conversation"], key="mode")
    st.divider()
    if st.session_state.mode == "Investigate":
        st.subheader("Investigation settings")
        st.selectbox(
            "Azure DevOps", [False, True], key="include_azure_devops",
            format_func=lambda include: "Include" if include else "Exclude",
        )
        st.selectbox("Application Insights", list(INTEGRATION_CHOICES), key="application_insights")
        provider = os.getenv("EVALAGENT_TOOL_PROVIDER", "direct").lower()
        st.caption(f"Configured tool provider: {provider if provider in {'direct', 'mcp'} else 'Unrecognized'}")
        st.divider()
        st.subheader("Session investigations")
        if st.session_state.investigations:
            identifiers = list(range(len(st.session_state.investigations)))[::-1]
            history = st.session_state.investigations
            history_key = f"history_{len(history)}"
            selected = st.session_state.selected_investigation
            st.selectbox(
                "Investigation history", identifiers, key=history_key,
                index=identifiers.index(selected) if selected in identifiers else 0,
                format_func=lambda identifier: f"{identifier + 1}. {'Failed | ' if history[identifier]['failed'] else ''}{history[identifier]['question']}",
                on_change=select_investigation, args=(history_key,),
            )
            st.button("Clear investigations", on_click=clear_investigations, icon=":material/delete:", use_container_width=True)
        else:
            st.caption("No investigations in this session.")
    else:
        st.subheader("Session conversation")
        st.button("Clear conversation", on_click=clear_conversation, icon=":material/delete:", use_container_width=True)

st.markdown('<div class="workspace-brand">EvalAgent</div>', unsafe_allow_html=True)
st.title("Incident investigation" if st.session_state.mode == "Investigate" else "Conversation")
st.caption(
    "Evidence-grounded incident analysis, deployment context, and recovery guidance."
    if st.session_state.mode == "Investigate"
    else "Document-grounded questions about incidents, deployments, and operational procedures."
)

if st.session_state.mode == "Investigate":
    execute_requested = st.session_state.pop("execute_requested", False)
    if not st.session_state.investigations:
        with st.container(key="investigation_examples"):
            st.caption("Example requests")
            examples = st.columns(3)
            for index, (column, label, prompt) in enumerate(zip(examples, ("Checkout latency", "Deployment correlation", "Payment recovery"), SUGGESTED_QUESTIONS)):
                with column:
                    st.button(label, key=f"investigation_example_{index}", icon=":material/arrow_forward:",
                              on_click=choose_example, args=(prompt,), use_container_width=True)
    with st.container(border=True, key="investigation_panel"):
        with st.form("investigation_input"):
            question = st.text_area(
                "Investigation request", key="investigation_question", height=120,
                placeholder="Investigate incident 1042 and identify its root cause, impact, and recovery actions.",
            )
            submitted = st.form_submit_button(
                "Run investigation", type="primary", icon=":material/manage_search:",
                disabled=st.session_state.investigation_running, on_click=start_investigation,
            )
    if submitted or execute_requested:
        if not question.strip():
            st.warning("Enter an investigation request before running.")
        else:
            azure_devops = st.session_state.include_azure_devops
            application_insights = INTEGRATION_CHOICES[st.session_state.application_insights]
            result = {
                "question": question.strip(), "report": "", "sources": [], "failed": False,
                "azure_devops": azure_devops, "application_insights": st.session_state.application_insights,
            }
            with st.status("Investigation running", expanded=True) as status:
                try:
                    from backend.investigation_runner import run_investigation

                    report, sources = run_investigation(
                        question.strip(), include_azure_devops=azure_devops,
                        include_application_insights=application_insights,
                    )
                    result["report"] = report if isinstance(report, str) else ""
                    result["sources"] = sources if isinstance(sources, (list, tuple)) else []
                    status.update(label="Investigation completed", state="complete", expanded=False)
                except Exception:
                    result["failed"] = True
                    status.update(label="Investigation failed", state="error", expanded=False)
                finally:
                    st.session_state.investigation_running = False
            st.session_state.investigations.append(result)
            st.session_state.selected_investigation = len(st.session_state.investigations) - 1
            st.rerun()

    if st.session_state.investigations:
        selected = st.session_state.selected_investigation
        if selected is None:
            selected = len(st.session_state.investigations) - 1
        result = st.session_state.investigations[selected]
        st.divider()
        st.subheader("Investigation report")
        st.write(result["question"])
        st.caption(
            f"Azure DevOps: {'Include' if result['azure_devops'] else 'Exclude'} | "
            f"Application Insights: {result['application_insights']}"
        )
        if result["failed"]:
            st.error("The investigation could not be completed. Retry your request. If the problem persists, contact your administrator.")
            st.button("Retry investigation", icon=":material/refresh:", on_click=retry_investigation, args=(result,))
        else:
            st.success("Investigation completed" if result["report"].strip() else "Execution completed without report text", icon=":material/check_circle:")
            if not result["report"].strip():
                st.warning("No report text was returned. Retrieved evidence, if available, is preserved.")
            display_report(result["report"], result["sources"], selected)
    else:
        st.divider()
        with st.container(key="investigation_empty"):
            st.markdown(":material/manage_search:")
            st.subheader("Ready to investigate")
            st.caption("No investigation report in this session.")

else:
    if not st.session_state.messages:
        st.subheader("Start a conversation")
        for index, prompt in enumerate(SUGGESTED_QUESTIONS):
            if st.button(prompt, key=f"suggestion_{index}", icon=":material/arrow_forward:"):
                st.session_state.pending_question = prompt

    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=":material/person:" if message["role"] == "user" else ":material/hub:"):
            if message.get("failed"):
                st.error(message["content"])
            else:
                st.markdown(message["content"])
            if message["role"] == "assistant" and not message.get("failed"):
                display_sources(message["sources"])

    question = st.chat_input("Ask about incidents or runbooks")
    question = question or st.session_state.pop("pending_question", None)
    if question and question.strip():
        st.session_state.messages.append({"role": "user", "content": question.strip(), "sources": []})
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(question.strip())
        failed = False
        with st.status("Retrieving answer", expanded=False) as status:
            try:
                from backend.rag_ai_search import ask_question

                answer, sources = ask_question(question.strip())
                answer = answer if isinstance(answer, str) and answer.strip() else "No answer text was returned. Any retrieved evidence is shown below."
                sources = sources if isinstance(sources, (list, tuple)) else []
                status.update(label="Answer retrieved", state="complete")
            except Exception:
                answer = "The answer could not be retrieved. Retry your question. If the problem persists, contact your administrator."
                sources = []
                failed = True
                status.update(label="Request failed", state="error")
        st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources, "failed": failed})
        st.rerun()