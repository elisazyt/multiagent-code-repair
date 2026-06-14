"""
BugDict stores general bug-related info, 
"""

from typing import List, Tuple
import os

from agents.data_structures import bugdict_helpers as helpers
import tools.defects4j_utils as d4j_utils


class BugDict:
    """
    Dictionary storing the following info:

    During initialization:
    - Project name (e.g., 'Chart')
    - Bug ID (e.g., '2')
    - Working directory (path to the directory where the Defects4J project is checked out for running test suites)
    - Bug files, bug locations, modified source name
    - Paths to Joern executable and directory (for context retrieval)

    During runtime, when creating the prompt:
    - Unique node locations per file (list of lists of tuples)
    """
    def __init__(self):
        self.info_dict = {}

    def add_project_info(self, project_name: str, bug_id: str):
        """
        Store project name and bug id
        """
        self.add_info("project name", project_name)
        self.add_info("bug id", bug_id)

    def add_bug_locations(
        self,
        bug_locations: List[Tuple[str, List[Tuple[int, int]]]],
    ):
        """
        - Bug locations are a list of tuples, each containing a file path (relative to the source folder)
        and a list of line numbers. Line numbers are tuples of (start, end) line numbers.
        - We store the complete path to each bug location, the modified source name, and the list of line numbers.
        """
        # Get the full path to the buggy file
        updated_bug_locations = []
        for relative_path, bug_locations_list in bug_locations:
            absolute_path = helpers.get_buggy_file_path(
                self.get_info("defects4j reference checkout path"),
                self.get_info("project name"),
                relative_path,
            )
            updated_bug_locations.append((absolute_path, bug_locations_list))

        # Enrich bug_locations with modified_source_name
        # New structure: List[Tuple[str, str, List[Tuple[int, int]]]]
        #                 (absolute_file_path, modified_source_name, bug_locations_list)
        enriched_bug_locations = []
        for java_file_path, bug_locations_list in updated_bug_locations:
            modified_source_name = helpers.get_modified_source(java_file_path)
            if modified_source_name:
                enriched_bug_locations.append((java_file_path, modified_source_name, bug_locations_list))
            else:
                # Fallback: use filename if extraction fails
                filename = os.path.basename(java_file_path).replace('.java', '')
                enriched_bug_locations.append((java_file_path, filename, bug_locations_list))

        self.add_info("bug files and locations", enriched_bug_locations)

    def add_paths(
        self,
        results_path: str,
        bm25_path: str,
        joern_executable: str,
        joern_working_dir: str,
        joern_workspace_path: str,
        defects4j_checkout_path: str,
    ):
        """
        results_path: path to folder containing chat_context, candidate_patches, final_patch, generated_patches
        bm25_path: path to folder containing bm25 index and corresponding jsonl file
        joern_executable: path to Joern executable (e.g., /opt/homebrew/bin/joern)
        joern_working_dir: path to folder where Joern is installed and runs from
        joern_workspace_path: path to folder containing Joern workspace for CPG generation/storage
        defects4j_checkout_path: path to folder where Defects4J projects are checked out, tests are run, etc.

        Also creates the reference checkout directory and runs defects4j checkout into it.
        Requires add_project_info to have been called first.
        """
        # Get project label for per-project folders
        label = f"{self.get_info('project name')}{self.get_info('bug id')}"

        results_path = os.path.abspath(results_path)
        self.add_info("results path", results_path)
        # results_path points to a folder which contains the following inner folders
        for subdir in ("chat_context", "candidate_patches", "final_patch", "generated_patches"):
            os.makedirs(os.path.join(results_path, subdir), exist_ok=True)
        # generated patches directory stores every agent's patch attempt
        self.add_info("generated patches path", os.path.join(results_path, "generated_patches", label))
        # don't add label for final patch directory because we store single files with labels, not folders
        self.add_info("final patch path", os.path.join(results_path, "final_patch"))

        chat_context_path = os.path.join(results_path, "chat_context", label)
        os.makedirs(chat_context_path, exist_ok=True)
        self.add_info("chat context path", chat_context_path)

        candidate_patches_path = os.path.join(results_path, "candidate_patches", label)
        os.makedirs(candidate_patches_path, exist_ok=True)
        self.add_info("candidate patches path", candidate_patches_path)

        bm25_project_path = os.path.join(os.path.abspath(bm25_path), label)
        os.makedirs(bm25_project_path, exist_ok=True)
        self.add_info("bm25 path", bm25_project_path)

        self.add_info("joern executable", joern_executable)
        self.add_info("joern working dir", os.path.abspath(joern_working_dir))

        # Create checkout folder for the given bug project + ID, the reference and per-agent checkouts are stored here
        defects4j_checkout_root = os.path.join(os.path.abspath(defects4j_checkout_path), label)
        os.makedirs(defects4j_checkout_root, exist_ok=True)
        self.add_info("defects4j checkout root", defects4j_checkout_root)

        # Create reference checkout folder under the checkout root (never modified)
        reference_checkout_dir = os.path.join(defects4j_checkout_root, "reference_checkout")
        os.makedirs(reference_checkout_dir, exist_ok=True)
        self.add_info("defects4j reference checkout path", reference_checkout_dir)
        # Perform the checkout
        project_name = self.get_info("project name")
        bug_id = self.get_info("bug id")
        if not d4j_utils.checkout_defects4j_project(project_name, bug_id, reference_checkout_dir):
            raise RuntimeError(f"Failed to checkout reference at {reference_checkout_dir}")

        joern_project_workspace_dir = os.path.join(os.path.abspath(joern_workspace_path), label)
        os.makedirs(joern_project_workspace_dir, exist_ok=True)
        self.add_info("joern workspace path", joern_project_workspace_dir)

    def add_info(self, info_type, info):
        self.info_dict[info_type] = info

    def get_info(self, info_type):
        return self.info_dict[info_type]


