from abstract_agent import AbstractAgent
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from typing import Tuple

class BasicAgent(AbstractAgent):
    
    def get_agent_role(self) -> str:
        return "basic"
    
    def format_context(self) -> str:
        """Format basic context without additional analysis"""
        bug_locations = self.information.get_info("bug files and locations")
        result = ''
        bug_number = 1

        # Iterate through each file
        for buggy_file_info in bug_locations:
            java_file_path, bug_locations_list = buggy_file_info
            with open(java_file_path, 'rb') as f:
                code = f.read()
            bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)

            # Iterate through each bug in the file
            for bug_in_file in bugs_in_file:
                # Use the common bug formatting from AbstractAgent
                result += self.format_basic_bug_info(bug_in_file, bug_number, java_file_path, code)
                
                bug_number += 1
                result += '\n'
        return result
    
    