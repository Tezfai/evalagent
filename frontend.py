import math
import re
from dataclasses import dataclass
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIRECTORIES = (ROOT / "data", ROOT / "data_backup")
SUGGESTED_QUESTIONS = (
    "What caused the checkout latency incident?",
    "Which deployment is linked to incident 1042?",
    "What are the recovery steps for a payment outage?",
)
REPORT_GROUPS = {
    "Overview": {"Primary Evidence", "Incident", "Root Cause", "Impact", "Resolution", "Recommendations"},
    "Deployment": {"Deployment Analysis"},
    "Runbook": {"Runbook Analysis"},
    "Evidence": {"Related Documents", "Azure DevOps Evidence"},
    "Review": {"Report Review"},
}
INTEGRATION_CHOICES = {"Auto": None, "Include": True, "Exclude": False}
FIELD_GROUPS = {
    "Incident": ("Incident ID", "Severity", "Status", "Service", "Incident Date", "Duration", "Related Deployment"),
    "Deployment Analysis": ("Change Summary", "Assessed Risk Rating", "Related Incidents", "Rollback Status"),
    "Runbook Analysis": ("Purpose", "Immediate Actions", "Escalation Conditions", "Recovery Steps", "Risk Level"),
    "Report Review": ("Confidence", "Report Quality", "Evidence Coverage", "Missing Evidence", "Unsupported Claims", "Recommended Next Steps", "Review Summary"),
    "Related Documents": ("Retrieved", "Referenced but Not Retrieved"),
    "Impact": ("Affected Service Behavior", "Reported Metrics", "User Impact"),
}
FIELD_ALIASES = {
    "date": "Incident Date", "deployment": "Related Deployment",
    "risk rating": "Assessed Risk Rating",
}


@dataclass(frozen=True)
class ReportSection:
    title: str | None
    markdown: str


def split_report(report):
    sections = []
    title = None
    lines = []
    fence_character = None
    fence_length = 0
    for line in report.splitlines(keepends=True):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if fence_character is None:
                fence_character, fence_length = marker[0], len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                if not line[fence.end():].strip():
                    fence_character = None
            lines.append(line)
            continue
        heading = re.match(r"^ {0,3}##[ \t]+(.+?)[ \t]*\r?\n?$", line)
        if heading and fence_character is None:
            if lines:
                sections.append(ReportSection(title, "".join(lines)))
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1)).strip()
            lines = [line]
        else:
            lines.append(line)
    if lines:
        sections.append(ReportSection(title, "".join(lines)))
    return sections


def load_source_document(source_file, directories=None):
    if not source_file or "://" in str(source_file):
        return None
    source_name = str(source_file).replace("\\", "/").rsplit("/", 1)[-1]
    if source_name in {"", ".", ".."}:
        return None
    for directory in DATA_DIRECTORIES if directories is None else directories:
        try:
            for match in Path(directory).rglob(source_name):
                if match.is_file() and match.resolve().is_relative_to(Path(directory).resolve()):
                    return match.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
    return None


def extract_fields(text, labels):
    if re.search(r"^\s*(?:`{3,}|~{3,})", text, re.MULTILINE):
        return None
    names = {label.lower(): label for label in labels}
    names.update({alias: label for alias, label in FIELD_ALIASES.items() if label in labels})
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    pattern = rf"(?:^|(?<=;)[ \t]+)[ \t]*(?:[-*][ \t]+)?(?:\*\*)?({alternatives})(?:\*\*)?[ \t]*:(?:\*\*)?[ \t]*"
    matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
    if not matches or text[:matches[0].start()].strip():
        return None
    other_labels = re.findall(r"^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?([A-Za-z][A-Za-z ]{0,48})(?:\*\*)?[ \t]*:", text, re.MULTILINE)
    if any(label.lower().strip() not in names for label in other_labels):
        return None
    label_mentions = list(re.finditer(rf"\b({alternatives})(?:\*\*)?[ \t]*:", text, re.IGNORECASE))
    if len(label_mentions) != len(matches):
        return None
    fields = []
    seen = set()
    for index, match in enumerate(matches):
        label = names[match.group(1).lower()]
        if label in seen:
            return None
        seen.add(label)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        if index + 1 < len(matches) and value.endswith(";"):
            value = value[:-1].rstrip()
        fields.append((label, value))
    return fields


