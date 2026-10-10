import os

# Unit tests call tools in-process; MCP is the production default and has its own tests.
os.environ.setdefault("TOOLS_VIA_MCP", "0")
