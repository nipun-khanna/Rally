"""Store generated capability source as review-only data, never executable code."""

import ast
import json
import os
from pathlib import Path
from uuid import UUID, uuid4


class CapabilityProposalStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _artifact(self, proposal_id: str) -> Path:
        try:
            canonical = str(UUID(proposal_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid proposal ID") from exc
        if canonical != proposal_id:
            raise ValueError("Invalid proposal ID")
        return self.directory / canonical

    def create(self, *, source: str, summary: str, dependencies: list[str],
               proposed_tests: list[str], tool_schema: dict) -> dict:
        if (not isinstance(source, str) or not source.strip() or
                not isinstance(summary, str) or not summary.strip() or
                not isinstance(dependencies, list) or
                any(not isinstance(item, str) for item in dependencies) or
                not isinstance(proposed_tests, list) or
                any(not isinstance(item, str) for item in proposed_tests) or
                not isinstance(tool_schema, dict) or
                not isinstance(tool_schema.get("name"), str) or
                not tool_schema["name"]):
            raise ValueError("Incomplete capability proposal")

        try:
            ast.parse(source)
            syntax_error = None
        except SyntaxError as exc:
            syntax_error = f"line {exc.lineno}: {exc.msg}"

        proposal_id = str(uuid4())
        metadata = {
            "id": proposal_id,
            "status": "invalid" if syntax_error else "pending_review",
            "syntax_valid": syntax_error is None,
            "syntax_error": syntax_error,
            "summary": summary,
            "dependencies": dependencies,
            "proposed_tests": proposed_tests,
            "tool_schema": tool_schema,
        }
        encoded = json.dumps(metadata, sort_keys=True).encode("utf-8")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        artifact = self._artifact(proposal_id)
        artifact.mkdir(mode=0o700)
        self._write_private(artifact / "source.py", source.encode("utf-8"))
        self._write_private(artifact / "metadata.json", encoded)
        return metadata

    @staticmethod
    def _write_private(path: Path, content: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)

    def get(self, proposal_id: str) -> dict:
        return json.loads((self._artifact(proposal_id) / "metadata.json").read_text())

    def read_source(self, proposal_id: str) -> str:
        return (self._artifact(proposal_id) / "source.py").read_text()
