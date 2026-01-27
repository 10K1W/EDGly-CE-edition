#!/usr/bin/env python3
"""
MCP Notion Bridge Service

This service bridges MCP Notion calls for the Flask server.
It can be run as a separate service or integrated into the Flask app.

Usage:
    python mcp_notion_bridge.py
    
Or integrate into Flask:
    from mcp_notion_bridge import search_notion_mcp
    results = search_notion_mcp("your query")
"""

import os
import sys
import json
import subprocess
from typing import Optional, Dict, List, Any

def search_notion_mcp(query: str, query_type: str = "internal", limit: int = 3) -> Optional[List[Dict[str, Any]]]:
    """
    Search Notion using MCP server.
    
    Args:
        query: Search query string
        query_type: Type of search ("internal" for workspace search)
        limit: Maximum number of results to return
        
    Returns:
        List of formatted results with title, content, url, or None if error
    """
    try:
        # Method 1: Try using MCP client library if available
        try:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client
            from mcp.client.stdio import StdioServerParameters
            import asyncio
            
            # MCP server configuration (adjust based on your setup)
            mcp_server_path = os.getenv('MCP_NOTION_SERVER_PATH', 'npx')
            mcp_server_args_str = os.getenv('MCP_NOTION_SERVER_ARGS', '-y @modelcontextprotocol/server-notion')
            mcp_server_args = mcp_server_args_str.split() if isinstance(mcp_server_args_str, str) else mcp_server_args_str
            
            async def _search():
                # Use StdioServerParameters instead of dict
                server_params = StdioServerParameters(
                    command=mcp_server_path,
                    args=mcp_server_args
                )
                
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        # Initialize session
                        await session.initialize()
                        
                        result = await session.call_tool(
                            "notion-search",
                            {
                                "query": query,
                                "query_type": query_type
                            }
                        )
                        return result
                
            # Run async function - handle event loop properly
            try:
                # Try to get existing event loop
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                # No event loop in this thread, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            result = loop.run_until_complete(_search())
            
            if result and 'results' in result:
                return format_mcp_results(result['results'], limit)
                
        except ImportError:
            # MCP client library not available - this is expected in many environments
            pass
        except Exception as e:
            print(f"MCP client error: {e}, trying alternative method...")
        
        # Method 2: Use HTTP bridge if MCP server exposes HTTP endpoint
        mcp_http_url = os.getenv('MCP_NOTION_HTTP_URL')
        if mcp_http_url:
            try:
                import requests
                response = requests.post(
                    f"{mcp_http_url}/search",
                    json={"query": query, "query_type": query_type},
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    if 'results' in result:
                        return format_mcp_results(result['results'], limit)
            except Exception as e:
                print(f"HTTP bridge error: {e}")
        
        # Method 3: Use subprocess to call MCP CLI (if available)
        # This assumes MCP CLI tools are installed and accessible
        try:
            # Try calling via npx or direct MCP command
            cmd = ['npx', '-y', '@modelcontextprotocol/server-notion', 'search', query]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if 'results' in data:
                    return format_mcp_results(data['results'], limit)
        except Exception as e:
            print(f"Subprocess MCP call error: {e}")
        
        # If all methods fail, return None (graceful degradation)
        return None
        
    except Exception as e:
        print(f"Notion MCP search error: {e}")
        return None

def format_mcp_results(results: List[Dict], limit: int = 3) -> List[Dict[str, Any]]:
    """
    Format MCP Notion search results for use in chatbot.
    
    Args:
        results: Raw MCP search results
        limit: Maximum number of results to format
        
    Returns:
        List of formatted result dictionaries
    """
    formatted = []
    
    for result in results[:limit]:
        title = result.get('title', 'Untitled')
        highlight = result.get('highlight', '') or result.get('snippet', '')
        url = result.get('url', '')
        page_id = result.get('id', '')
        
        # Clean HTML entities from highlight
        if highlight:
            highlight = highlight.replace('&lt;', '<').replace('&gt;', '>')
            highlight = highlight.replace('&amp;', '&')
        
        formatted.append({
            'title': str(title),
            'content': str(highlight)[:500] if highlight else '',
            'url': str(url) if url else '',
            'id': str(page_id) if page_id else ''
        })
    
    return formatted

if __name__ == '__main__':
    # Test the bridge
    if len(sys.argv) > 1:
        query = ' '.join(sys.argv[1:])
        results = search_notion_mcp(query)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No results or error occurred")
    else:
        print("Usage: python mcp_notion_bridge.py <search query>")

