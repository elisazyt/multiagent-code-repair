"""
Functions called by the ContextRetrievalAgent.
These are essentially wrappers of the functions defined in context_retrieval_implementations.py
"""

import sys
import os
from typing import List, Tuple

parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from src.tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils as utils
import src.tools.context_retrieval.parsing_retrieval_funcs.context_retrieval_implementations as implementations
from src.tools.context_retrieval.parsing_retrieval_funcs.joern_session import JoernSession
import src.tools.context_retrieval.parsing_retrieval_funcs.joern_utils as joern_utils
from src.agents.data_structures.dicts import BugDict, ContextDict


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
        buggy_node_result = utils.retrieve_buggy_node(java_file_path, bug_location)
        
        if buggy_node_result is None:
            return f"ERROR: Could not find a node containing the bug location ({start_line}, {end_line}) in {java_file_path}"
        
        _, buggy_node = buggy_node_result
        
        # Read the file to get code bytes
        with open(java_file_path, 'rb') as f:
            code = f.read()
        
        # Get comments before the node
        comments_before_node = implementations.get_comments_before_node(java_file_path, buggy_node)
        
        if comments_before_node:
            comments_text = utils.get_node_text(comments_before_node, code)
            return f"Comments before bug location ({start_line}, {end_line}):\n{comments_text}"
        else:
            return f"No comments found before bug location ({start_line}, {end_line})"
            
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve comments: {str(e)}"


def all_funcs_in_class(java_file_path: str, start_line: int, end_line: int, bug_dict) -> str:
    """
    Retrieve all methods in the class containing the bug location.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        bug_dict: BugDict to get Joern config and project info
    
    Returns:
        String containing all method signatures in the class, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from BugDict
        joern_executable = bug_dict.get_info("joern executable")
        joern_working_dir = bug_dict.get_info("joern working dir")
        project_name = bug_dict.get_info("project name")
        bug_id = bug_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        joern_workspace_path = bug_dict.get_info("joern workspace path")
        
        # Initialize JoernSession
        joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        signatures = implementations.get_full_signatures_in_buggy_class(joern_session, java_file_path, bug_location)
        
        if not signatures:
            return f"No methods found in class containing bug location ({start_line}, {end_line})"
        
        # Format the results
        result = f"All methods in class containing bug location ({start_line}, {end_line}):\n"
        for i, func_signature in enumerate(signatures, 1):
            result += f"  {i}. {func_signature}\n"
        
        return result
        
    except FileNotFoundError:
        return f"ERROR: File {java_file_path} not found"
    except Exception as e:
        return f"ERROR: Failed to retrieve methods in class: {str(e)}"


def top_k_class_signatures(java_file_path: str, start_line: int, end_line: int, class_name: str, bug_dict: BugDict, context_dict: ContextDict) -> Tuple[List[str], str]:
    """
    Retrieve top k signatures in the buggy class that are most similar to the signature
    of the buggy function, using BM25.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        class_name: Class name
        bug_dict: BugDict containing bug info, Joern config, BM25 directories
        context_dict: ContextDict containing BM25/UniXcoder configs
    
    Returns:
        Tuple of (list of full signatures, formatted results string or error message)
        On error, returns ([], error_message_string)
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get k from ContextDict
        k = context_dict.get_info("k (signatures)")
        
        # Get Joern configuration from BugDict
        joern_executable = bug_dict.get_info("joern executable")
        joern_working_dir = bug_dict.get_info("joern working dir")
        project_name = bug_dict.get_info("project name")
        bug_id = bug_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        joern_workspace_path = bug_dict.get_info("joern workspace path")
        
        joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)

        if not joern_session.load_cpg(cpg_project_name):
            error_msg = f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
            return ([], error_msg)
        
        full_signatures = implementations.get_full_signatures_in_buggy_class(joern_session, java_file_path, bug_location)
        if not full_signatures:
            return ([], "WARNING: No signatures found in class.")

        test_info_list = context_dict.get_info("test info")
        if not test_info_list:
            test_info_list = [{
                'failing test': "",
                'failure message': "",
                'buggy method': "",
                'buggy line': ""
            }]

        buggy_sig = joern_utils.get_full_method_signature_from_line_numbers(joern_session, java_file_path, bug_location, class_name)
        if not buggy_sig:
            return ([], f"ERROR: Could not find method signature at bug location {bug_location}")

        from src.tools.context_retrieval.vector_retrieval import bm25_search as search

        index_path = search.make_index(full_signatures, bug_dict, context_dict)

        # Request k+1 results in case the buggy signature is in the top k
        results = search.search(k + 1, test_info_list, buggy_sig, index_path, class_name=class_name)

        filtered_results = [sig for sig in results if sig != buggy_sig][:k]
        filtered_results_full_sig = filtered_results
        
        # Format top k results as numbered list (1 = highest score, k = lowest score)
        # Results are already ordered by BM25 score (highest first) from Pyserini
        formatted_results = []
        for i, signature in enumerate(filtered_results, 1):
            formatted_results.append(f"{i}. {signature}")
        
        formatted_results_str = "\n".join(formatted_results)
        return (filtered_results_full_sig, formatted_results_str)
    except Exception as e:
        print(f"[ERROR] top_k_class_signatures hit an exception: {e}")
        return ([], f"ERROR: top_k_class_signatures failed: {e}")


