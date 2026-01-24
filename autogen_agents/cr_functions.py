import sys
import os

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from joern_session import JoernSession


def comment_retrieval(java_file_path: str, start_line: int, end_line: int) -> str:
    """
    Retrieve comments before the bug location.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
    
    Returns:
        String containing the comments before the bug location, or error message
    """
    try:
        # Get the buggy node from the location using tree-sitter
        bug_location = (start_line, end_line)
        buggy_node_result = ib.retrieve_buggy_node(java_file_path, bug_location)
        
        if buggy_node_result is None:
            return f"ERROR: Could not find a node containing the bug location ({start_line}, {end_line}) in {java_file_path}"
        
        buggy_node_location, buggy_node = buggy_node_result
        
        # Read the file to get code bytes
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        # Get comments before the node
        comments_before_node = utils.get_comments_before_node(java_file_path, buggy_node)
        
        if comments_before_node:
            comments_text = utils.get_node_text(comments_before_node, code)
            return f"Comments before bug location ({start_line}, {end_line}):\n{comments_text}"
        else:
            return f"No comments found before bug location ({start_line}, {end_line})"
            
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve comments: {str(e)}"


def all_funcs_in_class(java_file_path: str, start_line: int, end_line: int, information) -> str:
    """
    Retrieve all methods in the class containing the bug location.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        information: InfoDict to get Joern config and project info
    
    Returns:
        String containing all method signatures in the class, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from InfoDict
        joern_executable = information.get_info("joern executable")
        joern_directory = information.get_info("joern directory")
        project_name = information.get_info("project name")
        bug_id = information.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Initialize JoernSession
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get all functions in the buggy class
        functions = joern_session.get_functions_in_buggy_class(java_file_path, bug_location)
        
        if not functions:
            return f"No methods found in class containing bug location ({start_line}, {end_line})"
        
        # Format the results
        result = f"All methods in class containing bug location ({start_line}, {end_line}):\n"
        for i, func_signature in enumerate(functions, 1):
            result += f"  {i}. {func_signature}\n"
        
        return result
        
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve methods in class: {str(e)}"

def one_hop_api_retrieval(java_file_path: str, start_line: int, end_line: int, variable_name: str, information) -> str:
    """
    Retrieve 1-hop APIs callable on the specified variable.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed) where the variable is used
        end_line: End line of the bug location (1-indexed) where the variable is used
        variable_name: Name of the variable to retrieve 1-hop APIs for
        information: InfoDict to get Joern config and project info
    
    Returns:
        String containing the 1-hop APIs callable on the specified variable, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from InfoDict
        joern_executable = information.get_info("joern executable")
        joern_directory = information.get_info("joern directory")
        project_name = information.get_info("project name")
        bug_id = information.get_info("bug id")
        checkout_dir = information.get_info("working directory")
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Initialize JoernSession
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get APIs for the variable using get_apis_from_var
        # This function will first get the variable type, then retrieve APIs for that type
        apis = joern_session.get_apis_from_var(java_file_path, variable_name, bug_location, project_name, bug_id, checkout_dir)
        
        if not apis:
            return f"No APIs found for variable '{variable_name}' at bug location ({start_line}, {end_line}). The variable type may not be found or may not have any methods."
        
        # Format the results
        result = f"1-hop APIs for variable '{variable_name}' at bug location ({start_line}, {end_line}):\n"
        result += f"Found {len(apis)} methods:\n"
        for i, api_signature in enumerate(apis, 1):
            result += f"  {i}. {api_signature}\n"
        
        return result
        
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve 1-hop APIs: {str(e)}"


def get_callers(java_file_path: str, start_line: int, end_line: int, information, class_name: str) -> str:
    """
    Retrieve callers (places where the function at bug location is called).
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        information: InfoDict to get Joern config and project info
        class_name: Class name (e.g., "CategoryPlot") to filter method signature lookup
    
    Returns:
        String containing the callers, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from InfoDict
        joern_executable = information.get_info("joern executable")
        joern_directory = information.get_info("joern directory")
        project_name = information.get_info("project name")
        bug_id = information.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Initialize JoernSession
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get callers of the function at bug location
        callers = joern_session.get_function_callers(java_file_path, bug_location, class_name)
        
        if not callers:
            return f"No callers found for function at bug location ({start_line}, {end_line})"
        
        # Format the results - just list the content (no line numbers)
        result = f"Callers of function at bug location ({start_line}, {end_line}):\n"
        for _, content in callers:
            result += f"  - {content}\n"
        
        return result
        
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve callers: {str(e)}"


def get_callees(java_file_path: str, start_line: int, end_line: int, information, class_name: str) -> str:
    """
    Retrieve callees (method calls) at the bug location.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        information: InfoDict to get Joern config and project info
        class_name: Class name (e.g., "CategoryPlot") to filter by file name.
                   Filters results to calls in files ending with "{class_name}.java"
    
    Returns:
        String containing the callees at the bug location, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from InfoDict
        joern_executable = information.get_info("joern executable")
        joern_directory = information.get_info("joern directory")
        project_name = information.get_info("project name")
        bug_id = information.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Initialize JoernSession
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get callees at the bug location
        callees = joern_session.get_callees_in_line_range(java_file_path, bug_location, class_name)
        
        if not callees:
            return f"No callees found at bug location ({start_line}, {end_line})"
        
        # Format the results
        result = f"Callees at bug location ({start_line}, {end_line}):\n"
        for method_name, line_number, code in callees:
            result += f"  - {method_name}() called at line {line_number}: {code}\n"
        
        return result
        
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve callees: {str(e)}"
    