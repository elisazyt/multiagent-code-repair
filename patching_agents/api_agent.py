from patching_agent import PatchingAgent
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
# Add the api_db directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'api_db'))
import isolate_bug as ib
import retrieval_utils as utils
from api_db_retrieval import retrieve_existing_apis, analyze_bug_for_apis, query_api_db
from typing import Tuple, List

class ApiAgent(PatchingAgent):

    def get_agent_role(self) -> str:
        return "api"


    def format_context(self) -> str:
        """Format context with API database information"""
        bug_locations = self.information.get_info("bug files and locations")
        result = ''
        node_number = 1
        bug_number = 1  # Track bug number sequentially across all nodes

        # Reset stored node locations (will be populated during formatting)
        self.information.info_dict["unique node locations per file"] = []

        # Iterate through each file
        # Structure: (file_path, modified_source_name, bug_locations_list)
        for buggy_file_info in bug_locations:
            java_file_path, modified_source_name, bug_locations_list = buggy_file_info
            with open(java_file_path, 'rb') as f:
                code = f.read()
            bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)

            # Group bugs by unique buggy node (same logic as format_bugs_grouped_by_node)
            # Note: We duplicate this logic because we need to insert API info per node
            unique_nodes = {}
            for bug_in_file in bugs_in_file:
                bug_location, bug_code, buggy_node_info = bug_in_file
                if buggy_node_info is None:
                    continue
                buggy_node_location, buggy_node = buggy_node_info
                if buggy_node_location not in unique_nodes:
                    unique_nodes[buggy_node_location] = []
                unique_nodes[buggy_node_location].append(bug_in_file)
            
            # Store unique node locations in InfoDict (same as format_bugs_grouped_by_node)
            unique_node_locations = sorted(unique_nodes.keys())
            self.information.info_dict["unique node locations per file"].append(unique_node_locations)
            
            # Get existing APIs once per file (not per node - they're the same for all nodes in the file)
            existing_apis = retrieve_existing_apis(java_file_path)
            
            # Format each unique node with API info added per node
            for buggy_node_location in sorted(unique_nodes.keys()):
                bugs_in_node = unique_nodes[buggy_node_location]
                first_bug = bugs_in_node[0]
                bug_location, bug_code, buggy_node_info = first_bug
                buggy_node_location, buggy_node = buggy_node_info
                buggy_node_text = utils.get_node_text(buggy_node, code)
                
                # Show the buggy node first (same format as format_bugs_grouped_by_node)
                result += f'{"="*60}\n'
                result += f'Buggy Node #{node_number}:\n'
                result += f'{"="*60}\n'
                result += f'File path: {java_file_path}\n'
                result += f'Buggy node line number(s): {buggy_node_location}\n'
                result += f'\nBuggy node:\n{buggy_node_text}\n'
                
                # Then show all bug locations within this node
                result += f'\nBug locations within this node:\n'
                if len(bugs_in_node) > 1:
                    result += f'Note: This node contains {len(bugs_in_node)} bug locations. Provide ONE patch for the entire node.\n\n'
                
                # Number bugs sequentially across all nodes
                for bug_loc, bug_code, _ in bugs_in_node:
                    result += f'Bug #{bug_number}:\n'
                    result += f'  Bug line number(s): {bug_loc}\n'
                    result += f'  Bug lines: {bug_code}\n'
                    bug_number += 1
                
                # Add API database information for this node
                bug_context = f"""
                Bug location: {buggy_node_location}
                Buggy node: {buggy_node_text}
                File: {java_file_path}
                """
                result += self.format_api_database_retrieval(java_file_path, bug_context, self.gpt_client, existing_apis)
                
                node_number += 1
                result += '\n'
        return result
    

    def format_api_database_retrieval(self, java_file_path: str, bug_context: str, gpt_client, existing_apis: list = None) -> str:
        """Format API database retrieval information for a specific bug
        
        Args:
            java_file_path: Path to the Java file
            bug_context: Context about the buggy node
            gpt_client: GPT client for API analysis
            existing_apis: Optional pre-computed list of existing APIs (to avoid recomputation)
        """
        
        # Step 1: Get existing APIs from the file (only if not provided)
        if existing_apis is None:
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
        result += f"In addition, the following categories of APIs has been identified as potentially useful for repairing the bug: {additional_categories}\n"
        result += f"Here are the APIs in those categories: {candidate_apis}\n"
        result += f"Here is the reasoning for why these APIs may be useful: {reasoning}\n"
        
        return result
    