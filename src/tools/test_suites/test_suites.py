import os
import subprocess
from typing import List, Dict, Tuple

from src.tools.test_suites import test_suites_helpers as tsh
import defects4j_utils as d4j_utils
from src.tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils as utils


def run_defects4j_test(
    project_name: str,
    bug_id: str,
    agent_checkout_dir: str,
    java_patch_files: dict[str, str],
    reference_dir: str,
) -> dict:
    '''
    Run the test suite for a given project and bug ID.
    
    Parameters:
    - project_name: Project name (e.g., 'Chart', 'Closure', 'Math')
    - bug_id: Bug ID (e.g., '2', '3', '4')
    - agent_checkout_dir: Defects4J project root for this specific agent (e.g. .../Closure3/basic)
    - java_patch_files: Dict containing entries in the form of {modified source name: path to java patch file}
    - reference_dir: Unchanged checkout directory to copy from (e.g. .../Closure3/reference_checkout)

    Returns:
    - dict containing:
        - 'success': bool indicating if test command ran successfully (return_code == 0)
        - 'failing_tests': list of failing test names
        - 'error': str (only present if an error occurred)
    '''
    if not tsh.reset_checkout(reference_dir, agent_checkout_dir):
        return {'error': 'Failed to reset agent checkout'}

    # Apply all patches first
    modified_sources = d4j_utils.get_modified_sources(project_name, bug_id)
    for modified_source in modified_sources:
        full_source_path = tsh.get_full_source_path(project_name, agent_checkout_dir, modified_source)
        
        if modified_source not in java_patch_files:
            return {'error': f'Missing mapping for modified source: {modified_source}'}
        if not tsh.apply_java_file_patch(java_patch_files[modified_source], full_source_path):
            return {'error': 'Failed to apply Java file patch'}
    
    # Run the test command once after all patches are applied
    result = subprocess.run(
        ['defects4j', 'test', '-w', agent_checkout_dir],
        capture_output=True,
        text=True,
        cwd=agent_checkout_dir,
        env=d4j_utils.get_java11_env()
    )
    
    # Parse the output to extract test results
    output = result.stdout
    return_code = result.returncode
    
    # If test command failed (return_code != 0), it likely means a compile error
    # Reset the checkout so it's clean for the next attempt
    if return_code != 0:
        print(f"[ERROR] run_defects4j_test: Test command failed (return code {return_code}). This likely indicates a compile error from the patch.")
        reset_success = tsh.reset_checkout(reference_dir, agent_checkout_dir)
        if not reset_success:
            return {'error': 'Failed to reset checkout after compile error'}
    
    # Parse failing test names
    failing_tests = []
    lines = output.split('\n')

    for line in lines:
        if line.strip().startswith('- '):
            # Remove the "  - " prefix and get the test name
            test_name = line.strip()[2:].strip()
            failing_tests.append(test_name)

    return {
        'success': return_code == 0,
        'failing_tests': failing_tests
    }


def get_failing_test_info(working_dir: str, project_name: str, failing_tests: List[str]) -> Tuple[str, List[Dict[str, str]]]:
    """
    Extract detailed information about failing tests.

    Return:
    Tuple of (test_info_string, test_info_list):
    - test_info_string: Formatted string with all test failure information
    - test_info_list: List of dicts, each containing: failing test identifier, failure message, buggy method, and failure line
    """
    test_info_list = []

    # get failing_tests_info
    failing_tests_path = os.path.join(working_dir, 'failing_tests')
    
    # Check if the failing_tests file exists
    if not os.path.exists(failing_tests_path):
        # Return empty info for all tests
        info_for_each_test = {test_id: "" for test_id in failing_tests}
    else:
        failing_tests_info = subprocess.run(['cat', failing_tests_path], capture_output=True, text=True).stdout
        if not failing_tests_info:
            info_for_each_test = {test_id: "" for test_id in failing_tests}
        else:
            info_for_each_test = tsh.get_each_failing_test_info(failing_tests, failing_tests_info)

    for test_identifier in failing_tests:
        test_info = info_for_each_test.get(test_identifier)
        
        failure_message = tsh.get_failure_message(test_info)

        buggy_method = "not found"
        buggy_method_with_marker = "not found"
        buggy_line = "not found"

        package_path, method_name, line_number = tsh.get_failing_test_method_and_line(test_identifier, test_info)
        
        if (line_number != -1):
            test_path = tsh.get_full_test_path(project_name, working_dir, package_path)

            with open(test_path, 'rb') as f:
                code = f.read()
            
            method_node = utils.retrieve_method_node_by_name(test_path, method_name)
            if method_node:
                buggy_method = utils.get_node_text(method_node, code)
                buggy_method_with_marker = tsh.mark_failing_line_in_method(
                    buggy_method, line_number, method_node.start_point[0] + 1
                )
                buggy_line = utils.retrieve_code_by_line_number(test_path, (line_number, line_number))
            else:
                buggy_method = "not found"
                buggy_method_with_marker = "not found"
                buggy_line = "not found"

        test_info = {
            'failing test': test_identifier,
            'failure message': failure_message,
            'buggy method': buggy_method_with_marker,  # Use the marked version with line numbers
            'buggy line': buggy_line
        }
        test_info_list.append(test_info)
    
    test_info_string = ""
    for test_info in test_info_list:
        test_info_string += f"Failing test identifier: {test_info['failing test']}\n"
        test_info_string += f"Failure message: {test_info['failure message']}\n"
        test_info_string += f"Failing method: {test_info['buggy method']}\n"
        test_info_string += f"Failure line: {test_info['buggy line']}\n"
    # test_info_string is for the agent output, test_info_list is for bm25/rag which is formatted differently
    return (test_info_string, test_info_list)