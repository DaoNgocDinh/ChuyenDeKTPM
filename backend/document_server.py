"""Read-only MCP transport probe for the project's approved documents."""

from hashlib import sha256
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer
from pydantic import BaseModel


class DocumentDigest(BaseModel):
    document_id: str
    uri: str
    sha256: str
    size_bytes: int


server = MCPServer("project-documents")
PLAN_PATH = Path(__file__).resolve().parents[1] / "docs" / "ke-hoach.md"


@server.tool(name="project.describe_document")
def describe_document(document_id: Literal["P01"]) -> DocumentDigest:
    """Return the byte length and SHA-256 of the approved P01 outline."""
    content = PLAN_PATH.read_bytes()
    return DocumentDigest(
        document_id=document_id,
        uri="project-doc://approved/P01",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
    )


if __name__ == "__main__":
    server.run(transport="stdio")
