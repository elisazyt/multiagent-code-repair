from abstract_agent import AbstractAgent
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
# Add the api_db directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'api_db'))
import isolate_bug as ib
import retrieval_utils as utils
from api_db_retrieval import retrieve_existing_apis, analyze_bug_for_apis, query_api_db
from typing import Tuple

class ApiAgent(AbstractAgent):

    def get_agent_role(self) -> str:
        return "api"


    def format_context(self) -> str:
        """Format context with API database information"""
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
                
                # Extract bug info for API analysis
                bug_location, bug_code, buggy_node_info = bug_in_file
                buggy_node_location, buggy_node = buggy_node_info
                buggy_node = utils.get_node_text(buggy_node, code)
                
                # Create context for this specific bug
                bug_context = f"""
                Bug location: {buggy_node_location}
                Buggy node: {buggy_node}
                File: {java_file_path}
                """
                
                # API database specific additions for this specific bug
                result += self.format_api_database_retrieval(java_file_path, bug_context, self.gpt_client)
                
                bug_number += 1
                result += '\n'
        return result
    

    def format_api_database_retrieval(self, java_file_path: str, bug_context: str, gpt_client) -> str:
        """Format API database retrieval information for a specific bug"""
        
        # Step 1: Get existing APIs from the file first
        existing_apis = retrieve_existing_apis(java_file_path)
        
        # Step 2: Analyze what additional API categories are needed
        additional_categories, reasoning = analyze_bug_for_apis(bug_context, existing_apis, self.gpt_client)
        
        # Step 3: Get candidate APIs from identified categories (avoiding duplicates)
        candidate_apis = query_api_db(additional_categories, existing_apis)
        
        # Step 4: Create API context dictionary
        api_context = {
            'existing_apis': existing_apis,
            'candidate_apis': candidate_apis
        }
        
        result = f"API Analysis:\n"
        result += f"The following APIs have already been imported: {existing_apis}\n"
        result += f"In addition, the following categories of APIs has been identified as potentially useful for repairing the bug: {candidate_apis}\n"
        result += f"Here are the APIs in those categories: {candidate_apis}\n"
        result += f"Here is the reasoning for why these APIs may be useful: {reasoning}\n"
        
        return result
    