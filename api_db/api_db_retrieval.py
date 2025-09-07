from asyncio import current_task
import os
import sys
import json
from typing import List, Dict, Tuple

import tree_sitter_java
from tree_sitter import Language, Parser, Query


# Set up Tree-sitter parser and language
JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)


# Retrieve all imported APIs from the original code file
def retrieve_existing_apis(java_file_path: str):
    # Read code (bytes)
    with open(java_file_path, 'rb') as f:
        code = f.read()
    tree = parser.parse(code)

    # Query for all import declarations
    query = Query(JAVA_LANGUAGE, "(import_declaration) @import")
    captures = query.captures(tree.root_node)

    # Add all import declarations to list
    imported_apis = []
    for name, nodes in captures.items():
        for node in nodes:
            snippet = code[node.start_byte:node.end_byte].decode('utf8')
            snippet = snippet[7:-1]
            imported_apis.append(snippet)

    return imported_apis


def get_api_db_path():
    # Set working directory to script's parent directory
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, ROOT_DIR)

    # Set path to API database
    API_DB_PATH = os.path.join(ROOT_DIR, "api_db.json")
    return API_DB_PATH


# Retrieve APIs by category, avoiding duplicates with existing APIs
def query_api_db(apis_to_retrieve: list, existing_apis: list):
    API_DB_PATH = get_api_db_path()
    retrieved_apis = []

    with open(API_DB_PATH, "r", encoding="utf-8") as f:
        api_db = json.load(f)
    for api_category in apis_to_retrieve:
        for api in api_db[api_category]:
            if api not in existing_apis:
                retrieved_apis.append(api)
    
    return retrieved_apis


# Function calling implementation for OpenAI agents
def get_api_categories() -> List[str]:
    """Get all available API categories from the database"""
    API_DB_PATH = get_api_db_path()
    with open(API_DB_PATH, "r", encoding="utf-8") as f:
        api_db = json.load(f)
    return list(api_db.keys())


def create_api_analysis_function():
    """Create the function schema for OpenAI function calling"""
    categories = get_api_categories()
    
    return [
        {
            "name": "analyze_api_needs",
            "description": "Analyze buggy Java code and determine which categories of APIs from the database are needed to fix it",
            "parameters": {
                "type": "object",
                "properties": {
                    "needed_categories": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": categories  # This forces exact category names
                        },
                        "description": "API categories needed to fix the bug"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explanation of why these categories are needed"
                    }
                },
                "required": ["needed_categories", "reasoning"]
            }
        }
    ]


def analyze_bug_for_apis(bug_context: str, existing_apis: List[str], gpt_client) -> Tuple[List[str], str]:
    """
    Analyze buggy Java code and determine which additional APIs from the database are needed.
    
    Args:
        bug_context: The complete context including all bugs and buggy nodes
        existing_apis: List of APIs already imported in the file
        gpt_client: GPTClient instance to make OpenAI calls
        
    Returns:
        Tuple of (additional_categories, reasoning)
    """
    functions = create_api_analysis_function()
    
    prompt = f"""
    Analyze this buggy Java code and determine which API categories from the database are needed to fix the bugs.
    
    Bug context:
    {bug_context}
    
    Additionally, these APIs have already been imported into the file:
    {existing_apis}
    
    Consider the intended functionality of the code and what types of APIs might be needed to supplement the existing ones.
    """
    
    # Make the API call with function calling
    response = gpt_client.send_prompt_with_functions(prompt, functions)
    
    if response.choices[0].message.function_call:
        function_name = response.choices[0].message.function_call.name
        function_args = json.loads(response.choices[0].message.function_call.arguments)
        
        if function_name == "analyze_api_needs":
            categories = function_args["needed_categories"]
            reasoning = function_args["reasoning"]
            return categories, reasoning
    
    return [], "No function call made"


def format_api_analysis(java_file_path: str, bug_context: str, gpt_client) -> str:
    """
    Complete API analysis for buggy code with full context.
    
    Args:
        java_file_path: Path to the Java file
        bug_context: The complete context including all bugs and buggy nodes
        gpt_client: GPTClient instance
        
    Returns:
        Formatted string with API analysis
    """
    # Step 1: Get existing APIs from the file first
    existing_apis = retrieve_existing_apis(java_file_path)
    
    # Step 2: Analyze what additional API categories are needed
    additional_categories, reasoning = analyze_bug_for_apis(bug_context, existing_apis, gpt_client)
    
    # Step 3: Get candidate APIs from identified categories (avoiding duplicates)
    candidate_apis = query_api_db(additional_categories, existing_apis)
    
    # Step 4: Create API context dictionary
    api_context = {
        'existing_apis': existing_apis,
        'candidate_apis': candidate_apis
    }
    
    result = ""
    result += f"After an analysis of the API usage, the following information has been obtained:\n"
    result += f"These APIs have already been imported: {existing_apis}\n"
    result += f"Additionally, some other APIs have been retrieved from the API database.\n"
    result += f"The following API categories were identified as needed: {additional_categories}\n"
    result += f"Here is the list of APIs that were retrieved from those categories: {candidate_apis}\n"
    result += f"Here is the reasoning for the retrieval: {reasoning}\n"
    
    return result