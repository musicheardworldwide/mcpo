import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Dict, Any, Optional, List, Type, Union, ForwardRef

import uvicorn
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount


from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


from mcpo.utils.main import get_model_fields, get_tool_handler
from mcpo.utils.auth import get_verify_api_key


async def create_dynamic_endpoints(app: FastAPI, api_dependency=None):
    session: ClientSession = app.state.session
    if not session:
        raise ValueError("Session is not initialized in the app state.")

    result = await session.initialize()
    server_info = getattr(result, "serverInfo", None)
    if server_info:
        app.title = server_info.name or app.title
        app.description = (
            f"{server_info.name} MCP Server" if server_info.name else app.description
        )
        app.version = server_info.version or app.version

    tools_result = await session.list_tools()
    tools = tools_result.tools

    for tool in tools:
        endpoint_name = tool.name
        endpoint_description = tool.description
        schema = tool.inputSchema

        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})

        form_model_name = f"{endpoint_name}_form_model"

        model_fields = get_model_fields(
            form_model_name,
            properties,
            required_fields,
        )

        tool_handler = get_tool_handler(
            session, endpoint_name, form_model_name, model_fields
        )

        app.post(
            f"/{endpoint_name}",
            summary=endpoint_name.replace("_", " ").title(),
            description=endpoint_description,
            dependencies=[Depends(api_dependency)] if api_dependency else [],
        )(tool_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    command = getattr(app.state, "command", None)
    args = getattr(app.state, "args", [])
    env = getattr(app.state, "env", {})

    api_dependency = getattr(app.state, "api_dependency", None)

    if not command:
        async with AsyncExitStack() as stack:
            for route in app.routes:
                if isinstance(route, Mount) and isinstance(route.app, FastAPI):
                    await stack.enter_async_context(
                        route.app.router.lifespan_context(route.app),  # noqa
                    )
            yield

    else:
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env={**env},
        )

        async with stdio_client(server_params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                app.state.session = session
                await create_dynamic_endpoints(app, api_dependency=api_dependency)
                yield


async def run(
    host: str = "127.0.0.1",
    port: int = 8000,
    api_key: Optional[str] = "",
    cors_allow_origins=["*"],
    **kwargs,
):
    # Server API Key
    api_dependency = get_verify_api_key(api_key) if api_key else None

    # MCP Config
    config_path = kwargs.get("config")
    server_command = kwargs.get("server_command")

    name = kwargs.get("name") or "MCP OpenAPI Proxy"
    description = (
        kwargs.get("description") or "Automatically generated API from MCP Tool Schemas"
    )
    version = kwargs.get("version") or "1.0"

    ssl_certfile = kwargs.get("ssl_certfile")
    ssl_keyfile = kwargs.get("ssl_keyfile")
    path_prefix = kwargs.get("path_prefix") or "/"

    main_app = FastAPI(
        title=name,
        description=description,
        version=version,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        lifespan=lifespan,
    )

    main_app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if server_command:
        main_app.state.command = server_command[0]
        main_app.state.args = server_command[1:]
        main_app.state.env = os.environ.copy()

        main_app.state.api_dependency = api_dependency
    elif config_path:
        with open(config_path, "r") as f:
            config_data = json.load(f)

        mcp_servers = config_data.get("mcpServers", {})
        if not mcp_servers:
            raise ValueError("No 'mcpServers' found in config file.")

        main_app.description += "\n\n- **available tools**："
        for server_name, server_cfg in mcp_servers.items():
            sub_app = FastAPI(
                title=f"{server_name}",
                description=f"{server_name} MCP Server\n\n- [back to tool list](/docs)",
                version="1.0",
                lifespan=lifespan,
            )

            sub_app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_allow_origins or ["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

            sub_app.state.command = server_cfg["command"]
            sub_app.state.args = server_cfg.get("args", [])
            sub_app.state.env = {**os.environ, **server_cfg.get("env", {})}

            sub_app.state.api_dependency = api_dependency

            main_app.mount(f"{path_prefix}{server_name}", sub_app)
            main_app.description += f"\n    - [{server_name}](/{server_name}/docs)"
    else:
        raise ValueError("You must provide either server_command or config.")

    config = uvicorn.Config(
        app=main_app,
        host=host,
        port=port,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        log_level="info",
    )
    server = uvicorn.Server(config)

    await server.serve()
