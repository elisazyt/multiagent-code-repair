from . import test_suites_helpers as tsh
import os
import subprocess
import sys

# Add parent directory to path for absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import context_retrieval.retrieval_utils as cr

# Java 11 environment is handled in test_suites_helpers._get_java11_env()

def run_defects4j_test(project_name: str, version: str, working_dir: str, java_patch_files: dict[str, str]) -> list:
    '''
    Run the test suite for a given project and version.
    
    Parameters:
    - project_name: Project name (e.g., 'Chart', 'Closure', 'Math')
    - version: Bug version (e.g., '2', '3', '4')
    - working_dir: Absolute path to the project directory
    - java_patch_files: Dict containing entries in the form of {modified source name: path to java patch file}
    '''
    if not tsh.checkout_defects4j_project(project_name, version, working_dir):
        return [{'error': 'Failed to checkout project'}]
    
    results = []

    modified_sources = tsh.get_modified_sources(project_name, version)
    for modified_source in modified_sources:
        full_source_path = tsh.get_full_source_path(project_name, working_dir, modified_source)
        
        try:
            if modified_source not in java_patch_files:
                return [{'error': f'Missing mapping for modified source: {modified_source}'}]
            if not tsh.apply_java_file_patch(java_patch_files[modified_source], full_source_path):
                return [{'error': 'Failed to apply Java file patch'}]
            # Run the test command with Java 11
            result = subprocess.run(
                ['defects4j', 'test', '-w', working_dir],
                capture_output=True,
                text=True,
                cwd=working_dir,
                env=tsh._get_java11_env()
            )
            # Debug: confirm the test command execution and surface key info
            try:
                print(f"[DEBUG] Ran: defects4j test -w {working_dir}")
                print(f"[DEBUG] Return code: {result.returncode}")
                if result.stderr:
                    print("[DEBUG] stderr (first 300 chars):")
                    print(result.stderr[:300])
                if result.stdout:
                    # print only a small slice to avoid flooding the console
                    print("[DEBUG] stdout (first 300 chars):")
                    print(result.stdout[:300])
            except Exception:
                pass
            
        
            # Parse the output to extract test results
            output = result.stdout
            return_code = result.returncode
            
            # Parse failing test names
            failing_tests = []
            lines = output.split('\n')

            for line in lines:
                if line.strip().startswith('- '):
                    # Remove the "  - " prefix and get the test name
                    test_name = line.strip()[2:].strip()
                    failing_tests.append(test_name)

            results.append({
            'success': return_code == 0,
            'failing_tests': failing_tests
            })
        
        except Exception as e:
            print(f"Error occurred: {e}")
            return [{'error': str(e)}]

    return results


# Call this function if success code is 0
def get_failing_test_info(working_dir: str, project_name: str, failing_tests: list[str]) -> list[dict[str]]:
    """
    Extract detailed information about failing tests.

    Return:
    list of failing tests, each containing: a dict of strings identifying the exception name, entire buggy
    function, and the exact failing line
    """
    all_info = []

    # get failing_tests_info
    failing_tests_path = os.path.join(working_dir, 'failing_tests')
    failing_tests_info = subprocess.run(['cat', failing_tests_path], capture_output=True, text=True).stdout
    info_for_each_test = tsh.get_each_failing_test_info(failing_tests, failing_tests_info)

    for test_identifier in failing_tests:
        test_info = info_for_each_test.get(test_identifier)
        failure_message = tsh.get_failure_message(test_info)

        buggy_method = "not found"
        buggy_line = "not found"

        package_path, method_name, line_number = tsh.get_failing_test_method_and_line(test_identifier, test_info)
        if (line_number != -1):
            test_path = tsh.get_full_test_path(project_name, working_dir, package_path)

            with open(test_path, 'rb') as f:
                code = f.read()
            
            method_node = cr.retrieve_method_by_name(test_path, method_name)
            if method_node:
                buggy_method = cr.get_node_text(method_node, code)
                # Mark the failing line in the full method with line numbers
                buggy_method_with_marker = cr.mark_failing_line_in_method(buggy_method, line_number, method_node.start_point[0] + 1)
                buggy_line = cr.retrieve_code_by_line_number(test_path, (line_number, line_number))
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
        all_info.append(test_info)

    
    test_info_string = ""
    for test_info in all_info:
        test_info_string += f"Failing test identifier: {test_info['failing test']}\n"
        test_info_string += f"Failure message: {test_info['failure message']}\n"
        test_info_string += f"Failing method: {test_info['buggy method']}\n"
        test_info_string += f"Failure line: {test_info['buggy line']}\n"
    return test_info_string