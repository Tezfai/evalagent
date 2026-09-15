import os
import re

try:
	from . import evalagent_mcp_client
	from . import tool_implementations
except ImportError:
	import evalagent_mcp_client
	import tool_implementations


class ToolRegistry:
	"""Thin provider-switching facade used by the investigation runner."""

	@staticmethod
	def _as_file_name(value, prefix=None):
		return tool_implementations._as_file_name(value, prefix)

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

	@staticmethod
	def _provider():
		provider = os.getenv("EVALAGENT_TOOL_PROVIDER", "direct").lower()
		if provider not in {"direct", "mcp"}:
			raise ValueError(
				"EVALAGENT_TOOL_PROVIDER must be 'direct' or 'mcp'"
			)
		return provider

	@classmethod
	def _call(cls, name, *arguments):
		if cls._provider() == "mcp":
			argument_names = {
				"get_incident": ("incident_id",),
				"get_deployment": ("deployment_id",),
				"get_runbook": ("runbook_name",),
				"get_work_item": ("work_item_id",),
				"get_pull_request": ("repository_id", "pr_id"),
				"get_release": ("release_id",),
				"get_application_insights_telemetry": (
					"service_name",
					"start_time",
					"end_time",
					"incident_id",
					"max_records",
				),
			}[name]
			return evalagent_mcp_client.call_tool(
				name,
				**dict(zip(argument_names, arguments)),
			)
		return getattr(tool_implementations, name)(*arguments)

	def get_incident(self, incident_id):
		return self._call("get_incident", incident_id)

	def get_deployment(self, deployment_id):
		return self._call("get_deployment", deployment_id)

	def get_runbook(self, runbook_name):
		return self._call("get_runbook", runbook_name)

	def get_work_item(self, work_item_id):
		return self._call("get_work_item", work_item_id)

	def get_pull_request(self, repository_id, pr_id):
		return self._call("get_pull_request", repository_id, pr_id)

	def get_release(self, release_id):
		return self._call("get_release", release_id)

	def get_application_insights_telemetry(
		self,
		service_name,
		start_time,
		end_time,
		incident_id=None,
		max_records=200,
	):
		return self._call(
			"get_application_insights_telemetry",
			service_name,
			start_time,
			end_time,
			incident_id,
			max_records,
		)

	@staticmethod
	def _with_category(results, category):
		return tool_implementations._with_category(results, category)


# Singleton registry used by the investigation runner.
tool_registry = ToolRegistry()


if __name__ == "__main__":
	print(
		tool_registry.get_work_item(
			input("Work Item ID: ").strip()
		)
	)
