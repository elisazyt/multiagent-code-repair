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
        
        # Manual traversal to find method_declaration nodes
        def find_method(node):
            if node.type == 'method_declaration':
                # In method_declaration, the structure is typically:
                # method_declaration -> modifiers? -> type -> identifier (method name) -> formal_parameters -> body
                # We need to find the identifier that comes after the type
                found_identifier = False
                for child in node.children:
                    if child.type == 'identifier':
                        # This should be the method name (comes after modifiers and type)
                        found_name = code[child.start_byte:child.end_byte].decode('utf8')
                if found_name == method_name:
                            return node
            
            # Recursively search children
            for child in node.children:
                result = find_method(child)
                if result:
                    return result
        
        return None
        
        return find_method(tree.root_node)
        
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
        
        target_class_node = None
        try:
            class_captures = class_query.captures(tree.root_node)
            if 'class_name' in class_captures:
                for class_name_node in class_captures['class_name']:
                    found_class_name = get_node_text(class_name_node, code)
                    if found_class_name == class_name:
                        # Get the parent class_declaration node
                        target_class_node = class_name_node.parent
                        while target_class_node and target_class_node.type != 'class_declaration':
                            target_class_node = target_class_node.parent
                        break
        except AttributeError:
            # Fall back to manual tree traversal
            def find_class_by_name(node, target_name):
                """Recursively find class_declaration node with specific name"""
                if node.type == 'class_declaration':
                    # Find the identifier child (class name)
                    for child in node.children:
                        if child.type == 'identifier':
                            found_name = get_node_text(child, code)
                            if found_name == target_name:
                                return node
                            break
                for child in node.children:
                    result = find_class_by_name(child, target_name)
                    if result:
                        return result
                return None
            target_class_node = find_class_by_name(tree.root_node, class_name)
        
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
        method_name_nodes = []
        try:
            method_captures = method_query.captures(target_class_node)
            method_name_nodes = method_captures.get('method_name', [])
        except AttributeError:
            # Fall back to manual tree traversal
            def find_method_names(node):
                """Recursively find all method_declaration nodes"""
                methods = []
                if node.type == 'method_declaration':
                    # Find the identifier child (method name)
                    for child in node.children:
                        if child.type == 'identifier':
                            methods.append(child)  # Append the identifier node
                            break
                for child in node.children:
                    methods.extend(find_method_names(child))
                return methods
            method_name_nodes = find_method_names(target_class_node)
        
        for method_name_node in method_name_nodes:
            method_name = get_node_text(method_name_node, code)
            
            # Find the method_declaration parent
            method_decl = method_name_node.parent
            while method_decl and method_decl.type != 'method_declaration':
                method_decl = method_decl.parent
            
            if not method_decl:
                continue
            
            # Extract return type from method_declaration
            return_type = "void"
            for child in method_decl.children:
                if child.type in ('type_identifier', 'scoped_type_identifier', 'generic_type', 'primitive_type', 'void_type'):
                    return_type = get_node_text(child, code)
                    break
            
            # Extract parameters
            parameters = []
            params_node = None
            for child in method_decl.children:
                if child.type == 'formal_parameters':
                    params_node = child
                    break
            
            if params_node:
                # Extract individual parameters
                param_query = Query(JAVA_LANGUAGE, """
                (formal_parameter
                    type: (_) @param_type
                    name: (identifier) @param_name)
                """)
                
                param_name_nodes = []
                try:
                    param_captures = param_query.captures(params_node)
                    param_name_nodes = param_captures.get('param_name', [])
                except AttributeError:
                    # Fall back to manual tree traversal
                    def find_param_names(node):
                        """Recursively find all formal_parameter identifier nodes"""
                        params = []
                        if node.type == 'formal_parameter':
                            # Find the identifier child (parameter name)
                            for child in node.children:
                                if child.type == 'identifier':
                                    params.append(child)
                                    break
                        for child in node.children:
                            params.extend(find_param_names(child))
                        return params
                    param_name_nodes = find_param_names(params_node)
                
                # Match param_type and param_name by finding their common parent formal_parameter
                for param_name_node in param_name_nodes:
                    param_name = get_node_text(param_name_node, code)
                    # Find the parent formal_parameter node
                    param_decl = param_name_node.parent
                    while param_decl and param_decl.type != 'formal_parameter':
                        param_decl = param_decl.parent
                    
                    if param_decl:
                        # Find the type within this formal_parameter
                        param_type = "Object"  # default
                        for child in param_decl.children:
                            if child.type in ('type_identifier', 'scoped_type_identifier', 'generic_type', 'primitive_type'):
                                param_type = get_node_text(child, code)
                                break
                        parameters.append((param_type, param_name))
            
            # Get line number (1-based)
            line_number = method_name_node.start_point[0] + 1
            
            methods.append((method_name, return_type, parameters, line_number))
        
        return methods
        
    except Exception as e:
        print(f"Error getting methods in class: {e}")
        return []