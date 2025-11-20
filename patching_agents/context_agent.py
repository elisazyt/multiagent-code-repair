from patching_agent import PatchingAgent
from typing import Tuple
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from joern_callgraph import JoernSession
from info_dict import InfoDict

class ContextAgent(PatchingAgent):

    def __init__(self, information: InfoDict, agent_role: str, agent_task: str):
        """
        Initialize ContextAgent following the same pattern as other agents.
        
        Args:
            information: InfoDict containing project info, bug locations, etc.
            agent_role: Role of the agent (e.g., "context")
            agent_task: Task description for the agent
        """
        # Initialize parent class (same as ApiAgent and BasicAgent)
        super().__init__(information, agent_role, agent_task)
        
        # Initialize CPG setup (ContextAgent-specific)
        self._initialize_cpg()
    
    def _initialize_cpg(self):
        """Initialize Joern CPG for the project if it doesn't already exist."""
        # Get project name and bug ID from InfoDict (e.g., "Chart", "Lang")
        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        
        # Combine project name and bug ID for CPG name (e.g., "Chart15", "Lang12")
        self.project_name = f"{project_name}{bug_id}"
        
        # Get Joern configuration from InfoDict
        joern_executable = self.information.get_info("joern executable")
        joern_directory = self.information.get_info("joern directory")
        
        # Get Java file paths from bug locations
        bug_locations = self.information.get_info("bug files and locations")
        
        # Get the first Java file path (we'll create CPG from this specific file)
        first_file_path = bug_locations[0][0]  # (file_path, modified_source_name, bug_locations_list)
        
        # Use the specific Java file path, not the directory
        # This ensures we only create CPG from the Java file, not all files in the directory
        java_file_path = first_file_path
        
        # Create JoernSession for the first file (we'll use same session for all files)
        self.joern_session = JoernSession(first_file_path, joern_executable, joern_directory)
        
        # Check if CPG already exists, if not create it
        cpg_path = f"{joern_directory}/workspace/{self.project_name}/cpg.bin"
        if not os.path.exists(cpg_path):
            print(f"Creating CPG for project '{self.project_name}' from file '{java_file_path}'...")
            success = self.joern_session.create_cpg(java_file_path, self.project_name)
            if not success:
                raise RuntimeError(f"Failed to create CPG for project '{self.project_name}'")
            # Verify CPG was created
            if not os.path.exists(cpg_path):
                raise RuntimeError(f"CPG file was not created at expected path: {cpg_path}")
            print(f"CPG created successfully at {cpg_path}")
        
        # Load the CPG (set project_name on the session)
        if not self.joern_session.load_cpg(self.project_name):
            raise RuntimeError(f"Failed to load CPG for project '{self.project_name}'")
    
            
    def format_context(self) -> str:
        """Format context with comments and call graph information"""
        bug_locations = self.information.get_info("bug files and locations")
        result = ''
        bug_number = 1

        # Iterate through each file
        # Structure: (file_path, modified_source_name, bug_locations_list)
        for buggy_file_info in bug_locations:
            java_file_path, modified_source_name, bug_locations_list = buggy_file_info
            with open(java_file_path, 'rb') as f:
                code = f.read()
            bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)

            # Iterate through each bug in the file
            for bug_in_file in bugs_in_file:
                # Use the common bug formatting from AbstractAgent
                result += self.format_basic_bug_info(bug_in_file, bug_number, java_file_path, code)
                
                # Extract bug info for context analysis
                bug_location, bug_code, buggy_node_info = bug_in_file
                buggy_node_location, buggy_node = buggy_node_info
                
                # Context retrieval specific additions
                # Note: buggy_node is a Node object here, not a string
                comments_before_node = utils.get_comments_before_node(java_file_path, buggy_node)
                if comments_before_node:
                    comments_text = utils.get_node_text(comments_before_node, code)
                else:
                    comments_text = "No comments found"
                result += f'Comments before buggy node: {comments_text}\n'
                result += self.format_callgraph_info(java_file_path, bug_location)
                result += self.format_ddg_info(java_file_path, bug_location)
                
                bug_number += 1
                result += '\n'
        return result
    
    def format_callgraph_info(self, java_file_path: str, bug_location: Tuple[int, int]) -> str:
        """Format call graph information for the bug location"""
        # CPG is already loaded during initialization
        result = ''
        result += f'Caller(s) of function:\n'
        callers = self.joern_session.get_function_callers(bug_location)
        for caller in callers:
            line_number, content = caller
            result += f'    - Line {line_number}: {content}\n'

        result += f'Callee(s) of function:\n'
        callees = self.joern_session.get_callees_in_line_range(bug_location)
        for callee in callees:
            method_name, line_number, content = callee
            result += f'    - "{method_name}" method called at line {line_number}: {content}\n'
        
        return result
    
    def format_ddg_info(self, java_file_path: str, bug_location: Tuple[int, int]) -> str:
        """Format data dependency graph information"""
        # TODO: Implement DDG analysis
        return ""
    
    def get_agent_role(self) -> str:
        """Return the agent role"""
        return self.agent_role