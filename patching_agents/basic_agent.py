from patching_agent import PatchingAgent
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from typing import Tuple

class BasicAgent(PatchingAgent):
    
    def get_agent_role(self) -> str:
        return "basic"
    
    def format_context(self) -> str:
        """Format basic context without additional analysis"""
        bug_locations = self.information.get_info("bug files and locations")
        result = ''
        bug_number = 1  # Track bug number sequentially across all files and nodes

        # Reset stored node locations (will be populated during formatting)
        self.information.info_dict["unique node locations per file"] = []

        # Iterate through each file
        # Structure: (file_path, modified_source_name, bug_locations_list)
        for buggy_file_info in bug_locations:
            java_file_path, modified_source_name, bug_locations_list = buggy_file_info
            with open(java_file_path, 'rb') as f:
                code = f.read()
            bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)

            # Use the helper method to format bugs grouped by unique nodes
            # Returns: (formatted_string, next_bug_number)
            formatted_bugs, next_bug_number = self.format_bugs_grouped_by_node(bugs_in_file, java_file_path, code, bug_number)
            result += formatted_bugs
            bug_number = next_bug_number  # Continue bug numbering across files
            
        return result
    
    