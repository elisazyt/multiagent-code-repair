from typing import List, Tuple
from message_history import MessageHistory
import sys
import os

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import tree_sitter_java
from tree_sitter import Language, Parser, Query

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

class InfoDict:
    def __init__(self):
        self.info_dict = {}

    def add_message_history(self, message_history: MessageHistory):
        self.add_info("message history", message_history)

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

    def add_info(self, info_type, info):
        self.info_dict[info_type] = info

    def get_info(self, info_type):
        return self.info_dict[info_type]
    
    def get_message_history(self):
        return self.info_dict["message history"]

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
            
            # Extract package name
            package_name = None
            package_query = Query(JAVA_LANGUAGE, "(package_declaration) @package_decl")
            package_matches = package_query.matches(tree.root_node)
            for match in package_matches:
                pattern_id, captures_dict = match
                if 'package_decl' in captures_dict:
                    package_node = captures_dict['package_decl'][0]
                    package_text = code[package_node.start_byte:package_node.end_byte].decode('utf8')
                    # Remove 'package' keyword and ';' and whitespace
                    package_name = package_text.replace('package', '').replace(';', '').strip()
                    break
            
            # Extract class name
            class_name = None
            class_query = Query(JAVA_LANGUAGE, "(class_declaration name: (identifier) @class_name)")
            class_matches = class_query.matches(tree.root_node)
            for match in class_matches:
                pattern_id, captures_dict = match
                if 'class_name' in captures_dict:
                    class_node = captures_dict['class_name'][0]
                    class_name = code[class_node.start_byte:class_node.end_byte].decode('utf8')
                    break
            
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