from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import asyncio
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="Knowledge Base Assistant API")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Schemas
class QueryRequest(BaseModel):
    question: str
    sources: Optional[List[str]] = ["drive", "notion", "calendar"]


class Source(BaseModel):
    name: str
    content: str
    url: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    tools_used: List[str]


# MCP Server Manager
class MCPServerManager:
    def __init__(self):
        self.servers = {
            "calendar": {
                "command": "npx",
                "args": ["@cocal/google-calendar-mcp"],
                "env": {
                    "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
                    "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET")
                }
            },
            "notion": {
                "command": "npx",
                "args": ["@notionhq/notion-mcp-server"],
                "env": {
                    "NOTION_API_KEY": os.getenv("NOTION_API_KEY")
                }
            },
            "drive": {
                "command": "npx",
                "args": ["@modelcontextprotocol/server-gdrive"],
                "env": {
                    "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
                    "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET")
                }
            }
        }
        self.processes = {}
    
    async def start_server(self, server_name: str):
        """Start an MCP server process"""
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        
        server_config = self.servers[server_name]
        
        # Start the process
        process = await asyncio.create_subprocess_exec(
            server_config["command"],
            *server_config["args"],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **server_config["env"]}
        )
        
        self.processes[server_name] = process
        return process
    
    async def call_server(self, server_name: str, method: str, params: Dict[str, Any]):
        """
        Call an MCP server with a specific method
        Uses JSON-RPC 2.0 protocol over stdin/stdout
        """
        if server_name not in self.processes:
            await self.start_server(server_name)
        
        process = self.processes[server_name]
        
        # Prepare JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        # Send request
        request_json = json.dumps(request) + "\n"
        process.stdin.write(request_json.encode())
        await process.stdin.drain()
        
        # Read response
        response_line = await process.stdout.readline()
        response = json.loads(response_line.decode())
        
        if "error" in response:
            raise Exception(f"MCP Server Error: {response['error']}")
        
        return response.get("result", {})
    
    async def search_calendar(self, query: str):
        """Search Google Calendar"""
        try:
            result = await self.call_server(
                "calendar",
                "tools/call",
                {
                    "name": "search_events",
                    "arguments": {"query": query}
                }
            )
            return result
        except Exception as e:
            print(f"Calendar search error: {e}")
            return []
    
    async def search_notion(self, query: str):
        """Search Notion"""
        try:
            result = await self.call_server(
                "notion",
                "tools/call",
                {
                    "name": "search",
                    "arguments": {"query": query}
                }
            )
            return result
        except Exception as e:
            print(f"Notion search error: {e}")
            return []
    
    async def search_drive(self, query: str):
        """Search Google Drive"""
        try:
            result = await self.call_server(
                "drive",
                "tools/call",
                {
                    "name": "search_files",
                    "arguments": {"query": query}
                }
            )
            return result
        except Exception as e:
            print(f"Drive search error: {e}")
            return []
    
    async def cleanup(self):
        """Stop all MCP server processes"""
        for process in self.processes.values():
            process.terminate()
            await process.wait()


# Initialize MCP manager
mcp_manager = MCPServerManager()


# MCP Server Communication
async def fetch_from_sources(query: str, sources: List[str]):
    """
    Fetch data from requested MCP servers in parallel
    """
    tasks = []
    
    if "calendar" in sources:
        tasks.append(("calendar", mcp_manager.search_calendar(query)))
    if "notion" in sources:
        tasks.append(("notion", mcp_manager.search_notion(query)))
    if "drive" in sources:
        tasks.append(("drive", mcp_manager.search_drive(query)))
    
    results = {}
    for source_name, task in tasks:
        try:
            data = await task
            results[source_name] = data
        except Exception as e:
            print(f"Error fetching from {source_name}: {e}")
            results[source_name] = []
    
    return results


# OpenAI Query with Tools
async def query_with_openai(question: str, context_data: dict):
    """
    Query OpenAI with context from MCP servers
    """
    # Build context from all sources
    context = ""
    for source, items in context_data.items():
        if items:
            context += f"\n\n{source.upper()} Data:\n"
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        title = item.get('title', item.get('name', 'Untitled'))
                        content = item.get('content', item.get('description', ''))
                        context += f"- {title}: {content}\n"
    
    if not context.strip():
        return "No relevant information found in your knowledge base."
    
    # Create prompt
    prompt = f"""Based on the following information from the user's knowledge base, answer their question.

Context:
{context}

Question: {question}

Provide a comprehensive answer and cite which sources you used."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that searches through a user's personal knowledge base (Google Drive, Notion, Calendar) to answer questions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        return response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")


# Routes
@app.get("/")
def root():
    return {
        "message": "Knowledge Base Assistant API",
        "version": "1.0.0",
        "endpoints": {
            "/query": "POST - Ask questions across your knowledge base",
            "/health": "GET - Check API health"
        }
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """
    Query across Google Drive, Notion, and Calendar using MCP servers
    """
    try:
        # Step 1: Fetch data from MCP servers
        context_data = await fetch_from_sources(request.question, request.sources)
        
        # Step 2: Query OpenAI with context
        answer = await query_with_openai(request.question, context_data)
        
        # Step 3: Format response
        sources = []
        for source_name, items in context_data.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        sources.append(Source(
                            name=f"{source_name}/{item.get('title', item.get('name', 'Untitled'))}",
                            content=item.get('content', item.get('description', ''))[:200],
                            url=item.get('url', item.get('link'))
                        ))
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            tools_used=request.sources
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up MCP servers on shutdown"""
    await mcp_manager.cleanup()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)