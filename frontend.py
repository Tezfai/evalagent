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