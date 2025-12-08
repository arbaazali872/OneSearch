from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from queue import Queue, Empty
import os
import json
import subprocess
import threading
import traceback
import sys
import shutil
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="Knowledge Base Assistant API")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Find npx executable
def get_npx_command():
    """Get the correct npx command for the platform"""
    if sys.platform == "win32":
        npx_path = shutil.which("npx.cmd") or shutil.which("npx")
        if npx_path:
            return npx_path
        possible_paths = [
            r"C:\Program Files\nodejs\npx.cmd",
            r"C:\Program Files (x86)\nodejs\npx.cmd",
            os.path.expanduser(r"~\AppData\Roaming\npm\npx.cmd")
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return "npx"
    else:
        return "npx"

NPX_CMD = get_npx_command()
print(f"[DEBUG] Using npx command: {NPX_CMD}")

# MCP Server configurations
MCP_SERVERS = {
    "calendar": {
        "command": NPX_CMD,
        "args": ["@cocal/google-calendar-mcp"],
        "env": {
            "GOOGLE_OAUTH_CREDENTIALS": os.getenv("GOOGLE_OAUTH_CREDENTIALS")
        }
    },
    "notion": {
        "command": NPX_CMD,
        "args": ["@notionhq/notion-mcp-server"],
        "env": {
            "NOTION_TOKEN": os.getenv("NOTION_TOKEN")
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
            return
        
        if server_name not in MCP_SERVERS:
            raise ValueError(f"Unknown server: {server_name}")
        
        server_config = MCP_SERVERS[server_name]
        env = {**os.environ, **server_config["env"]}
        
        print(f"[DEBUG] Starting {server_name} MCP server...")
        
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
        
        reader_thread = threading.Thread(
            target=self._read_output,
            args=(server_name, process),
            daemon=True
        )
        reader_thread.start()
        self.reader_threads[server_name] = reader_thread
        stderr_thread = threading.Thread(
        target=self._read_stderr,
        args=(server_name, process),
        daemon=True
        )
        stderr_thread.start()
        
        print(f"[DEBUG] {server_name} MCP server started (PID: {process.pid})")
        import time
        time.sleep(0.5)  # Let server start
        
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print(f"[DEBUG] Sending initialize to {server_name}")
        process.stdin.write(json.dumps(init_request) + "\n")
        process.stdin.flush()
        try:
            init_response = self.response_queues[server_name].get(timeout=5)
            print(f"[DEBUG] {server_name} initialized: {init_response}")
            
            # Send initialized notification (MCP protocol requirement)
            initialized_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            process.stdin.write(json.dumps(initialized_notif) + "\n")
            process.stdin.flush()
            
        except Empty:
            print(f"[WARN] {server_name} initialize timeout")
            # Wait for initialize response
        # time.sleep(1)
    def _read_output(self, server_name: str, process: subprocess.Popen):
        """Read JSON-RPC responses from stdout with proper HTTP-style framing"""
        try:
            while True:
                # Read headers
                headers = {}
                while True:
                    line = process.stdout.readline()
                    if not line:
                        return
                    line = line.strip()
                    if not line:  # Empty line = end of headers
                        break
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip()] = value.strip()
                
                # Read JSON body
                if 'Content-Length' in headers:
                    length = int(headers['Content-Length'])
                    body = process.stdout.read(length)
                    print(f"[DEBUG] {server_name} response: {body}")
                    try:
                        response = json.loads(body)
                        self.response_queues[server_name].put(response)
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] {server_name} JSON decode error: {e}")
                        print(f"[ERROR] Body was: {body}")
        except Exception as e:
            print(f"[ERROR] Reader thread for {server_name} crashed: {e}")
            traceback.print_exc()
    
    def _read_stderr(self, server_name: str, process: subprocess.Popen):
        """Read stderr output for debugging"""
        try:
            for line in process.stderr:
                print(f"[STDERR {server_name}] {line.strip()}")
        except Exception as e:
            print(f"[ERROR] stderr reader for {server_name}: {e}")
    
    def call_server(self, server_name: str, method: str, params: Dict[str, Any], timeout: int = 10):
        """Call an MCP server with JSON-RPC request"""
        if server_name not in self.processes:
            self.start_server(server_name)
        
        process = self.processes[server_name]
        queue = self.response_queues[server_name]
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        print(f"[DEBUG] Sending to {server_name}: {request}")
        
        try:
            request_json = json.dumps(request) + "\n"
            process.stdin.write(request_json)
            process.stdin.flush()
        except Exception as e:
            print(f"[ERROR] Failed to write to {server_name}: {e}")
            traceback.print_exc()
            raise
        
        try:
            response = queue.get(timeout=timeout)
            print(f"[DEBUG] Response from {server_name}: {response}")
            
            if "error" in response:
                raise Exception(f"MCP Server Error: {response['error']}")
            
            return response.get("result", {})
        except Empty:
            raise Exception(f"Timeout waiting for response from {server_name}")
    
    def cleanup(self):
        """Stop all MCP server processes"""
        for name, process in self.processes.items():
            print(f"[DEBUG] Stopping {name} MCP server...")
            process.terminate()
            process.wait(timeout=5)


# Initialize MCP manager
mcp_manager = MCPProcessManager()


def list_calendar_tool(start_date: str = None, end_date: str = None, query: str = None):
    """Tool function for OpenAI to call - List/search calendar events"""
    try:
        print(f"[TOOL CALL] list_calendar - start: {start_date}, end: {end_date}, query: {query}")
        
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if query:
            params["query"] = query
            
        result = mcp_manager.call_server(
            "calendar",
            "tools/call",
            {
                "name": "list-events",
                "arguments": params
            }
        )
        
        # Handle error responses
        if isinstance(result, dict) and result.get("isError"):
            error_msg = result.get("content", [{}])[0].get("text", "Unknown error")
            return json.dumps({"error": f"Calendar error: {error_msg}"})
        
        print(f"[TOOL RESULT] Calendar: {result}")
        return json.dumps(result)
    except Exception as e:
        print(f"Calendar tool error: {e}")
        traceback.print_exc()
        return json.dumps({"error": str(e)})


def search_notion_tool(query: str):
    """Tool function for OpenAI to call - Search Notion pages"""
    try:
        print(f"[TOOL CALL] search_notion - query: {query}")
        
        result = mcp_manager.call_server(
            "notion",
            "tools/call",
            {
                "name": "search",
                "arguments": {"query": query}
            }
        )
        
        # Handle error responses
        if isinstance(result, dict) and result.get("isError"):
            error_msg = result.get("content", [{}])[0].get("text", "Unknown error")
            return json.dumps({"error": f"Notion error: {error_msg}"})
        
        print(f"[TOOL RESULT] Notion: {result}")
        return json.dumps(result)
    except Exception as e:
        print(f"Notion tool error: {e}")
        traceback.print_exc()
        return json.dumps({"error": str(e)})


# OpenAI Tools Definition
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_calendar",
            "description": "List or search Google Calendar events. Use this to find meetings, appointments, and scheduled events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (e.g., 2025-12-07)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (e.g., 2025-12-14)"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for event titles or descriptions"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_notion",
            "description": "Search Notion pages and databases. Use this to find notes, documents, project information, and tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find in Notion pages"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Map function names to actual functions
TOOL_FUNCTIONS = {
    "list_calendar": list_calendar_tool,
    "search_notion": search_notion_tool
}


async def query_with_openai_tools(question: str):
    """Query OpenAI with function calling - it decides which tools to use"""
    today = datetime.now().strftime('%Y-%m-%d')
    messages = [
        {
            "role": "system",
            "content": f"You are a helpful assistant with access to the user's Notion and Google Calendar. Today's date is {today}. Use the available tools to search for information and answer questions accurately."
        },
        {
            "role": "user",
            "content": question
        }
    ]
    
    try:
        print(f"[DEBUG] Calling OpenAI with question: {question}")
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        if not tool_calls:
            return {
                "answer": response_message.content,
                "tool_calls": [],
                "sources": []
            }
        
        # Add assistant message with tool calls
        messages.append(response_message)
        
        tool_results = []
        sources = []
        
        # Execute each tool call and add response immediately
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"[DEBUG] OpenAI wants to call: {function_name} with {function_args}")
            
            if function_name in TOOL_FUNCTIONS:
                function_response = TOOL_FUNCTIONS[function_name](**function_args)
                tool_results.append({
                    "tool": function_name,
                    "result": function_response
                })
                
                # Add tool response immediately (CRITICAL FIX)
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response
                })
                
                # Parse results for sources
                try:
                    result_data = json.loads(function_response)
                    if isinstance(result_data, list):
                        for item in result_data:
                            if isinstance(item, dict):
                                sources.append({
                                    "name": f"{function_name}/{item.get('title', 'Untitled')}",
                                    "content": item.get('content', '')[:200],
                                    "url": item.get('url', '')
                                })
                except:
                    pass
        
        # Get final response from OpenAI with tool results
        print(f"[DEBUG] Getting final answer from OpenAI with tool results")
        final_response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=messages
        )
        
        return {
            "answer": final_response.choices[0].message.content,
            "tool_calls": [tc.function.name for tc in tool_calls],
            "sources": sources
        }
        
    except Exception as e:
        print(f"OpenAI tool calling error: {e}")
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
    Query across Notion and Calendar using OpenAI function calling
    OpenAI decides which tools to call based on the question
    """
    try:
        print(f"[DEBUG] Processing query: {request.question}")
        
        result = await query_with_openai_tools(request.question)
        
        sources = []
        for source_data in result["sources"]:
            sources.append(Source(
                name=source_data["name"],
                content=source_data["content"],
                url=source_data.get("url")
            ))
        
        return QueryResponse(
            answer=result["answer"],
            sources=sources,
            tools_used=result["tool_calls"]
        )
    
    except Exception as e:
        print(f"Query error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)