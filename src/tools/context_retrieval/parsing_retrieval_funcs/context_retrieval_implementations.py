"""
Actual implementations of the context retrieval functions, defined in context_retrieval_functions.py
"""

import json
import re
from typing import List, Tuple

import tree_sitter_java
from tree_sitter import Language, Parser, Query, Node

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

from . import tree_sitter_utils as ib
from .joern_session import JoernSession
from .joern_utils import (
    get_full_method_signature_from_line_numbers,
    get_buggy_variable_type,
    get_apis_from_var_type,
    parse_joern_json_with_unescaped_quotes,
)


def get_comments_before_node(java_file_path: str, node: Node) -> Node:
    """
    Retrieve the comment node right before a given node using tree-sitter.
    Returns the comment node, or None if no comments found.
    Note: this only works for comments that are directly before the target node, with no blank lines in between.
    """
    try:
        # Read the file to get the code bytes
        with open(java_file_path, 'rb') as f:
            code = f.read()
        tree = parser.parse(code)
        
        # Get the node's start position
        node_start_point = node.start_point
        
        # Find all comment nodes in the file
        query = Query(JAVA_LANGUAGE, """
        (block_comment) @block_comment
        (line_comment) @line_comment
        """)
                
        try:
            # Try the direct API first (works in some environments)
            captures = query.captures(tree.root_node)
            # captures should be a dict: {capture_name: [nodes]}
            for capture_name in ['block_comment', 'line_comment']:
                if capture_name in captures:
                    for captured_node in captures[capture_name]:
                        comment_end_point = captured_node.end_point
                        if (comment_end_point[0] == node_start_point[0] - 1 or
                            comment_end_point[0] == node_start_point[0]):
                            return captured_node
        except AttributeError:
            # If .captures() doesn't exist, manually traverse the tree for comments
            # This avoids needing QueryCursor
            def find_comments_before(node, target_line):
                """Recursively find comment nodes before target line"""
                comments = []
                if node.type in ('block_comment', 'line_comment'):
                    if node.end_point[0] <= target_line:
                        comments.append(node)
                for child in node.children:
                    comments.extend(find_comments_before(child, target_line))
                return comments
            
            all_comments = find_comments_before(tree.root_node, node_start_point[0])
            # Find the comment closest to (but before) the target node
            for comment in reversed(all_comments):  # Check from bottom up
                comment_end_point = comment.end_point
                if (comment_end_point[0] == node_start_point[0] - 1 or
                    comment_end_point[0] == node_start_point[0]):
                    return comment
        
        return None
    except Exception as e:
        print(f"[ERROR] get_comments_before_node hit an exception: {e}")
        return None


def get_full_signatures_in_buggy_class(session: JoernSession, java_file_path: str, line_numbers: Tuple[int, int]) -> List[str]:
    """
    Get all function signatures in the buggy class.
    
    Args:
        java_file_path: Path to the Java file containing the bug
        line_numbers: Tuple of (start_line, end_line) to search
        
    Returns:
        List of function signatures
    """
    # Step 1: Use tree-sitter to find the class containing the bug
    class_node = ib.retrieve_buggy_class(java_file_path, line_numbers)
    if class_node:
        # Extract class name from tree-sitter node
        class_name = ib.extract_class_name_from_node(class_node, java_file_path)
        
        # Step 2: Use class name in Joern query
        query = f'cpg.typeDecl.name("{class_name}").method.map(m => (m.name, m.fullName)).toJson'
        stdout, _ = session.run_joern_query(query)
        if not stdout:
            return []
        
        try:
            # Extract JSON string from Joern output
            lines = stdout.strip().split('\n')
            json_str = None
            for line in lines:
                # Strip ANSI color codes
                line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                # Look for the JSON output line
                if 'val res' in line_clean and 'String = ' in line_clean:
                    # Extract the JSON string from the output
                    json_start = line_clean.find('String = ') + 8
                    json_str = line_clean[json_start:].strip()
                    # Remove any extra quotes at the beginning and end
                    while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                        json_str = json_str[1:-1]
                    # Handle escaped quotes
                    json_str = json_str.replace('\\"', '"')
                    break
            
            if not json_str:
                return []
            
            # Parse the JSON
            data = json.loads(json_str)
            
            # If data is still a string, try parsing it again
            if isinstance(data, str):
                data = json.loads(data)
            
            # Extract method full names from the list of dicts
            # Format: [{"methodName": "fullName"}, ...]
            method_signatures = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        # Each dict has one key-value pair: {methodName: fullName}
                        method_signatures.extend(item.values())
            
            return method_signatures
        except Exception as e:
            print(f"[ERROR] get_full_signatures_in_buggy_class hit an exception: {e}")
            return []
    
    return []


