from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import json
import subprocess
import threading
import traceback
from queue import Queue
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="Knowledge Base Assistant API")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# MCP Server configurations
MCP_SERVERS = {
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
    }
}


# Schemas
class QueryRequest(BaseModel):
    question: str
    sources: Optional[List[str]] = ["notion", "calendar"]


class Source(BaseModel):
    name: str
    content: str
    url: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    tools_used: List[str]


# MCP Process Manager with Popen
class MCPProcessManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.response_queues: Dict[str, Queue] = {}
        self.reader_threads: Dict[str, threading.Thread] = {}
    
    def start_server(self, server_name: str):
        """Start an MCP server process"""
        if server_name in self.processes:
            return  # Already running
        
        if server_name not in MCP_SERVERS:
            raise ValueError(f"Unknown server: {server_name}")
        
        server_config = MCP_SERVERS[server_name]
        env = {**os.environ, **server_config["env"]}
        
        print(f"[DEBUG] Starting {server_name} MCP server...")
        
        # Start process with PIPE
        process = subprocess.Popen(
            [server_config["command"]] + server_config["args"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1
        )
        
        self.processes[server_name] = process
        self.response_queues[server_name] = Queue()
        
        # Start reader thread for stdout
        reader_thread = threading.Thread(
            target=self._read_output,
            args=(server_name, process),
            daemon=True
        )
        reader_thread.start()
        self.reader_threads[server_name] = reader_thread
        
        print(f"[DEBUG] {server_name} MCP server started (PID: {process.pid})")
    
    def _read_output(self, server_name: str, process: subprocess.Popen):
        """Read JSON-RPC responses from stdout"""
        try:
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                
                line = line.strip()
                if line:
                    print(f"[DEBUG] {server_name} stdout: {line}")
                    try:
                        response = json.loads(line)
                        self.response_queues[server_name].put(response)
                    except json.JSONDecodeError:
                        print(f"[DEBUG] {server_name} non-JSON output: {line}")
        except Exception as e:
            print(f"[ERROR] Reader thread for {server_name} crashed: {e}")
            traceback.print_exc()
    
    def call_server(self, server_name: str, method: str, params: Dict[str, Any], timeout: int = 10):
        """
        Call an MCP server with JSON-RPC request
        """
        if server_name not in self.processes:
            self.start_server(server_name)
        
        process = self.processes[server_name]
        queue = self.response_queues[server_name]
        
        # Prepare JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        print(f"[DEBUG] Sending to {server_name}: {request}")
        
        # Send request to stdin
        try:
            request_json = json.dumps(request) + "\n"
            process.stdin.write(request_json)
            process.stdin.flush()
        except Exception as e:
            print(f"[ERROR] Failed to write to {server_name}: {e}")
            traceback.print_exc()
            raise
        
        # Wait for response from queue
        try:
            import queue
            response = queue.get(timeout=timeout)
            print(f"[DEBUG] Response from {server_name}: {response}")
            
            if "error" in response:
                raise Exception(f"MCP Server Error: {response['error']}")
            
            return response.get("result", {})
        except queue.Empty:
            raise Exception(f"Timeout waiting for response from {server_name}")
    
    def cleanup(self):
        """Stop all MCP server processes"""
        for name, process in self.processes.items():
            print(f"[DEBUG] Stopping {name} MCP server...")
            process.terminate()
            process.wait(timeout=5)


# Initialize MCP manager
mcp_manager = MCPProcessManager()


async def search_calendar(query: str) -> List[Dict]:
    """Search Google Calendar via MCP server"""
    try:
        print(f"[DEBUG] Searching calendar with query: {query}")
        result = mcp_manager.call_server(
            "calendar",
            "tools/call",
            {
                "name": "search_events",
                "arguments": {"query": query}
            }
        )
        print(f"[DEBUG] Calendar result: {result}")
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Calendar search error: {e}")
        traceback.print_exc()
        return []


async def search_notion(query: str) -> List[Dict]:
    """Search Notion via MCP server"""
    try:
        print(f"[DEBUG] Searching Notion with query: {query}")
        result = mcp_manager.call_server(
            "notion",
            "tools/call",
            {
                "name": "search",
                "arguments": {"query": query}
            }
        )
        print(f"[DEBUG] Notion result: {result}")
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Notion search error: {e}")
        traceback.print_exc()
        return []


async def search_drive(query: str) -> List[Dict]:
    """Google Drive removed - not implemented"""
    return []


async def fetch_from_sources(query: str, sources: List[str]) -> Dict[str, List]:
    """
    Fetch data from requested MCP servers in parallel
    """
    import asyncio
    
    tasks = {}
    if "calendar" in sources:
        tasks["calendar"] = search_calendar(query)
    if "notion" in sources:
        tasks["notion"] = search_notion(query)
    
    # Execute all tasks in parallel
    results = {}
    completed = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    for (source_name, _), result in zip(tasks.items(), completed):
        if isinstance(result, Exception):
            print(f"Error fetching from {source_name}: {result}")
            results[source_name] = []
        else:
            results[source_name] = result
    
    return results


async def query_with_openai(question: str, context_data: Dict) -> str:
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
            model="gpt-4o-nano",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that searches through a user's personal knowledge base (Notion, Calendar) to answer questions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"OpenAI API error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")


# Routes
@app.get("/")
def root():
    return {
        "message": "Knowledge Base Assistant API",
        "version": "1.0.0",
        "endpoints": {
            "/query": "POST - Ask questions across your knowledge base",
            "/health": "GET - Check API health",
            "/servers/status": "GET - Check MCP servers status"
        }
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/servers/status")
def check_servers_status():
    """Check if all MCP servers are running"""
    status = {}
    
    for name in MCP_SERVERS.keys():
        if name in mcp_manager.processes:
            process = mcp_manager.processes[name]
            if process.poll() is None:
                status[name] = "running"
            else:
                status[name] = "stopped"
        else:
            status[name] = "not started"
    
    return {"servers": status}


@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """
    Query across Notion and Calendar using MCP servers
    """
    try:
        # Step 1: Fetch data from MCP servers
        print(f"[DEBUG] Fetching from sources: {request.sources}")
        context_data = await fetch_from_sources(request.question, request.sources)
        print(f"[DEBUG] Context data: {context_data}")
        
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
        print(f"Query error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)