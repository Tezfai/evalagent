import base64
import html
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

API_VERSION = "7.1"
REQUEST_TIMEOUT_SECONDS = 15


def _clean_html(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    return re.sub(r"<[^>]+>", "", text).strip()


class AzureDevOpsError(RuntimeError):
    """Raised when an Azure DevOps request cannot be completed."""


class AzureDevOpsClient:
    """Small REST client for Azure DevOps investigation evidence."""

    def __init__(self):
        self.organization = os.getenv("AZDO_ORG")
        self.project = os.getenv("AZDO_PROJECT")
        self.pat = os.getenv("AZDO_PAT")

    def _request_json(self, path):
        if not all((self.organization, self.project, self.pat)):
            missing_settings = [
                name
                for name, value in (
                    ("AZDO_ORG", self.organization),
                    ("AZDO_PROJECT", self.project),
                    ("AZDO_PAT", self.pat),
                )
                if not value
            ]
            raise AzureDevOpsError(
                "Missing Azure DevOps configuration: "
                + ", ".join(missing_settings)
            )

        token = base64.b64encode(
            f":{self.pat}".encode()
        ).decode()
        request = Request(
            f"https://dev.azure.com/{quote(self.organization, safe='')}/"
            f"{quote(path, safe='/')}?api-version={API_VERSION}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {token}",
            },
        )

        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                data = json.load(response)
                if not isinstance(data, dict):
                    raise AzureDevOpsError(
                        "Azure DevOps returned an invalid JSON response."
                    )
                return data
        except HTTPError as error:
            raise AzureDevOpsError(
                f"Azure DevOps request failed with HTTP status {error.code}."
            ) from error
        except (URLError, TimeoutError, ValueError) as error:
            raise AzureDevOpsError(
                f"Azure DevOps request failed: {error}"
            ) from error

    @staticmethod
    def _require_value(value, name):
        if value is None or not str(value).strip():
            raise ValueError(f"{name} must not be empty")
        return str(value).strip()

    @staticmethod
    def _created_by(data):
        created_by = data.get("createdBy") or {}
        return created_by.get("displayName") or created_by.get("uniqueName")

    @staticmethod
    def _assigned_to(fields):
        assigned_to = fields.get("System.AssignedTo")
        if isinstance(assigned_to, dict):
            return assigned_to.get("displayName") or assigned_to.get(
                "uniqueName"
            )
        return assigned_to

    def get_work_item(self, work_item_id):
        work_item_id = self._require_value(work_item_id, "work_item_id")

        data = self._request_json(
            f"{quote(self.project, safe='')}/_apis/wit/workitems/"
            f"{quote(work_item_id, safe='')}"
        )

        fields = data.get("fields", {})
        return {
            "id": data.get("id"),
            "title": fields.get("System.Title", ""),
            "state": fields.get("System.State", ""),
            "description": _clean_html(fields.get("System.Description", "")),
            "assigned_to": self._assigned_to(fields),
        }

    def get_pull_request(self, repository_id, pr_id):
        repository_id = self._require_value(repository_id, "repository_id")
        pr_id = self._require_value(pr_id, "pr_id")

        data = self._request_json(
            f"{quote(self.project, safe='')}/_apis/git/repositories/"
            f"{quote(repository_id, safe='')}/pullrequests/"
            f"{quote(pr_id, safe='')}"
        )

        return {
            "id": data.get("pullRequestId"),
            "title": data.get("title", ""),
            "state": data.get("status", ""),
            "description": data.get("description", ""),
            "assigned_to": self._created_by(data),
        }

    def get_release(self, release_id):
        release_id = self._require_value(release_id, "release_id")

        data = self._request_json(
            f"{quote(self.project, safe='')}/_apis/release/releases/"
            f"{quote(release_id, safe='')}"
        )

        return {
            "id": data.get("id"),
            "title": data.get("name", ""),
            "state": data.get("status", ""),
            "assigned_to": self._created_by(data),
        }


# FUTURE MCP: replace these REST calls with Azure DevOps MCP tools.
azure_devops_client = AzureDevOpsClient()


if __name__ == "__main__":
    client = AzureDevOpsClient()
    work_item_id = input("Work Item ID: ").strip()
    print(json.dumps(client.get_work_item(work_item_id), indent=4))
