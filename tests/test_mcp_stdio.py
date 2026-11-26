import hashlib
import sys
import unittest
from importlib.metadata import version
from pathlib import Path

from mcp import Client, StdioServerParameters


class MCPTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_discover_call_and_reject_unknown_document(self):
        root = Path(__file__).resolve().parents[1]
        transport = StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.document_server"],
            cwd=root,
        )
        async with Client(transport, read_timeout_seconds=30) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual([tool.name for tool in tools], ["project.describe_document"])
            schema = tools[0].input_schema
            self.assertEqual(schema["required"], ["document_id"])
            self.assertEqual(schema["properties"]["document_id"]["const"], "P01")

            result = await client.call_tool(tools[0].name, {"document_id": "P01"})
            expected = (root / "docs" / "ke-hoach.md").read_bytes()
            self.assertFalse(result.is_error)
            self.assertEqual(
                result.structured_content,
                {
                    "document_id": "P01",
                    "uri": "project-doc://approved/P01",
                    "sha256": hashlib.sha256(expected).hexdigest(),
                    "size_bytes": len(expected),
                },
            )
            rejected = await client.call_tool(tools[0].name, {"document_id": "R99"})
            self.assertTrue(rejected.is_error)
            self.assertIsNone(rejected.structured_content)
            print(
                f"mcp={version('mcp')} protocol={client.protocol_version} "
                f"tools/list={tools[0].name} P01={len(expected)}B R99=isError"
            )
