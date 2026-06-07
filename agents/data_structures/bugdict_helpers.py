import os

def get_buggy_file_path(
    reference_checkout_path: str,
    project_name: str,
    java_relative_path: str,
) -> str:
    """
    Given a relative Java path, return the absolute path to the buggy file
    Concatenate the defects4j checkout path, the project prefix, and the relative path
    """
    prefix = get_project_prefix(project_name)
    relative_path = java_relative_path.lstrip("/")
    return os.path.join(reference_checkout_path, prefix, relative_path)

def get_project_prefix(project_name: str) -> str:
    """
    Get the connecting prefix for a given project
    """
    prefixes = {
        "chart": "source",
        "closure": "src",
        "mockito": "src",
        "math": "src/main/java",
        "lang": "src/main/java",
        "time": "src/main/java",
    }
    return prefixes[project_name.lower()]

def get_modified_source(java_file_path: str) -> str:
    """
    Helper for add_bug_locations
    Extract the modified source name (package.class_name) from a single Java file.
    Returns the Defects4J-style modified source name, e.g., 'com.google.javascript.jscomp.TypeCheck'
    
    Args:
        java_file_path: Path to the Java file
        
    Returns:
        str: The modified source name, or None if extraction fails
    """
    try:
        import tree_sitter_java
        from tree_sitter import Language, Parser

        JAVA_LANGUAGE = Language(tree_sitter_java.language())
        parser = Parser(JAVA_LANGUAGE)

        # Use tree_sitter to parse the Java file and extract the modified source name
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        tree = parser.parse(code)
        root = tree.root_node
        
        # Extract package name by traversing the tree
        package_name = None
        def find_package(node):
            if node.type == 'package_declaration':
                # Get the scoped_identifier or identifier child
                for child in node.children:
                    if child.type in ('scoped_identifier', 'identifier'):
                        package_text = code[child.start_byte:child.end_byte].decode('utf8')
                        return package_text
            for child in node.children:
                result = find_package(child)
                if result:
                    return result
            return None
        
        package_name = find_package(root)
        
        # Extract class name by traversing the tree
        class_name = None
        def find_class(node):
            if node.type == 'class_declaration':
                # Find the identifier child which is the class name
                for child in node.children:
                    if child.type == 'identifier':
                        return code[child.start_byte:child.end_byte].decode('utf8')
            for child in node.children:
                result = find_class(child)
                if result:
                    return result
            return None
        
        class_name = find_class(root)

        # Combine package and class name
        if package_name and class_name:
            return f"{package_name}.{class_name}"
        elif class_name:
            return class_name
        else:
            return None
            
    except Exception as e:
        print(f"Error extracting modified source name from {java_file_path}: {e}")
        return None