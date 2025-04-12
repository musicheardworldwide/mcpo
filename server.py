# custom_interpreter_server.py
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from interpreter import interpreter
from typing import List, Optional
import uvicorn
import os
import logging

# Configuration
LLM_MODEL = "openai/deepseek-chat"
API_BASE = "https://api.deepseek.com/v1"
API_KEY = os.getenv("INTERPRETER_API_KEY", "sk-7fd014d945684bf5b00c27c092d8866c")
PORT = 8000

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Open Interpreter with DeepSeek
interpreter.llm.api_key = API_KEY
interpreter.llm.model = LLM_MODEL
interpreter.llm.api_base = API_BASE
interpreter.llm.temperature = 0.1
interpreter.auto_run = True
interpreter.verbose = False

# FastAPI App
app = FastAPI(
    title="OpenInterpreter Server",
    description="Custom OpenInterpreter server with DeepSeek integration",
    version="0.1.0"
)

# Security
api_key_header = APIKeyHeader(name="X-API-KEY")

def get_api_key(api_key: str = Security(api_key_header)) -> str:
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# Models
class CodeExecutionRequest(BaseModel):
    code: str
    timeout: Optional[int] = 300

class ToolRegistrationRequest(BaseModel):
    name: str
    description: str
    code: str

class ChatRequest(BaseModel):
    message: str
    tools: Optional[List[str]] = None

# Custom Tools Registry
CUSTOM_TOOLS = {}

# API Endpoints
@app.post("/execute", summary="Execute Python code")
async def execute_code(
    request: CodeExecutionRequest,
    api_key: str = Security(get_api_key)
):
    """Execute arbitrary Python code securely"""
    try:
        result = interpreter.chat(f"""
        Please execute this code and return only the output:
        ```python
        {request.code}
        ```
        """)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Execution failed: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/chat", summary="Chat with interpreter")
async def chat_with_interpreter(
    request: ChatRequest,
    api_key: str = Security(get_api_key)
):
    """Have a conversation with the interpreter, optionally using specific tools"""
    try:
        if request.tools:
            active_tools = {name: CUSTOM_TOOLS[name] for name in request.tools if name in CUSTOM_TOOLS}
            interpreter.reset()
            for name, tool in active_tools.items():
                interpreter.tool(name, tool["description"])(eval(tool["code"]))
        
        response = interpreter.chat(request.message)
        return {"response": response}
    except Exception as e:
        logger.error(f"Chat failed: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/tools/register", summary="Register a custom tool")
async def register_tool(
    request: ToolRegistrationRequest,
    api_key: str = Security(get_api_key)
):
    """Register a new custom tool for the interpreter"""
    try:
        # Validate the tool code
        compiled = compile(request.code, '<string>', 'exec')
        
        CUSTOM_TOOLS[request.name] = {
            "description": request.description,
            "code": request.code
        }
        
        logger.info(f"Registered new tool: {request.name}")
        return {"success": True, "tool": request.name}
    except Exception as e:
        logger.error(f"Tool registration failed: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/tools/list", summary="List available tools")
async def list_tools(api_key: str = Security(get_api_key)):
    """List all registered custom tools"""
    return {"tools": list(CUSTOM_TOOLS.keys())}

@app.post("/reset", summary="Reset interpreter state")
async def reset_interpreter(api_key: str = Security(get_api_key)):
    """Reset the interpreter's state and memory"""
    interpreter.reset()
    return {"success": True}

# Example Custom Tools (pre-registered)
CUSTOM_TOOLS.update({
    "file_stats": {
        "description": "Get statistics about a file",
        "code": """
def file_stats(filename):
    import os
    stat = os.stat(filename)
    return {
        'size': stat.st_size,
        'last_modified': stat.st_mtime,
        'is_dir': os.path.isdir(filename)
    }
"""
    },
    "web_fetch": {
        "description": "Fetch content from a URL",
        "code": """
def web_fetch(url):
    import requests
    response = requests.get(url)
    return {
        'status': response.status_code,
        'content': response.text[:1000] + '...' if len(response.text) > 1000 else response.text
    }
"""
    }
})

if __name__ == "__main__":
    logger.info(f"Starting OpenInterpreter server with {LLM_MODEL} at {API_BASE}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)