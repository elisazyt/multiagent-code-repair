"""
https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/components/tools.html
This file only contains the function schema definition
The actual ContextRetrievalAgent implementation is in agents.py
"""

def create_context_retrieval_function():
    """Create the function schema for OpenAI function calling"""
    return {
        "name": "request_context",
        "description": "Request context retrieval for specific files and functions",
        "parameters": {
            "type": "object",
            "properties": {
                "file_functions": {
                    "type": "object",
                    "description": "Map file paths to list of function calls. Each function call is a dict with exactly one function name mapping to its arguments object. Arguments object can only contain keys: 'start_line', 'end_line', or 'variable'.",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "description": "A single function call: dict with exactly one function name -> its arguments object",
                            "additionalProperties": {
                                "type": "object",
                                "description": "Arguments for the function. Allowed keys: 'start_line' (int), 'end_line' (int), 'var' (string). Functions needing bug locations must provide 'start_line' and 'end_line'. Functions needing variables must provide 'var'.",
                                "properties": {
                                    "start_line": {"type": "integer"},
                                    "end_line": {"type": "integer"},
                                    "var": {"type": "string"}
                                },
                                "additionalProperties": False
                            },
                            "minProperties": 1,
                            "maxProperties": 1
                        }
                    }
                },
                "selected_methods": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For 2-hop APIs only: select 1-3 methods from 1-hop results to expand. Leave empty for other functions."
                },
                "reasoning": {
                    "type": "string",
                    "description": "Why these functions/methods were selected"
                }
            },
            "required": ["file_functions", "reasoning"]
        }
    }