def number_recommendations(text):
    if re.search(r"^\s*(?:`{3,}|~{3,})", text, re.MULTILINE):
        return text
    if "\n" not in text.strip():
        markers = list(re.finditer(r"(?:^|[ \t]+)(\d+)[.)][ \t]+(?=\S)", text))
        if len(markers) > 1 and not text[:markers[0].start()].strip() and [int(marker.group(1)) for marker in markers] == list(range(1, len(markers) + 1)):
            return "\n".join(
                f"{index + 1}. {text[marker.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)].strip()}"
                for index, marker in enumerate(markers)
            )
    lines = text.splitlines(keepends=True)
    numbered = []
    counter = 0
    for line in lines:
        match = re.match(r"^(?:[-*]|\d+[.)])[ \t]+(.+)", line)
        if match:
            counter += 1
            numbered.append(f"{counter}. {match.group(1)}\n")
        else:
            numbered.append(line)
    return "".join(numbered)


def display_summary_fields(fields, key):
    with st.container(key=key):
        for offset in range(0, len(fields), 3):
            columns = st.columns(3)
            for column, (label, value) in zip(columns, fields[offset:offset + 3]):
                with column:
                    st.caption(label)
                    if label in {"Severity", "Status"} and value and "\n" not in value and len(value) < 80:
                        st.badge(value, color="orange" if label == "Severity" else "gray")
                    else:
                        st.markdown(f"**{value}**" if value and "\n" not in value else value or "No value returned.")


def display_section(section, key):
    if section.title not in FIELD_GROUPS and section.title != "Recommendations":
        section_name = (section.title or "context").replace(" ", "_").lower()
        with st.container(key=f"section_{section_name}_{key}"):
            st.markdown(section.markdown)
        return
    body = "".join(section.markdown.splitlines(keepends=True)[1:])
    if section.title == "Recommendations":
        st.subheader("Recommendations")
        st.markdown(number_recommendations(body))
        return
    fields = extract_fields(body, FIELD_GROUPS[section.title])
    if fields is None:
        st.markdown(section.markdown)
        return
    st.subheader(section.title)
    if section.title == "Incident":
        display_summary_fields(fields, f"incident_summary_{key}")
        return
    if section.title == "Report Review":
        summary = [field for field in fields if field[0] in FIELD_GROUPS["Report Review"][:3]]
        if summary:
            display_summary_fields(summary, f"review_summary_{key}")
        fields = [field for field in fields if field not in summary]
    for label, value in fields:
        with st.container(key=f"field_{key}_{label.replace(' ', '_').lower()}"):
            st.markdown(f"**{label}**")
            if label == "Referenced but Not Retrieved":
                st.caption("References only. These documents were not retrieved or analyzed in this investigation.")
            st.markdown(value or "No value returned.")


def display_sources(sources, *, grouped=False):
    if not sources:
        st.info("No retrieved evidence was returned.")
        return
    groups = [("Retrieved evidence", sources)]
    if grouped:
        groups = [
            ("Primary evidence", [source for source in sources if isinstance(source, dict) and source.get("primary")]),
            ("Supporting evidence", [source for source in sources if not isinstance(source, dict) or not source.get("primary")]),
        ]
    for label, records in groups:
        if not records:
            continue
        st.subheader(label)
        for source in records:
            record = source if isinstance(source, dict) else {"file": source}
            filename = str(record.get("file") or "Unknown source")
            chunk = record.get("chunk_id")
            chunk_label = "Unavailable" if chunk is None else str(chunk)
            category = f"{record['category']} | " if record.get("category") else ""
            with st.expander(f"{category}{filename} | Chunk {chunk_label}"):
                st.caption(f"Source: {filename}")
                st.caption(f"Chunk: {chunk_label}")
                if record.get("category") or record.get("source"):
                    st.caption(f"Type: {record.get('category') or record.get('source')}")
                if record.get("category") and record.get("source"):
                    st.caption(f"Provider: {record['source']}")
                st.markdown("**Retrieved evidence**")
                st.markdown(record.get("content") or "No retrieved source text was returned.")
                document = load_source_document(filename)
                if document:
                    st.markdown("**Full source document | Local copy**")
                    st.markdown(document)
                else:
                    st.caption("A full local document is unavailable; retrieved evidence is shown above.")


def display_report(report, sources, report_key):
    sections = split_report(report)
    known_titles = set().union(*REPORT_GROUPS.values())
    display_report_actions(report, report_key)
    tabs = st.tabs(list(REPORT_GROUPS))
    for (group, titles), tab in zip(REPORT_GROUPS.items(), tabs):
        with tab:
            if group == "Review":
                st.info("Model-generated critic assessment. This is not an independent verification of the report or its claims.")
            selected = [section for section in sections if section.title in titles]
            if group == "Overview":
                selected = [section for section in sections if section.title in titles or section.title not in known_titles]
            for index, section in enumerate(selected):
                display_section(section, f"{report_key}_{group}_{index}")
            if not selected:
                st.caption(f"No {group.lower()} section was returned.")
            if group == "Evidence":
                display_sources(sources, grouped=True)