class ContextDict:
    """
    Dictionary containing the following info:

    During initialization:
    - BM25 configs: k (how many signatures to retrieve), path to directory for creating BM25 index and jsonl file
    - UniXcoder configs: k (how many code snippets to retrieve), window size, batch size

    During runtime:
    - Retrieved context (list of summaries, one for each retrieval attempt)
    - Available context functions (for each file, a list of context retrieval functions available to call)
    - Test info (list of failing-test dicts for BM25)
    """
    def __init__(self, bug_dict: BugDict = None):
        self.context_dict = {
            "retrieved context": [], # List of retrieval summaries, one per patching attempt
            "available context functions": {}, # Dict mapping file_path to available functions for that file
            "test info": [], # Failing test info for the latest patching attempt, populated by run_patch_test_loop
        }
        
        # Default list of all available functions (used when initializing for a new file)
        # Must match the functions listed in cr_functions.py
        # Note: similar_lines_of_code and similar_function_name are only available from attempt 2 onwards
        self.default_functions = [
            "comment_retrieval",
            "all_funcs_in_class",
            "one_hop_api_retrieval",
            "get_callers",
        ]

        '''
        UPDATED LIST:
        - comment retrieval
        - top k code snippets (in class)
        - get callers
        - top k callable functions (one-hop APIs, 2-hop APIs, within class)
        '''
        
        # Functions unlocked at the start of context retrieval attempt 2+ (require failing test info)
        self.attempt2_functions = [
            "similar_lines_of_code",
            "similar_function_name"
        ]

        self.initialize_from_bug_dict(bug_dict)
    
    def initialize_from_bug_dict(self, bug_dict: BugDict = None):
        """Initialize available functions dict with file paths from BugDict.
        
        Args:
            bug_dict: BugDict containing bug file information.
        """
        
        bug_files_and_locations = bug_dict.get_info("bug files and locations")
        
        # Ensure the dict exists in context_dict
        if "available context functions" not in self.context_dict:
            self.context_dict["available context functions"] = {}
        
        available_functions = self.context_dict["available context functions"]
        
        # Initialize each file with default functions
        for file_path, _, _ in bug_files_and_locations:
            if file_path not in available_functions:
                available_functions[file_path] = self.default_functions.copy()

    def get_retrieved_context(self) -> list[str]:
        """Get the list of round summaries"""
        return self.context_dict.get("retrieved context", [])
    
    def add_retrieved_context_attempt(self, attempt_summary: str):
        """
        Add a summary of a context retrieval attempt (NUM_PATCHING_ROUNDS rounds per attempt)
        to the retrieved context list (formatted summary string from SummaryAgent)
        """
        if "retrieved context" not in self.context_dict:
            self.context_dict["retrieved context"] = []
        self.context_dict["retrieved context"].append(attempt_summary)
    
    def get_available_functions(self) -> dict[str, list[str]]:
        """Get dict mapping file_path -> list of available context retrieval functions for all files.
        
        Returns:
            Dict mapping file_path -> list of available function names.
        """
        available = self.context_dict.get("available context functions", {})
        return available.copy() if available else {}
    
    def remove_function(self, function_name: str, file_path: str):
        """Remove a function from available list for a specific file (after it's been used)"""
        available = self.context_dict.get("available context functions", {})
        if file_path not in available:
            available[file_path] = self.default_functions.copy()
        if function_name in available[file_path]:
            available[file_path].remove(function_name)
    
    def add_attempt2_functions(self):
        """
        Add attempt 2 functions to all files.
        These functions are more computationally expensive, so we don't make them available until
        after the first attempt of patching has failed.
        """
        available = self.context_dict.get("available context functions", {})
        for file_path in available.keys():
            for func in self.attempt2_functions:
                if func not in available[file_path]:
                    available[file_path].append(func)
    
    def get_info(self, info_type):
        return self.context_dict[info_type]
    
    def add_info(self, info_type, info):
        self.context_dict[info_type] = info
    
    def add_bm25_rag_config(self, k_signatures: int, jsonl_dir, index_dir, k_code_snippets: int, window_size: int, batch_size: int):
        """Add BM25 RAG configuration to ContextDict"""
        # BM25 configs
        self.context_dict["k (signatures)"] = k_signatures
        self.context_dict["bm25 rag jsonl directory"] = jsonl_dir
        self.context_dict["bm25 rag index directory"] = index_dir
        # UniXcoder configs
        self.context_dict["k (code snippets)"] = k_code_snippets
        self.context_dict["window size"] = window_size 
        self.context_dict["batch size"] = batch_size