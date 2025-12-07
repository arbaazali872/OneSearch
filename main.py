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


def search_calendar_tool(start_date: str = None, end_date: str = None, query: str = None):
    """
    Tool function for OpenAI to call
    Search Google Calendar for events
    """
    try:
        print(f"[TOOL CALL] search_calendar - start: {start_date}, end: {end_date}, query: {query}")
        
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
                "name": "search_events",
                "arguments": params
            }
        )
        print(f"[TOOL RESULT] Calendar: {result}")
        return json.dumps(result)
    except Exception as e:
        print(f"Calendar tool error: {e}")
        traceback.print_exc()
        return json.dumps({"error": str(e)})


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


def search_notion_tool(query: str):
    """
    Tool function for OpenAI to call
    Search Notion pages and databases
    """
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
        print(f"[TOOL RESULT] Notion: {result}")
        return json.dumps(result)
    except Exception as e:
        print(f"Notion tool error: {e}")
        traceback.print_exc()
        return json.dumps({"error": str(e)})


async def search_drive(query: str) -> List[Dict]:
    """Google Drive removed - not implemented"""
    return []


# OpenAI Tools Definition
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_calendar",
            "description": "Search Google Calendar for events. Use this to find meetings, appointments, and scheduled events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (e.g., 2024-12-07)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (e.g., 2024-12-14)"
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
    "search_calendar": search_calendar_tool,
    "search_notion": search_notion_tool
}


async def query_with_openai_tools(question: str):
    """
    Query OpenAI with function calling - it decides which tools to use
    """
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to the user's Notion and Google Calendar. Use the available tools to search for information and answer questions accurately."
        },
        {
            "role": "user",
            "content": question
        }
    ]
    
    try:
        # Initial call to OpenAI with tools
        print(f"[DEBUG] Calling OpenAI with question: {question}")
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        # If no tool calls, return the response
        if not tool_calls:
            return {
                "answer": response_message.content,
                "tool_calls": [],
                "sources": []
            }
        
        # Execute tool calls
        messages.append(response_message)
        
        tool_results = []
        sources = []
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"[DEBUG] OpenAI wants to call: {function_name} with {function_args}")
            
            # Execute the tool
            if function_name in TOOL_FUNCTIONS:
                function_response = TOOL_FUNCTIONS[function_name](**function_args)
                tool_results.append({
                    "tool": function_name,
                    "result": function_response
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
                
                # Add tool result to messages
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response
                })
        
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
        
        # Let OpenAI decide which tools to call
        result = await query_with_openai_tools(request.question)
        
        # Format response
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