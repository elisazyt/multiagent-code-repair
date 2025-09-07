from abstract_agent import AbstractAgent
from typing import Tuple
import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from joern_callgraph import JoernSession

class ContextAgent(AbstractAgent):
    
    def get_prompt(self) -> str:
        return self.format_context()
    
    def get_agent_role(self) -> str:
        return "context retrieval"
    
    def format_context(self) -> str:
        """Format context with comments and call graph information"""
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
                
                # Extract bug info for context analysis
                bug_location, bug_code, buggy_node_info = bug_in_file
                buggy_node_location, buggy_node = buggy_node_info
                buggy_node = utils.get_node_text(buggy_node, code)
                
                # Context retrieval specific additions
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
        joern_executable = os.getenv('JOERN_EXECUTABLE', '/usr/local/bin/joern')
        joern_directory = os.getenv('JOERN_DIRECTORY', '/usr/local/share/joern')
        
        session = JoernSession(java_file_path, joern_executable, joern_directory)
        
        # Load CPG
        if not session.load_cpg("test_program"):
            return "Error: Could not load CPG\n"
        
        result = ''
        result += f'Caller(s) of function:\n'
        callers = session.get_function_callers(bug_location)
        for caller in callers:
            line_number, content = caller
            result += f'    - Line {line_number}: {content}\n'

        result += f'Callee(s) of function:\n'
        callees = session.get_callees_in_line_range(bug_location)
        for callee in callees:
            method_name, line_number, content = callee
            result += f'    - "{method_name}" method called at line {line_number}: {content}\n'
        
        return result
    
    def format_ddg_info(self, java_file_path: str, bug_location: Tuple[int, int]) -> str:
        """Format data dependency graph information"""
        # TODO: Implement DDG analysis
        return ""