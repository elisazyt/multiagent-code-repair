import sys
import os
from typing import List

# Add the context_retrieval directory to the path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
context_retrieval_path = os.path.join(parent_dir, 'context_retrieval')
if context_retrieval_path not in sys.path:
    sys.path.append(context_retrieval_path)
import isolate_bug as ib
import retrieval_utils as utils
from joern_session import JoernSession

# Add parent directory to path to access bm25_rag
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
import bm25_rag.bm25_within_file as bm25_wf
from bm25_rag.unixcoder_rag import embed_code_snippets, embed_bug_location, get_top_k_code_snippets
from info_dict import InfoDict, ContextDict


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

def top_k_class_signatures(java_file_path: str, start_line: int, end_line: int, class_name: str, info_dict: InfoDict, context_dict: ContextDict) -> str:
    """
    Retrieve all methods in the class containing the bug location.
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        class_name: Class name
        info_dict: InfoDict containing bug info, Joern config, BM25 directories
        context_dict: ContextDict containing BM25/UniXcoder configs
    
    Returns:
        Tuple of (list of full signatures, formatted results string)
    """
    try:
        bug_location = (start_line, end_line)
        
        # Get k from ContextDict
        k = context_dict.get_info("k (signatures)")
        
        # Get Joern configuration from InfoDict
        joern_executable = info_dict.get_info("joern executable")
        joern_directory = info_dict.get_info("joern directory")
        project_name = info_dict.get_info("project name")
        bug_id = info_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)

        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get all function signatures in the buggy class
        full_signatures = joern_session.get_full_signatures_in_buggy_class(java_file_path, bug_location)
        signatures_code = []
        code_to_full_signature = {}  # Reverse mapping: code -> full_signature
        full_signature_to_code = joern_session.get_code_from_full_signatures_batch(full_signatures)
        for signature in full_signatures:
            signature_code = full_signature_to_code[signature]
            if not signature_code:
                print(f"WARNING: Could not find method code for signature {signature}, using full signature instead")
                signatures_code.append(signature)
                code_to_full_signature[signature] = signature  # Map to itself
            else:
                signatures_code.append(signature_code)
                code_to_full_signature[signature_code] = signature  # Map code to full signature
        
        # TODO: figure out fallback
        if not signatures_code:
            print("WARNING: No signatures found in class. Returning empty list.")
            return []
        
        # TODO: figure out how to get test info
        test_info = ""

        bug_location = (start_line, end_line)
        buggy_sig = joern_session.get_full_method_signature_from_line_numbers(java_file_path, bug_location, class_name)
        if not buggy_sig:
            print(f"WARNING: Could not find method signature at bug location {bug_location}")
            return []
        buggy_sig_code_dict = joern_session.get_code_from_full_signatures_batch([buggy_sig])
        buggy_sig_code = buggy_sig_code_dict.get(buggy_sig)
        if not buggy_sig_code:
            print(f"WARNING: Could not find method code at bug location {bug_location}")
            buggy_sig_code = buggy_sig
        
        index_path = bm25_wf.make_index(signatures_code, info_dict, context_dict)

        # Request k+1 results in case the buggy signature is in the top k
        results = bm25_wf.search(k + 1, test_info, buggy_sig_code, index_path, class_name=class_name)
        
        # Remove the buggy signature itself from results (it will always be the top match)
        filtered_results = [sig for sig in results if sig != buggy_sig_code]
        # Take only the top k after filtering
        filtered_results = filtered_results[:k]
        
        filtered_results_full_sig = []
        for result in filtered_results:
            filtered_results_full_sig.append(code_to_full_signature[result])
        
        # Format top k results as numbered list (1 = highest score, k = lowest score)
        # Results are already ordered by BM25 score (highest first) from Pyserini
        formatted_results = []
        for i, signature in enumerate(filtered_results, 1):
            formatted_results.append(f"{i}. {signature}")
        
        formatted_results_str = "\n".join(formatted_results)
        
        print("\nFormatted results (ranked by BM25 score, buggy signature excluded):")
        print(formatted_results_str)
        # TODO: potentially return a tuple of (formatted_results, formatted_results_str)
        # We may need the list version for top_k_code_snippets
        return (filtered_results_full_sig, formatted_results_str)
    except Exception as e:
        error_msg = f"ERROR: Failed to retrieve top k class signatures: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return error_msg

def top_k_code_snippets(java_file_path: str, start_line: int, end_line: int, class_name: str, info_dict: InfoDict, context_dict: ContextDict) -> str:
    """
    Retrieve top k code snippets using two-stage retrieval:
    1. BM25 to get top k signatures
    2. UniXcoder embeddings to get top k code snippets from those signatures
    
    Args:
        java_file_path: Path to the Java file
        start_line: Start line of the bug location (1-indexed)
        end_line: End line of the bug location (1-indexed)
        class_name: Class name
        info_dict: InfoDict containing bug info, Joern config, BM25 directories
        context_dict: ContextDict containing BM25/UniXcoder configs
    
    Returns:
        List of top k code snippets (as strings)
    """
    try:
        # Get configs from ContextDict
        k = context_dict.get_info("k (code snippets)")
        window_size = context_dict.get_info("window size")
        batch_size = context_dict.get_info("batch size")
        
        # Stage 1: BM25 to get top k signatures
        result = top_k_class_signatures(java_file_path, start_line, end_line, class_name, info_dict, context_dict)
        if isinstance(result, str):
            # Error case - result is an error string
            return result
        top_k_signatures, _ = result
        
        # Get Joern configuration from InfoDict
        joern_executable = info_dict.get_info("joern executable")
        joern_directory = info_dict.get_info("joern directory")
        project_name = info_dict.get_info("project name")
        bug_id = info_dict.get_info("bug id")
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Initialize JoernSession
        joern_session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        if not joern_session.load_cpg(cpg_project_name):
            return f"ERROR: Could not load CPG for project '{cpg_project_name}'. Make sure CPG is created first."
        
        # Get method bodies from signatures
        method_bodies = joern_session.get_method_bodies_from_signatures_batch(java_file_path, top_k_signatures)
        method_embeddings, method_line_ranges = embed_code_snippets(method_bodies, window_size, batch_size)
        query_embedding = embed_bug_location(java_file_path, (start_line, end_line))

        top_k_code_snippets = get_top_k_code_snippets(k, query_embedding, method_embeddings, java_file_path, method_line_ranges)
        return top_k_code_snippets
    except Exception as e:
        return f"ERROR: Failed to retrieve top k code snippets: {str(e)}"

def one_hop_api_retrieval(java_file_path: str, start_line: int, end_line: int, variable_name: str, information: ContextDict) -> str:
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
    