import re

try:
	from .search_ai_search import search_chunks, search_document
except ImportError:
	from search_ai_search import search_chunks, search_document


class ToolRegistry:
	"""Registry for investigation tools and their retrieval implementations."""

	@staticmethod
	def _as_file_name(value, prefix=None):
		if value is None:
			return None

		value = str(value).strip()
		if not value:
			return None

		if value.endswith(".md"):
			return value

		if prefix and value.isdigit():
			return f"{prefix}-{value}.md"

		return f"{value}.md"

	@staticmethod
	def _is_incident_file(file_name):
		return bool(
			file_name
			and re.fullmatch(
				r"incident-\d+\.md",
				file_name,
				re.IGNORECASE,
			)
		)

	def _search_with_category(self, query, category):
		return self._with_category(search_chunks(query), category)

	def get_incident(self, incident_id):
		"""Retrieve an incident by ID, or search incident evidence by question."""
		if incident_id is None:
			return []

		incident_file = self._as_file_name(incident_id, "incident")
		is_incident_file = self._is_incident_file(incident_file)
		if incident_file and (
			str(incident_id).strip().isdigit() or is_incident_file
		):
			exact_results = search_document(incident_file)
			return self._with_category(exact_results, "incident")

		# FUTURE MCP:
		# Azure DevOps
		# GitHub
		# Jira
		# Confluence
		# Monitoring
		return self._search_with_category(incident_id, "incident")

	def get_deployment(self, deployment_id):
		"""Retrieve deployment evidence by ID or document name."""
		if deployment_id is None:
			return []

		deployment_file = self._as_file_name(deployment_id, "deployment")

		# FUTURE MCP:
		# Azure DevOps
		# GitHub
		# Jira
		# Confluence
		# Monitoring
		return self._with_category(search_document(deployment_file), "deployment")

	def get_runbook(self, runbook_name):
		"""Retrieve runbook evidence by document name."""
		if runbook_name is None:
			return []

		runbook_file = self._as_file_name(runbook_name)

		# FUTURE MCP:
		# Azure DevOps
		# GitHub
		# Jira
		# Confluence
		# Monitoring
		return self._with_category(search_document(runbook_file), "runbook")

	@staticmethod
	def _with_category(results, category):
		return [
			{
				"source": "azure_ai_search",
				"category": category,
				"primary": False,
				**result,
			}
			for result in results
		]


# Singleton registry used by the investigation runner.
tool_registry = ToolRegistry()
