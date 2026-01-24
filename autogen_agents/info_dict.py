from typing import List, Tuple
import sys
import os

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import tree_sitter_java
from tree_sitter import Language, Parser, Query

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

#TODO: split info into multiple dicts for different purposes
class InfoDict:
    def __init__(self):
        self.info_dict = {}

    def add_bug_info(self, project_name: str, bug_id: str, bug_locations: List[Tuple[str, List[Tuple[int, int]]]], working_directory: str):
        self.add_info("project name", project_name)
        self.add_info("bug id", bug_id)
        # Add the working directory where the user wants to running the Defects4J test.
        # This is where the entire Defects4J project is checked out, tests are run, etc.
        self.add_info("working directory", working_directory)

        # Enrich bug_locations with modified_source_name
        # New structure: List[Tuple[str, str, List[Tuple[int, int]]]]
        #                 (file_path, modified_source_name, bug_locations_list)
        enriched_bug_locations = []
        for java_file_path, bug_locations_list in bug_locations:
            modified_source_name = self.get_modified_source(java_file_path)
            if modified_source_name:
                enriched_bug_locations.append((java_file_path, modified_source_name, bug_locations_list))
            else:
                # Fallback: use filename if extraction fails
                filename = os.path.basename(java_file_path).replace('.java', '')
                enriched_bug_locations.append((java_file_path, filename, bug_locations_list))
        
        self.add_info("bug files and locations", enriched_bug_locations)
    
    def add_joern_config(self, joern_executable: str, joern_directory: str):
        """
        Add Joern configuration to InfoDict.
        
        Args:
            joern_executable: Path to Joern executable
            joern_directory: Path to Joern directory (contains workspace subdirectory)
        """
        self.add_info("joern executable", joern_executable)
        self.add_info("joern directory", joern_directory)

    def add_info(self, info_type, info):
        self.info_dict[info_type] = info

    def get_info(self, info_type):
        return self.info_dict[info_type]

    def get_modified_source(self, java_file_path: str) -> str:
        """
        Extract the modified source name (package.class_name) from a Java file.
        
        Returns the Defects4J-style modified source name, e.g., 'com.google.javascript.jscomp.TypeCheck'
        
        Args:
            java_file_path: Path to the Java file
            
        Returns:
            str: The modified source name, or None if extraction fails
        """
        try:
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


class ContextDict:
    def __init__(self, info_dict: InfoDict = None):
        self.context_dict = {}
        # Initialize persistent context storage if it doesn't exist
        if "retrieved context" not in self.context_dict:
            self.context_dict["retrieved context"] = []  # List of round summaries
        if "available context functions" not in self.context_dict:
            # Dict mapping file_path -> list of available functions for that file
            self.context_dict["available context functions"] = {}
        
        # Default list of all available functions (used when initializing for a new file)
        # Must match the functions listed in cr_functions.py
        self._default_functions = [
            "comment_retrieval",
            "similar_lines_of_code",
            "similar_function_name",
            "all_funcs_in_class",
            "all_variables_in_class",
            "one_hop_api_retrieval",
            "get_callers",
            "get_callees",
            "test_failure_check"
        ]

        self.initialize_from_info_dict(info_dict)
    
    def initialize_from_info_dict(self, info_dict: InfoDict = None):
        """Initialize available functions dict with file paths from InfoDict.
        
        Args:
            info_dict: InfoDict containing bug file information.
        """
        
        bug_files_and_locations = info_dict.get_info("bug files and locations")
        
        # Ensure the dict exists in context_dict
        if "available context functions" not in self.context_dict:
            self.context_dict["available context functions"] = {}
        
        available_functions = self.context_dict["available context functions"]
        
        # Initialize each file with default functions
        for file_path, _, _ in bug_files_and_locations:
            if file_path not in available_functions:
                available_functions[file_path] = self._default_functions.copy()

    def get_retrieved_context(self) -> list[str]:
        """Get the list of round summaries"""
        return self.context_dict.get("retrieved context", [])
    
    def add_retrieved_context_round(self, round_summary: str):
        """Add a round summary to the retrieved context list (formatted summary string from SummaryAgent)"""
        if "retrieved context" not in self.context_dict:
            self.context_dict["retrieved context"] = []
        self.context_dict["retrieved context"].append(round_summary)
    
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
            available[file_path] = self._default_functions.copy()
        if function_name in available[file_path]:
            available[file_path].remove(function_name)
    