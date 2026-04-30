---
name: mcp-builder
description: Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services. Use when building MCP servers to integrate external APIs or services, in Python (FastMCP) or Node/TypeScript (MCP SDK).
---

# MCP Server Development Guide

## Overview

Create MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. The quality of an MCP server is measured by how well it enables LLMs to accomplish real-world tasks.

---

## When to Use This Skill

- Building integrations between LLMs and external APIs
- Creating tools that Claude/opencode can use to access services
- Wrapping third-party services (GitHub, Notion, databases, etc.)
- Building internal tools for your team

---

## High-Level Workflow

### Phase 1: Deep Research and Planning

**API Coverage vs. Workflow Tools:**
Balance comprehensive API endpoint coverage with specialized workflow tools. When uncertain, prioritize comprehensive API coverage.

**Tool Naming:**
- Use clear, descriptive names
- Consistent prefixes: `github_create_issue`, `github_list_repos`
- Action-oriented naming

**Context Management:**
- Return focused, relevant data
- Support filtering/pagination
- Concise tool descriptions

### Phase 2: Implementation

**Recommended Stack:**
- **Language**: TypeScript (excellent SDK support, static typing)
- **Transport**: Streamable HTTP for remote, stdio for local

**For TypeScript:**
- MCP TypeScript SDK: `@modelcontextprotocol/sdk`
- Use Zod for input validation
- Define output schemas for structured responses

**For Python:**
- FastMCP framework: `fastmcp`
- Use Pydantic for input validation

### Phase 3: Testing

- Test with MCP Inspector: `npx @modelcontextprotocol/inspector`
- Verify each tool works as expected
- Test error handling paths

---

## TypeScript Implementation

### Project Setup

```bash
mkdir my-mcp-server
cd my-mcp-server
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D @types/node typescript
```

### Basic Server Structure

```typescript
// src/index.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

// Define input schemas
const SearchSchema = z.object({
  query: z.string().describe("Search query string"),
  limit: z.number().optional().default(10).describe("Max results to return"),
});

// Create server
const server = new Server(
  {
    name: "my-api-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "search_items",
        description: "Search for items in the system",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Search query string",
            },
            limit: {
              type: "number",
              description: "Max results to return",
              default: 10,
            },
          },
          required: ["query"],
        },
      },
    ],
  };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "search_items") {
    const parsed = SearchSchema.safeParse(args);
    if (!parsed.success) {
      throw new Error(`Invalid arguments: ${parsed.error.message}`);
    }

    // Implement your search logic here
    const results = await searchItems(parsed.data.query, parsed.data.limit);

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(results, null, 2),
        },
      ],
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
```

---

## Python Implementation (FastMCP)

### Project Setup

```bash
mkdir my-mcp-server
cd my-mcp-server
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install fastmcp
```

### Basic Server Structure

```python
# server.py
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional

# Create MCP server
mcp = FastMCP("my-api-server")

# Define input model
class SearchInput(BaseModel):
    query: str = Field(description="Search query string")
    limit: Optional[int] = Field(default=10, description="Max results to return")

# Define tool
@mcp.tool()
async def search_items(query: str, limit: int = 10) -> str:
    """
    Search for items in the system.
    
    Args:
        query: Search query string
        limit: Maximum number of results to return
    
    Returns:
        JSON string with search results
    """
    # Implement your search logic
    results = await perform_search(query, limit)
    return json.dumps(results, indent=2)

# Add more tools...

if __name__ == "__main__":
    mcp.run()
```

---

## Best Practices

### Tool Design

1. **Clear Descriptions**: Write descriptions as if explaining to a junior developer
2. **Actionable Errors**: Error messages should suggest how to fix the issue
3. **Consistent Naming**: Use verb_noun pattern (e.g., `create_issue`, `list_repos`)
4. **Input Validation**: Always validate and sanitize inputs
5. **Pagination**: Support pagination for list operations

### Error Handling

```typescript
// Good error message
throw new Error(
  `Repository "${repo}" not found. ` +
  `Check the repository name and ensure you have access. ` +
  `Format: owner/repo-name`
);

// Bad error message
throw new Error("Not found");
```

### Response Format

```typescript
// Return structured data when possible
return {
  content: [
    {
      type: "text",
      text: JSON.stringify({
        success: true,
        data: results,
        count: results.length,
      }, null, 2),
    },
  ],
};
```

---

## Testing with MCP Inspector

```bash
# Install inspector globally
npm install -g @modelcontextprotocol/inspector

# Run your server with inspector
mcp-inspector node build/index.js

# For Python
mcp-inspector python server.py
```

The inspector provides:
- Interactive tool testing
- Request/response inspection
- Error debugging

---

## Resources

- **MCP Specification**: https://modelcontextprotocol.io/
- **TypeScript SDK**: https://github.com/modelcontextprotocol/typescript-sdk
- **Python SDK**: https://github.com/modelcontextprotocol/python-sdk
- **FastMCP**: https://github.com/jlowin/fastmcp