def _metric_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _duration_text(value):
    return f"{value / 1000:.2f} s" if _metric_number(value) else "Unavailable"


def _token_text(metrics, field, flag):
    value = metrics.get(field)
    return (
        f"{value:,}"
        if metrics.get(flag) is True and isinstance(value, int)
        and _metric_number(value) else "Unavailable (usage incomplete)"
    )


def _stage_label(stage):
    if not isinstance(stage, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", stage):
        return "Unknown stage"
    return stage.replace("_", " ").capitalize()


def _request_token_text(value):
    return f"{value:,}" if isinstance(value, int) and _metric_number(value) else "Unavailable"


def _metric_cards(cards):
    for column, (label, value, caption) in zip(st.columns(len(cards)), cards):
        with column:
            st.metric(label, value)
            if caption:
                st.caption(caption)


def display_investigation_metrics(metrics, key):
    with st.container(key=f"investigation_metrics_{key}"):
        st.subheader("Investigation metrics")
        if not isinstance(metrics, dict):
            st.caption("Metrics are unavailable for this investigation.")
            metrics = {}
        counts = [metrics.get(field) for field in (
            "calls_attempted", "calls_successful", "calls_failed",
        )]
        counts_complete = metrics.get("request_metrics_complete") is True and all(
            isinstance(value, int) and _metric_number(value) for value in counts
        )
        calls_caption = (
            f"{counts[0]} attempted, {counts[1]} succeeded, {counts[2]} failed"
            if counts_complete else "Request metrics incomplete or unavailable."
        )
        tokens = _token_text(metrics, "total_tokens", "token_totals_complete")
        cost = metrics.get("estimated_cost")
        verified_cost = (
            metrics.get("cost_status") == "verified"
            and metrics.get("cost_currency") == "USD"
            and counts_complete and metrics.get("token_totals_complete") is True
            and _metric_number(cost)
        )
        _metric_cards([
            ("Duration", _duration_text(metrics.get("duration_ms")), "Investigation wall-clock time."),
            ("LLM requests", f"{counts[0]:,}" if counts_complete else "Unavailable", calls_caption),
            ("Total tokens", tokens if not tokens.startswith("Unavailable") else "Unavailable",
             "" if not tokens.startswith("Unavailable") else "Usage incomplete or unavailable."),
            ("Estimated cost", f"${cost:.4f}" if verified_cost else "Unavailable",
             "USD; verified configured pricing." if verified_cost else "Verified pricing is not configured or usage is incomplete."),
        ])
        with st.expander("Advanced investigation metrics", expanded=False):
            display_advanced_investigation_metrics(metrics)


def display_advanced_investigation_metrics(metrics):
    st.subheader("Performance overview")
    _metric_cards([
        ("Investigation elapsed", _duration_text(metrics.get("duration_ms")), "Wall-clock time."),
        ("LLM request time", _duration_text(metrics.get("llm_duration_ms")), "Cumulative observed SDK request durations."),
        ("Tool execution time", _duration_text(metrics.get("tool_duration_ms")), "Cumulative observed tool-call durations."),
        ("Other / unattributed", "Unavailable", "Cannot reliably subtract overlapping measurements."),
    ])
    st.caption(
        "Cumulative durations are not additive wall-clock time. Tool time includes retrieval "
        "and MCP startup/transport; embedding requests can overlap that tool time. "
        "SDK-internal retries are included in request latency, not separate observed requests."
    )

    stages = metrics.get("stages")
    stages = stages if isinstance(stages, dict) else {}
    agents = metrics.get("agent_stages")
    agents = agents if isinstance(agents, dict) else {}
    executed = sorted(set(stages) | set(agents))
    latency_rows = []
    token_rows = []
    for stage in executed:
        requests = stages.get(stage, {})
        runtime = agents.get(stage, {})
        if not isinstance(requests, dict) or not isinstance(runtime, dict):
            continue
        duration = runtime.get("duration_ms")
        latency_rows.append({
            "Stage": _stage_label(stage),
            "Stage runtime (s)": duration / 1000 if _metric_number(duration) else None,
            "LLM request duration": _duration_text(requests.get("duration_ms")),
            "LLM requests": (
                str(requests["calls_attempted"])
                if metrics.get("request_metrics_complete") is True
                and isinstance(requests.get("calls_attempted"), int)
                else "Unavailable"
            ),
            "Status": runtime.get("status") if runtime.get("status") in {
                "success", "failed", "mixed",
            } else "Unavailable",
        })
        token_rows.append({
            "Stage": _stage_label(stage),
            "Prompt tokens": _token_text(requests, "prompt_tokens", "prompt_tokens_complete"),
            "Completion tokens": _token_text(requests, "completion_tokens", "completion_tokens_complete"),
            "Total tokens": _token_text(requests, "total_tokens", "token_totals_complete"),
        })

    st.subheader("Agent latency breakdown")
    if latency_rows:
        max_duration = max((row["Stage runtime (s)"] or 0 for row in latency_rows), default=1)
        st.dataframe(
            latency_rows, hide_index=True, width="stretch",
            column_config={
                "Stage runtime (s)": st.column_config.ProgressColumn(
                    "Stage runtime (s)", min_value=0, max_value=max(max_duration, 1),
                    format="%.2f s",
                ),
            },
        )
        st.caption(
            "Runtime measures the entire agent function, including its SDK calls and explicit retries. "
            "Blank runtime bars mean unavailable (for example, retrieval-only embedding stages). "
            "Only observed stages are shown."
        )
    else:
        st.caption("Agent runtime metrics are unavailable or no agent stages were observed.")

    st.subheader("Token usage breakdown")
    _metric_cards([
        ("Prompt tokens", _token_text(metrics, "prompt_tokens", "prompt_tokens_complete"), ""),
        ("Completion tokens", _token_text(metrics, "completion_tokens", "completion_tokens_complete"), ""),
        ("Total tokens", _token_text(metrics, "total_tokens", "token_totals_complete"), ""),
    ])
    if token_rows:
        st.dataframe(token_rows, hide_index=True, width="stretch")
    st.caption("Embedding requests contribute prompt/total tokens, not completion tokens. Incomplete totals are unavailable.")

    st.subheader("MCP / tool execution")
    tools = metrics.get("tools")
    if isinstance(tools, dict) and tools:
        tool_rows = []
        for tool, record in sorted(tools.items()):
            if not isinstance(record, dict):
                continue
            tool_rows.append({
                "Tool": tool if isinstance(tool, str)
                and re.fullmatch(r"get_[a-z_]{1,64}", tool) else "Unknown tool",
                "Calls": record.get("calls_attempted"),
                "Total observed duration": _duration_text(record.get("duration_ms")),
                "Average per call": _duration_text(record.get("average_duration_ms")),
                "Succeeded": record.get("calls_successful"),
                "Failed": record.get("calls_failed"),
            })
        st.dataframe(tool_rows, hide_index=True, width="stretch")
    else:
        st.caption("No tool calls observed." if metrics.get("tool_metrics_complete") is True
                   else "Tool execution metrics are unavailable.")
    if metrics.get("tool_metrics_complete") is False:
        st.caption("Tool telemetry is incomplete; totals are unavailable.")

    with st.expander("Individual LLM SDK requests", expanded=False):
        records = metrics.get("requests")
        request_rows = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            request_type = record.get("request_type")
            deployment = record.get("deployment")
            finish = record.get("finish_reason")
            request_rows.append({
                "Stage": _stage_label(record.get("stage")),
                "Request type": {"chat": "Chat", "embeddings": "Embedding"}.get(request_type, "Unavailable"),
                "Deployment": deployment if isinstance(deployment, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", deployment) else "Unavailable",
                "Duration": _duration_text(record.get("duration_ms")),
                "Prompt tokens": _request_token_text(record.get("prompt_tokens")),
                "Completion tokens": "N/A (embedding)" if request_type == "embeddings"
                else _request_token_text(record.get("completion_tokens")),
                "Total tokens": _request_token_text(record.get("total_tokens")),
                "Finish reason": finish if finish in {"stop", "length", "content_filter", "tool_calls", "function_call"} else "Unavailable",
                "Status": record.get("status") if record.get("status") in {"success", "failed"} else "Unavailable",
            })
        if request_rows:
            st.dataframe(request_rows, hide_index=True, width="stretch")
            if metrics.get("request_metrics_complete") is not True:
                st.caption("Request collection is incomplete. These are observed records only, not a definitive request total.")
        else:
            st.caption("Request-level details are unavailable or no SDK requests were observed.")


def display_report_actions(report, report_key):
    with st.container(key=f"report_actions_{report_key}"):
        download_column, original_column = st.columns([1, 3])
        with download_column:
            st.download_button(
                "Download report", data=report, file_name="evalagent-investigation.md",
                mime="text/markdown", key=f"download_{report_key}", icon=":material/download:",
                disabled=not report.strip(), on_click="ignore", use_container_width=True,
            )
        with original_column:
            with st.expander("Complete original Markdown report"):
                if report.strip():
                    st.markdown(report)
                    st.code(report, language="markdown")
                else:
                    st.warning("The investigation returned no report text. Any retrieved evidence remains available in Evidence.")