def top_k_code_snippets(java_file_path: str, start_line: int, end_line: int, class_name: str, bug_dict: BugDict, context_dict: ContextDict) -> str:
    """
    Retrieve top k code snippets using two-stage retrieval:
    1. BM25 to get top k signatures
    2. UniXcoder embeddings to get top k code snippets from those signatures
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        class_name: Class name
        bug_dict: BugDict containing bug info, Joern config, BM25 directories
        context_dict: ContextDict containing BM25/UniXcoder configs
    
    Returns:
        Formatted string of top k code snippets (numbered list), or error message string
    """
    try:
        # Get configs from ContextDict
        k = context_dict.get_info("k (code snippets)")
        window_size = context_dict.get_info("window size")
        batch_size = context_dict.get_info("batch size")
        
        # Stage 1: BM25 to get top k signatures
        top_k_signatures, formatted_sigs = top_k_class_signatures(java_file_path, start_line, end_line, class_name, bug_dict, context_dict)
        
        # Check if there was an error (error message in formatted_sigs)
        if formatted_sigs.startswith("ERROR:") or formatted_sigs.startswith("WARNING:"):
            return formatted_sigs
        
        # Get Joern configuration from BugDict
        joern_executable = bug_dict.get_info("joern executable")
        joern_working_dir = bug_dict.get_info("joern working dir")
        project_name = bug_dict.get_info("project name")
        bug_id = bug_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        joern_workspace_path = bug_dict.get_info("joern workspace path")
        
        # Initialize JoernSession
        joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)
        
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get method bodies from signatures
        from src.tools.context_retrieval.vector_retrieval.unixcoder_retrieval import (
            embed_code_snippets,
            embed_bug_location,
            get_top_k_code_snippets,
        )

        method_bodies = joern_utils.get_method_bodies_from_signatures_batch(joern_session, java_file_path, top_k_signatures)
        method_embeddings, method_line_ranges = embed_code_snippets(method_bodies, window_size, batch_size)
        query_embedding = embed_bug_location(java_file_path, (start_line, end_line))

        top_k_snippets = get_top_k_code_snippets(k, query_embedding, method_embeddings, java_file_path, method_line_ranges)
        
        # Format the list of code snippets as a numbered string
        formatted_results = []
        for i, snippet in enumerate(top_k_snippets, 1):
            formatted_results.append(f"{i}. {snippet}")
        
        return "Top k similar code snippets:\n" + "\n\n".join(formatted_results)
    except Exception as e:
        return f"ERROR: Failed to retrieve top k code snippets: {str(e)}"


def one_hop_api_retrieval(java_file_path: str, start_line: int, end_line: int, variable_name: str, bug_dict: BugDict) -> str:
    """
    Retrieve 1-hop APIs callable on the specified variable.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed) where the variable is used
        end_line: End line of the bug location (1-indexed) where the variable is used
        variable_name: Name of the variable to retrieve 1-hop APIs for
        bug_dict: BugDict to get Joern config and project info
    
    Returns:
        String containing the 1-hop APIs callable on the specified variable, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from BugDict
        joern_executable = bug_dict.get_info("joern executable")
        joern_working_dir = bug_dict.get_info("joern working dir")
        project_name = bug_dict.get_info("project name")
        bug_id = bug_dict.get_info("bug id")
        reference_checkout_dir = bug_dict.get_info("defects4j reference checkout path")
        cpg_project_name = f"{project_name}{bug_id}"
        joern_workspace_path = bug_dict.get_info("joern workspace path")
        
        # Initialize JoernSession
        joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get APIs for the variable using get_apis_from_var
        # This function will first get the variable type, then retrieve APIs for that type
        apis = implementations.get_apis_from_var(joern_session, java_file_path, variable_name, bug_location, reference_checkout_dir)
        
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


def get_callers(java_file_path: str, start_line: int, end_line: int, bug_dict, class_name: str) -> str:
    """
    Retrieve callers (places where the function at bug location is called).
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        bug_dict: BugDict to get Joern config and project info
        class_name: Class name (e.g., "CategoryPlot") to filter method signature lookup
    
    Returns:
        String containing the callers, or error message
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get Joern configuration from BugDict
        joern_executable = bug_dict.get_info("joern executable")
        joern_working_dir = bug_dict.get_info("joern working dir")
        project_name = bug_dict.get_info("project name")
        bug_id = bug_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        joern_workspace_path = bug_dict.get_info("joern workspace path")
        
        # Initialize JoernSession
        joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)
        
        # Load CPG (assumes CPG already exists)
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get callers of the function at bug location
        callers = implementations.get_function_callers(joern_session, java_file_path, bug_location, class_name)
        
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