def get_apis_from_var(session: JoernSession, java_file_path: str, var_name: str, line_numbers: Tuple[int, int], reference_checkout_dir: str) -> List[str]:
    """
    Get all APIs (methods) available for a variable by first getting its type, then retrieving APIs for that type.
    
    Args:
        java_file_path: Path to the Java file containing the bug
        var_name: Name of the variable to get APIs for
        line_numbers: Tuple of (start_line, end_line) where the variable is used
        reference_checkout_dir: Defects4J reference checkout (e.g. .../Closure3/reference_checkout)
        
    Returns:
        List of method signatures (as strings), or empty list if error or variable type not found
    """
    # First, get the variable type
    variable_type = get_buggy_variable_type(session, java_file_path, var_name, line_numbers)
    
    if variable_type is None:
        print(f"[ERROR] get_apis_from_var: Could not determine type for variable '{var_name}' at lines {line_numbers}")
        return []
    
    # Then, get APIs for that type
    return get_apis_from_var_type(variable_type, reference_checkout_dir)


def get_function_callers(session: JoernSession, java_file_path: str, line_numbers: Tuple[int, int], class_name: str) -> List[Tuple[int, str]]:
    """
    Get all function callers of a given function.
    
    Args:
        java_file_path: Path to the Java file containing the bug
        line_numbers: Tuple of (start_line, end_line) to search
        class_name: Class name (e.g., "CategoryPlot") to filter method signature lookup
        
    Returns:
        List of tuples (line_number, content) where the function is called
    """
    if not session.project_name:
        raise RuntimeError("No project loaded. Call load_cpg() first.")
    
    method_signature = get_full_method_signature_from_line_numbers(session, java_file_path, line_numbers, class_name)
    if not method_signature:
        return []

    # Find calls to this method and get the line number where the call occurs
    # Search entire project for callers (callers can be in any file)
    query = f'cpg.call.filter(call => call.methodFullName == "{method_signature}").map(call => (call.lineNumber.get, call.code)).toJson'

    stdout, _ = session.run_joern_query(query)
    if not stdout:
        return []
    
    try:
        # Extract JSON string from Joern output
        lines = stdout.strip().split('\n')
        json_str = None
        for line in lines:
            # Strip ANSI color codes
            line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            # Look for the JSON output line
            if 'val res' in line_clean and 'String = ' in line_clean:
                # Extract the JSON string from the output
                json_start = line_clean.find('String = ') + 8
                json_str = line_clean[json_start:].strip()
                # Remove any extra quotes at the beginning and end
                # Handle both single and double quotes
                while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                    json_str = json_str[1:-1]
                break
            # Also try pattern 2: lines that start with "[" (JSON array)
            elif line_clean.strip().startswith('[') and line_clean.strip().endswith(']'):
                json_str = line_clean.strip()
                break
        
        if not json_str:
            return []
        
        # Parse the JSON (handles unescaped quotes in code strings)
        data = parse_joern_json_with_unescaped_quotes(json_str)
        if data is None:
            print(f"[ERROR] Could not parse the following JSON string in get_function_callers: {json_str}")
            return []
        
        # If data is still a string, try parsing it again
        if isinstance(data, str):
            data = json.loads(data)
        
        callers = []
        if isinstance(data, list):
            for caller in data:
                if isinstance(caller, dict) and '_1' in caller and '_2' in caller:
                    # Joern serializes tuples as objects with _1, _2 keys
                    # Format: {"_1": lineNumber, "_2": code}
                    line_number = caller['_1']
                    code = caller['_2']
                    if line_number:
                        callers.append((line_number, code if code else ""))
        
        return callers
    except Exception as e:
        print(f"[ERROR] get_function_callers hit an exception: {e}")
        return []