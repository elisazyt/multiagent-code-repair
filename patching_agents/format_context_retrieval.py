from typing import Tuple, List
from tree_sitter import Node

import sys
import os
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils
from joern_callgraph import JoernSession

# Get paths from environment variables
JOERN_EXECUTABLE = os.getenv('JOERN_EXECUTABLE')
JOERN_DIRECTORY = os.getenv('JOERN_DIRECTORY')
JAVA_FILE_PATH = os.getenv('JAVA_FILE_PATH')


# TODO: how much context to provide? is whole node enough, or do we provide the whole node + the program
# for reference?

 # Provide a list of tuples in the form of (file path, bug locations). The bug locations should be given
 # as a list of tuples in the form of (start line number, end line number).
def format_context(context_type: str, all_bug_locations: List[Tuple[str, List[Tuple[int, int]]]]) -> str:
    result = ''
    bug_number = 1

    # Iterate through each file
    for buggy_file_info in all_bug_locations:
        java_file_path, bug_locations_list = buggy_file_info
        with open(java_file_path, 'rb') as f:
            code = f.read()
        bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)

        # Iterate through each bug in the file
        for bug_in_file in bugs_in_file:
            bug_location, bug_code, buggy_node_info = bug_in_file
            buggy_node_location, buggy_node = buggy_node_info
            buggy_node = utils.get_node_text(buggy_node, code)
            result += f'Bug #{bug_number}:\n'
            result += f'File path: {java_file_path}\n'
            result += f'Bug line number(s): {bug_location}\n'
            result += f'Bug lines: {bug_code}'
            result += f'Buggy node line number(s): {buggy_node_location}\n'
            result += f'Buggy node: {buggy_node}\n'
            if context_type == "context retrieval":
                comments_before_node = utils.get_comments_before_node(java_file_path, buggy_node)
                if comments_before_node:
                    comments_text = utils.get_node_text(comments_before_node, code)
                else:
                    comments_text = "No comments found"
                result += format_context_retrieval(comments_text, java_file_path, bug_location)
            if context_type == "api database retrieval":
                # TODO: result += format_api_database_retrieval(buggy_node_location, buggy_node, comments_text)
                pass
            bug_number += 1
            result += '\n'
    return result

def format_context_retrieval(comments_text: str, java_file_path: str, bug_location: Tuple[int, int]) -> str:
    result = ""
    result += f'Comments before buggy node: {comments_text}\n'
    result += format_callgraph_info(java_file_path, bug_location)
    result += format_ddg_info(java_file_path, bug_location)
    return result

def format_api_database_retrieval() -> str:
    # TODO
    pass

# TODO: fix json parsing
def format_callgraph_info(java_file_path: str, bug_location: Tuple[int, int]) -> str:
    # Use provided parameters or fall back to environment variables
    joern_executable = JOERN_EXECUTABLE
    joern_directory = JOERN_DIRECTORY
    
    session = JoernSession(java_file_path, joern_executable, joern_directory)
    
    # Load CPG
    if not session.load_cpg("test_program"):
        print("Failed to load CPG")
        return "Error: Could not load CPG"

    result = ''
    result += f'Caller(s) of function:\n'
    callers = session.get_function_callers(java_file_path, bug_location)
    for caller in callers:
        line_number, content = caller
        result += f'    - Line {line_number}: {content}\n'

    result += f'Callee(s) of function:\n'
    callees = session.get_callees_in_line_range(java_file_path, bug_location)
    for callee in callees:
        method_name, line_number, content = callee
        result += f'    - "{method_name}" method called at line {line_number}: {content}\n'
    
    return result


def format_ddg_info() -> str:
    # TODO
    pass
