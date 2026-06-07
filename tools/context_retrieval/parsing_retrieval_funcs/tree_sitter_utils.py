"""
Functions for retrieving, parsing, and extracting info from tree-sitter nodes
"""

import tree_sitter_java
from tree_sitter import Language, Parser, Node
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


########################################################################################
# FUNCTIONS FOR RETRIEVING BUG LOCATIONS AND NODES
########################################################################################

def retrieve_buggy_lines_and_node(java_file_path: str, bug_locations: List[Tuple[int, int]]) -> List[Tuple[Tuple[int, int], str, Tuple[Tuple[int, int], Node]]]:
    """
    Retrieve the buggy lines of code and the node that contains the buggy lines of code.
    Returns: a list of tuples, one per bug location, each containing:
    - bug location (start, end)
    - buggy lines of code
    - buggy node location (start, end)
    - buggy Node object
    """
    result = []
    for bug_location in bug_locations:
        buggy_lines = retrieve_code_by_line_number(java_file_path, bug_location)
        buggy_node = retrieve_buggy_node(java_file_path, bug_location)
        result.append((bug_location, buggy_lines, buggy_node))
    return result

# TODO: further narrow down what's provided in retrieve_buggy_class. no need to provide all method bodies
def retrieve_buggy_node(java_file_path: str, bug_location: Tuple[int, int]) -> Tuple[Tuple[int, int], Node]:
    """
    Retrieve the node that contains the buggy lines of code (either method, constructor, class, or None)
    
    Args: path to buggy code file, and a single bug location
    Returns: ((start of node, end of node), buggy Node object)
    """
    try:
        # Most common case: try to retrieve buggy method or constructor
        buggy_method_node = retrieve_buggy_method_or_constructor(java_file_path, bug_location)
        if buggy_method_node:
            # Convert back to 1-based line numbers for return
            node_start_line = buggy_method_node.start_point[0] + 1
            node_end_line = buggy_method_node.end_point[0] + 1
            return ((node_start_line, node_end_line), buggy_method_node)
        
        # If not in a method or constructor, the bug is most likely related to class declaration
        buggy_class_node = retrieve_buggy_class(java_file_path, bug_location)
        if buggy_class_node:
            # Convert back to 1-based line numbers for return
            node_start_line = buggy_class_node.start_point[0] + 1
            node_end_line = buggy_class_node.end_point[0] + 1
            return ((node_start_line, node_end_line), buggy_class_node)
        # TODO: figure out how to exclude irrelevant context
        
        # If not in class, it's most likely related to API importation, global variables, etc. Return None
        return None

    except FileNotFoundError:
        print(f"Error: File {java_file_path} not found")
        return None
    except Exception as e:
        print(f"Error reading file {java_file_path}: {e}")
        return None


########################################################################################
# FUNCTIONS FOR PROCESSING METHODS AND CONSTRUCTORS
########################################################################################

def retrieve_buggy_method_or_constructor(java_file_path: str, bug_location: Tuple[int, int]) -> Node:
    """
    HELPER FOR retrieve_buggy_node
    Retrieve the method declaration node that contains the buggy lines of code.
    Assumes the start and end line both fall within the range of a method_declaration node.
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        tree = parser.parse(code)
        
        start_line, end_line = bug_location
        # Convert from 1-based to 0-based line numbers for tree-sitter
        start_line = start_line - 1
        end_line = end_line - 1
        
        # Find all method/constructor declarations by traversing the tree
        def find_methods_and_constructors(node):
            results = []
            if node.type in ('method_declaration', 'constructor_declaration'):
                results.append(node)
            for child in node.children:
                results.extend(find_methods_and_constructors(child))
            return results
        
        all_methods = find_methods_and_constructors(tree.root_node)
        
        # Check each method/constructor to see if it contains the bug location
        for node in all_methods:
                node_start_line = node.start_point[0]  # Line number where method/constructor starts
                node_end_line = node.end_point[0]      # Line number where method/constructor ends
                
                # Check if bug location falls within this method/constructor's range
                if node_start_line <= start_line and end_line <= node_end_line:
                    return node
        
        return None
        
    except FileNotFoundError:
        print(f"Error: File {java_file_path} not found")
        return None
    except Exception as e:
        print(f"Error reading file {java_file_path}: {e}")
        return None


def retrieve_method_node_by_name(java_file_path: str, method_name: str) -> Node:
    """
    Helper for get_failing_test_info
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
        
        def find_method(node):
            if node.type == 'method_declaration':
                for child in node.children:
                    if child.type == 'identifier':
                        if get_node_text(child, code) == method_name:
                            return node
                        break

            for child in node.children:
                result = find_method(child)
                if result:
                    return result
            return None

        return find_method(tree.root_node)
        
    except Exception as e:
        print(f"Error retrieving method by name: {e}")
        return None


