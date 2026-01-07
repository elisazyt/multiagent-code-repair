import tree_sitter_java
from tree_sitter import Language, Parser, Query, Node
from typing import List, Tuple

JAVA_LANGUAGE = Language(tree_sitter_java.language())

parser = Parser(JAVA_LANGUAGE)

# Extract text from a tree-sitter node
def get_node_text(node: Node, code: bytes) -> str:
    """
    Extract text from a tree-sitter node using the provided code bytes
    """
    return code[node.start_byte:node.end_byte].decode("utf8")


# This retrieves the buggy code for all buggy files
def retrieve_code_by_line_number(java_file_path: str, bug_location: Tuple[int, int]) -> str:
    """
    Retrieve the exact code corresponding to the buggy lines of code
    """
    try:
        with open(java_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        buggy_code = ''
        
        start_line, end_line = bug_location
        # Convert to 0-based indexing
        start_idx = start_line - 1
        end_idx = end_line
        
        # Validate line numbers
        if start_idx < 0 or end_idx > len(lines) or start_idx >= end_idx:
            print(f"Warning: Invalid line range ({start_line}, {end_line}) for file with {len(lines)} lines")
            return ""
        
        # Extract the buggy lines of code (inclusive)
        bug_lines = lines[start_idx:end_idx]
        buggy_code = ''.join(bug_lines)
        
        return buggy_code
        
    except FileNotFoundError:
        print(f"Error: File {java_file_path} not found")
        return ""
    except Exception as e:
        print(f"Error reading file {java_file_path}: {e}")
        return ""


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
                
        matches = query.matches(tree.root_node)
        
        # Check each comment node
        for match in matches:
            pattern_id, captures_dict = match
            
            # Check both block_comment and line_comment captures
            for capture_name in ['block_comment', 'line_comment']:
                if capture_name in captures_dict:
                    captured_node = captures_dict[capture_name][0]  # Get the first (and only) node
                    comment_end_point = captured_node.end_point
                    
                    # Check for comments on the same line or the line immediately before the target node
                    if (comment_end_point[0] == node_start_point[0] - 1 or  # Comment on line before
                        comment_end_point[0] == node_start_point[0]):       # Comment on same line
                        return captured_node
        
        return None
        
    except FileNotFoundError:
        print(f"Error: File {java_file_path} not found")
        return None
    except Exception as e:
        print(f"Error reading file {java_file_path}: {e}")
        return None


def get_name_from_tree_sitter_node(tree_sitter_node, java_file_path: str) -> Tuple[str, str]:
    """
    Extract method or constructor name from a tree-sitter node
    
    Args:
        tree_sitter_node: Tree-sitter node (could be method_declaration, constructor_declaration, etc.)
        java_file_path: Path to the Java file
        
    Returns: tuple of either ('method', method_name) or ('constructor', constructor_name)
        
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        # If the node is a method declaration, extract the name
        if tree_sitter_node.type == "method_declaration":
            # Find the identifier node (method name)
            for child in tree_sitter_node.children:
                if child.type == "identifier":
                    return ('method', get_node_text(child, code))
        
        # If the node is a constructor declaration
        elif tree_sitter_node.type == "constructor_declaration":
            # Find the identifier node (constructor name)
            for child in tree_sitter_node.children:
                if child.type == "identifier":
                    return ('constructor', get_node_text(child, code))
        
        return None
        
    except Exception as e:
        print(f"Error extracting method name: {e}")
        return None



# other things to consider as context: instance variables, method params, etc

# data flow: get variable in each statement, find where variable is from- use tree sitter

def retrieve_method_by_name(java_file_path: str, method_name: str) -> Node:
    """
    Retrieve a method node by its name from a Java file.
    
    Args:
        java_file_path: Path to the Java file
        method_name: Name of the method to find
        
    Returns:
        Node: The method_declaration node, or None if not found
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        tree = parser.parse(code)
        
        # Query for method declarations
        query = Query(JAVA_LANGUAGE, """
        (method_declaration
            name: (identifier) @method_name)
        """)
        
        matches = query.matches(tree.root_node)
        
        for match in matches:
            pattern_id, captures_dict = match
            if 'method_name' in captures_dict:
                method_name_node = captures_dict['method_name'][0]
                found_name = get_node_text(method_name_node, code)
                
                if found_name == method_name:
                    # Get the parent method_declaration node
                    current = method_name_node.parent
                    while current and current.type != 'method_declaration':
                        current = current.parent
                    if current:
                        return current
        
        return None
        
    except Exception as e:
        print(f"Error retrieving method by name: {e}")
        return None


def mark_failing_line_in_method(method_code: str, failing_line_number: int, method_start_line: int) -> str:
    """
    Add line numbers to method code and mark the failing line.
    
    Args:
        method_code: The full method code as a string
        failing_line_number: The absolute line number where failure occurred (1-based)
        method_start_line: The line number where the method starts (1-based)
    
    Returns:
        Method code with line numbers prefixed and failing line marked
    """
    lines = method_code.split('\n')
    method_relative_line = failing_line_number - method_start_line + 1  # 1-based within method
    
    result_lines = []
    for i, line in enumerate(lines, start=1):  # i is 1-based relative to method
        absolute_line = method_start_line + i - 1
        if i == method_relative_line:
            # Mark the failing line
            result_lines.append(f"{absolute_line:4d} >>> {line} <<< FAILED HERE")
        else:
            result_lines.append(f"{absolute_line:4d}     {line}")
    
    return '\n'.join(result_lines)


# TODO: Implement data flow analysis functions



# Get all available instance methods in the buggy class
def get_all_methods_in_class(java_file_path: str, class_name: str) -> List[Tuple[str, str, List[Tuple[str, str]], int]]:
    """
    Get all methods in a class with their full signatures.
    
    Args:
        java_file_path: Path to the Java file
        class_name: Name of the class to search for
        
    Returns:
        List of tuples: (method_name, return_type, parameters, line_number)
        where parameters is a list of (param_type, param_name) tuples
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        tree = parser.parse(code)
        
        # First, find the class by name
        class_query = Query(JAVA_LANGUAGE, """
        (class_declaration
            name: (identifier) @class_name)
        """)
        
        class_matches = class_query.matches(tree.root_node)
        target_class_node = None
        
        for match in class_matches:
            pattern_id, captures_dict = match
            if 'class_name' in captures_dict:
                found_class_name = get_node_text(captures_dict['class_name'][0], code)
                if found_class_name == class_name:
                    # Get the parent class_declaration node
                    target_class_node = captures_dict['class_name'][0].parent
                    while target_class_node and target_class_node.type != 'class_declaration':
                        target_class_node = target_class_node.parent
                    break
        
        if not target_class_node:
            return []
        
        # Now find all methods within this class (search in class body)
        methods = []
        method_query = Query(JAVA_LANGUAGE, """
        (method_declaration
            type: (_) @return_type
            name: (identifier) @method_name
            parameters: (formal_parameters) @params)
        """)
        
        # Search within the class node (recursively)
        method_matches = method_query.matches(target_class_node)
        
        for match in method_matches:
            pattern_id, captures_dict = match
            
            # Get method name
            method_name_node = captures_dict.get('method_name', [None])[0]
            if not method_name_node:
                continue
            method_name = get_node_text(method_name_node, code)
            
            # Get return type
            return_type_node = captures_dict.get('return_type', [None])[0]
            return_type = get_node_text(return_type_node, code) if return_type_node else "void"
            
            # Get parameters
            params_node = captures_dict.get('params', [None])[0]
            parameters = []
            if params_node:
                # Extract individual parameters
                param_query = Query(JAVA_LANGUAGE, """
                (formal_parameter
                    type: (_) @param_type
                    name: (identifier) @param_name)
                """)
                param_matches = param_query.matches(params_node)
                for param_match in param_matches:
                    param_pattern, param_captures = param_match
                    param_type_node = param_captures.get('param_type', [None])[0]
                    param_name_node = param_captures.get('param_name', [None])[0]
                    if param_type_node and param_name_node:
                        param_type = get_node_text(param_type_node, code)
                        param_name = get_node_text(param_name_node, code)
                        parameters.append((param_type, param_name))
            
            # Get line number (1-based)
            line_number = method_name_node.start_point[0] + 1
            
            methods.append((method_name, return_type, parameters, line_number))
        
        return methods
        
    except Exception as e:
        print(f"Error getting methods in class: {e}")
        return []