# MCP Notion Integration for Ask ED Chatbot

The Ask ED chatbot has been enhanced to use the Notion MCP server to augment answers with knowledge base content.

## How It Works

When a user asks a question in the Ask ED chatbot:

1. The chatbot searches your Notion workspace for relevant content using semantic search
2. The top 3 most relevant results are included in the answer
3. Each result includes:
   - Page title
   - Relevant content snippet (highlight)
   - Link to view the full page in Notion

## MCP Integration Methods

The implementation tries multiple methods to connect to the MCP Notion server:

### Method 1: MCP Bridge Module
Uses the `mcp_notion_bridge.py` module which provides a Python interface to MCP.

### Method 2: Direct MCP Client
Uses the MCP Python SDK (`pip install mcp`) to connect directly to the MCP server.

### Method 3: HTTP Bridge
If your MCP server exposes HTTP endpoints, set `MCP_NOTION_HTTP_URL` environment variable.

### Method 4: Environment Variable Bridge
For Cursor environment, MCP results can be passed via `MCP_NOTION_RESULTS` environment variable.

## Configuration

### Option 1: Using MCP Python SDK (Recommended)

1. Install the MCP Python SDK:
   ```bash
   pip install mcp
   ```

2. Set environment variables (optional):
   ```bash
   export MCP_NOTION_COMMAND="npx"
   export MCP_NOTION_ARGS="-y @modelcontextprotocol/server-notion"
   ```

### Option 2: Using MCP Bridge Module

The `mcp_notion_bridge.py` module provides a standalone bridge that can be used independently or integrated into Flask.

### Option 3: Cursor Environment

If running in Cursor with MCP configured, the integration will automatically use the available MCP tools.

## Graceful Degradation

If MCP integration is not available or fails, the chatbot will:
- Continue to work normally
- Provide answers based on repository data and EDGY knowledge
- Simply omit the Notion knowledge base context

This ensures the chatbot always works, even without Notion integration.

## Testing

To test the MCP integration:

1. Start the Flask server:
   ```bash
   python server.py
   ```

2. Ask a question in the Ask ED chatbot that relates to EDGY concepts

3. Check if Notion context appears in the answer (look for "Additional Context from Knowledge Base" section)

## Troubleshooting

- **No Notion content appearing**: Check that MCP Notion server is configured and accessible
- **Import errors**: Install required packages (`pip install mcp` or use the bridge module)
- **Connection errors**: Verify MCP server is running and accessible
- **Timeout errors**: Check network connectivity and MCP server status

## Notes

- The MCP Notion server must be configured in your Cursor environment
- The integration searches your entire Notion workspace (query_type="internal")
- Results are limited to the top 3 most relevant pages
- Content snippets are limited to 500 characters for readability