########################################################################################
# FUNCTIONS FOR PROCESSING CLASSES
########################################################################################

def retrieve_buggy_class(java_file_path: str, bug_location: Tuple[int, int]) -> Node:
    """
    Helper for retrieve_buggy_node
    Retrieve the outermost class declaration node that contains the buggy lines of code.
    If the bug is in a nested class, returns the outer class (needed for Joern queries).
    Assumes the start and end line both fall within the range of a class_declaration node.
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        tree = parser.parse(code)
        
        start_line, end_line = bug_location
        # Convert from 1-based to 0-based line numbers for tree-sitter
        start_line = start_line - 1
        end_line = end_line - 1
        
        # Find all class declarations by traversing the tree
        def find_classes(node):
            results = []
            if node.type == 'class_declaration':
                results.append(node)
            for child in node.children:
                results.extend(find_classes(child))
            return results
        
        all_classes = find_classes(tree.root_node)
        
        # Collect all classes that contain the bug location
        matching_classes = []
        for class_node in all_classes:
                class_start = class_node.start_point[0]  # Line number where class starts
                class_end = class_node.end_point[0]      # Line number where class ends
                
                # Check if bug location falls within this class's range
                if class_start <= start_line and end_line <= class_end:
                    # Store class node with its line range size
                    class_range_size = class_end - class_start
                    matching_classes.append((class_node, class_range_size))
        
        # Return the outermost class (largest line range)
        if matching_classes:
            # Sort by range size (largest first) and return the outermost
            outermost_class = max(matching_classes, key=lambda x: x[1])
            return outermost_class[0]  # Return the node, not the tuple
        
        return None
        
    except FileNotFoundError:
        print(f"Error: File {java_file_path} not found")
        return None
    except Exception as e:
        print(f"Error reading file {java_file_path}: {e}")
        return None


def extract_class_name_from_file(java_file_path: str, line_numbers: Tuple[int, int]) -> str:
    """
    Used for the context retrieval function calls, as some functionsrequest class name as an argument
    Given a line number range (i.e., a bug location), retrieve the class where the bug is located
    Assumes the bug is inside a class (standard Java).
    
    Args:
        java_file_path: Path to the Java file
        line_numbers: Tuple of (start_line, end_line) where the code is located
        
    Returns:
        Class name (e.g., "CategoryPlot")
        
    Raises:
        ValueError: If class name cannot be extracted
    """
    bug_location = line_numbers
    class_node = retrieve_buggy_class(java_file_path, bug_location)
    if not class_node:
        raise ValueError(f"Could not find class node for {java_file_path} at lines {line_numbers}")
    
    class_name = extract_class_name_from_node(class_node, java_file_path)
    if not class_name:
        raise ValueError(f"Could not extract class name from class node in {java_file_path} at lines {line_numbers}")
    
    return class_name


def extract_class_name_from_node(class_node: Node, java_file_path: str) -> str:
    """
    Helper for extract_class_name_from_file.
    Extracts the class name from a given class_declaration node.

    Args:
        class_node: Tree-sitter class_declaration node
        java_file_path: Path to the Java file (needed to read code)

    Returns:
        str: The class name, or None if extraction fails
    """
    try:
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        # Find the identifier child which is the class name
        # In class_declaration, the structure is typically: modifiers? class identifier type_parameters? superclass? interfaces? body
        for child in class_node.children:
            if child.type == 'identifier':
                return get_node_text(child, code)
        
        return None
        
    except Exception as e:
        print(f"Error extracting class name: {e}")
        return None