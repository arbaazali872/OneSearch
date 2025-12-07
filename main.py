from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="Knowledge Base Assistant API")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# MCP Server endpoints (these will be running separately)
MCP_SERVERS = {
    "calendar": os.getenv("CALENDAR_MCP_URL", "http://localhost:3001"),
    "notion": os.getenv("NOTION_MCP_URL", "http://localhost:3002"),
    "drive": os.getenv("DRIVE_MCP_URL", "http://localhost:3003")
}


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


# MCP Server Communication via HTTP
async def call_mcp_server(server_url: str, method: str, params: Dict[str, Any]) -> Any:
    """
    Call MCP server via HTTP
    """
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            response = await http_client.post(
                f"{server_url}/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                raise Exception(f"MCP Server Error: {data['error']}")
            
            return data.get("result", {})
        except httpx.ConnectError:
            raise Exception(f"Cannot connect to MCP server at {server_url}. Is it running?")
        except Exception as e:
            raise Exception(f"MCP Server communication error: {str(e)}")


async def search_calendar(query: str) -> List[Dict]:
    """Search Google Calendar via MCP server"""
    try:
        result = await call_mcp_server(
            MCP_SERVERS["calendar"],
            "tools/call",
            {
                "name": "search_events",
                "arguments": {"query": query}
            }
        )
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Calendar search error: {e}")
        return []


async def search_notion(query: str) -> List[Dict]:
    """Search Notion via MCP server"""
    try:
        result = await call_mcp_server(
            MCP_SERVERS["notion"],
            "tools/call",
            {
                "name": "search",
                "arguments": {"query": query}
            }
        )
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Notion search error: {e}")
        return []


async def search_drive(query: str) -> List[Dict]:
    """Search Google Drive via MCP server"""
    try:
        result = await call_mcp_server(
            MCP_SERVERS["drive"],
            "tools/call",
            {
                "name": "search_files",
                "arguments": {"query": query}
            }
        )
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Drive search error: {e}")
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
    if "drive" in sources:
        tasks["drive"] = search_drive(query)
    
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
            "/health": "GET - Check API health",
            "/servers/status": "GET - Check MCP servers status"
        }
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/servers/status")
async def check_servers_status():
    """Check if all MCP servers are running"""
    status = {}
    
    async with httpx.AsyncClient(timeout=5.0) as http_client:
        for name, url in MCP_SERVERS.items():
            try:
                response = await http_client.get(f"{url}/health")
                status[name] = "running" if response.status_code == 200 else "error"
            except:
                status[name] = "not running"
    
    return {"servers": status}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)