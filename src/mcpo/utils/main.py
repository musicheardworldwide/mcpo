from typing import Any, Dict, List, Type, Union, ForwardRef
from pydantic import create_model, Field
from pydantic.fields import FieldInfo
from mcp import ClientSession, types
from mcp.types import CallToolResult

import json


def process_tool_response(result: CallToolResult) -> list:
    """Universal response processor for all tool endpoints"""
    response = []
    for content in result.content:
        if isinstance(content, types.TextContent):
            text = content.text
            if isinstance(text, str):
                try:
                    text = json.loads(text)
                except json.JSONDecodeError:
                    pass
            response.append(text)
        elif isinstance(content, types.ImageContent):
            image_data = f"data:{content.mimeType};base64,{content.data}"
            response.append(image_data)
        elif isinstance(content, types.EmbeddedResource):
            # TODO: Handle embedded resources
            response.append("Embedded resource not supported yet.")
    return response


def _process_schema_property(
    _model_cache: Dict[str, Type],
    prop_schema: Dict[str, Any],
    model_name_prefix: str,
    prop_name: str,
    is_required: bool,
) -> tuple[Union[Type, List, ForwardRef, Any], FieldInfo]:
    """
    Recursively processes a schema property to determine its Python type hint
    and Pydantic Field definition.

    Returns:
        A tuple containing (python_type_hint, pydantic_field).
        The pydantic_field contains default value and description.
    """
    prop_type = prop_schema.get("type")
    prop_desc = prop_schema.get("description", "")
    default_value = ... if is_required else prop_schema.get("default", None)
    pydantic_field = Field(default=default_value, description=prop_desc)

    if prop_type == "object":
        nested_properties = prop_schema.get("properties", {})
        nested_required = prop_schema.get("required", [])
        nested_fields = {}

        nested_model_name = f"{model_name_prefix}_{prop_name}_model".replace(
            "__", "_"
        ).rstrip("_")

        if nested_model_name in _model_cache:
            return _model_cache[nested_model_name], pydantic_field

        for name, schema in nested_properties.items():
            is_nested_required = name in nested_required
            nested_type_hint, nested_pydantic_field = _process_schema_property(
                schema, nested_model_name, name, is_nested_required
            )

            nested_fields[name] = (nested_type_hint, nested_pydantic_field)

        if not nested_fields:
            return Dict[str, Any], pydantic_field

        NestedModel = create_model(nested_model_name, **nested_fields)
        _model_cache[nested_model_name] = NestedModel

        return NestedModel, pydantic_field

    elif prop_type == "array":
        items_schema = prop_schema.get("items")
        if not items_schema:
            # Default to list of anything if items schema is missing
            return List[Any], pydantic_field

        # Recursively determine the type of items in the array
        item_type_hint, _ = _process_schema_property(
            items_schema,
            f"{model_name_prefix}_{prop_name}",
            "item",
            False,  # Items aren't required at this level
        )
        list_type_hint = List[item_type_hint]
        return list_type_hint, pydantic_field

    elif prop_type == "string":
        return str, pydantic_field
    elif prop_type == "integer":
        return int, pydantic_field
    elif prop_type == "boolean":
        return bool, pydantic_field
    elif prop_type == "number":
        return float, pydantic_field
    else:
        return Any, pydantic_field


def get_model_fields(form_model_name, properties, required_fields):
    model_fields = {}

    _model_cache: Dict[str, Type] = {}

    for param_name, param_schema in properties.items():
        is_required = param_name in required_fields
        python_type_hint, pydantic_field_info = _process_schema_property(
            _model_cache, param_schema, form_model_name, param_name, is_required
        )
        # Use the generated type hint and Field info
        model_fields[param_name] = (python_type_hint, pydantic_field_info)
    return model_fields


def get_tool_handler(session, endpoint_name, form_model_name, model_fields):
    if model_fields:
        FormModel = create_model(form_model_name, **model_fields)

        def make_endpoint_func(
            endpoint_name: str, FormModel, session: ClientSession
        ):  # Parameterized endpoint

            async def tool(form_data: FormModel):
                args = form_data.model_dump(exclude_none=True)
                print(f"Calling endpoint: {endpoint_name}, with args: {args}")

                result = await session.call_tool(endpoint_name, arguments=args)
                return process_tool_response(result)

            return tool

        tool_handler = make_endpoint_func(endpoint_name, FormModel, session)
    else:

        def make_endpoint_func_no_args(
            endpoint_name: str, session: ClientSession
        ):  # Parameterless endpoint
            async def tool():  # No parameters
                print(f"Calling endpoint: {endpoint_name}, with no args")
                result = await session.call_tool(
                    endpoint_name, arguments={}
                )  # Empty dict
                return process_tool_response(result)  # Same processor

            return tool

        tool_handler = make_endpoint_func_no_args(endpoint_name, session)
