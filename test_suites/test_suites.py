import os
import subprocess
import sys

# Add parent directory to path for absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add test_suites directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import test_suites_helpers as tsh
try:
    import context_retrieval.retrieval_utils as cr
except ImportError:
    # For testing, make this optional
    cr = None

# Java 11 environment is handled in test_suites_helpers._get_java11_env()

def run_defects4j_test(project_name: str, version: str, checkout_dir: str, java_patch_files: dict[str, str]) -> dict:
    '''
    Run the test suite for a given project and version.
    
    Parameters:
    - project_name: Project name (e.g., 'Chart', 'Closure', 'Math')
    - version: Bug version (e.g., '2', '3', '4')
    - checkout_dir: Base directory where Defects4J checkouts are stored
    - java_patch_files: Dict containing entries in the form of {modified source name: path to java patch file}

    Returns:
    - dict containing:
        - 'success': bool indicating if test command ran successfully (return_code == 0)
        - 'failing_tests': list of failing test names
        - 'error': str (only present if an error occurred)
    '''
    # Checkout project
    success = tsh.checkout_defects4j_project(project_name, version, checkout_dir)
    if not success:
        # Try resetting once as a last resort (in case checkout is corrupted)
        print(f"Initial checkout failed. Attempting reset and retry...")
        reset_success = tsh.reset_checkout(project_name, version, checkout_dir)
        if not reset_success:
            return {'error': 'Failed to reset checkout'}
        # Try checkout again after reset
        success = tsh.checkout_defects4j_project(project_name, version, checkout_dir)
        if not success:
            return {'error': 'Failed to checkout project even after reset'}
    
    working_dir = os.path.join(checkout_dir, f"{project_name.lower()}{version}")
    
    # Apply all patches first
    modified_sources = tsh.get_modified_sources(project_name, version)
    for modified_source in modified_sources:
        full_source_path = tsh.get_full_source_path(project_name, working_dir, modified_source)
        
        if modified_source not in java_patch_files:
            return {'error': f'Missing mapping for modified source: {modified_source}'}
        if not tsh.apply_java_file_patch(java_patch_files[modified_source], full_source_path):
            return {'error': 'Failed to apply Java file patch'}
    
    # Run the test command once after all patches are applied
    result = subprocess.run(
        ['defects4j', 'test', '-w', working_dir],
        capture_output=True,
        text=True,
        cwd=working_dir,
        env=tsh._get_java11_env()
    )
    # Debug: confirm the test command execution and surface key info
    print(f"[DEBUG] Ran: defects4j test -w {working_dir}")
    print(f"[DEBUG] Return code: {result.returncode}")
    if result.stderr:
        print("[DEBUG] stderr (first 300 chars):")
        print(result.stderr[:300])
    if result.stdout:
        # print only a small slice to avoid flooding the console
        print("[DEBUG] stdout (first 300 chars):")
        print(result.stdout[:300])
    
    # Parse the output to extract test results
    output = result.stdout
    return_code = result.returncode
    
    # If test command failed (return_code != 0), it likely means a compile error
    # Reset the checkout so it's clean for the next attempt
    if return_code != 0:
        print(f"Test command failed (return code {return_code}). This likely indicates a compile error from the patch.")
        print(f"Resetting checkout to clean state...")
        reset_success = tsh.reset_checkout(project_name, version, checkout_dir)
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
    
    # Check if the failing_tests file exists
    if not os.path.exists(failing_tests_path):
        print(f"[DEBUG] Warning: failing_tests file does not exist at {failing_tests_path}")
        print(f"[DEBUG] This may happen if Defects4J didn't write the file (e.g., compile errors, or no detailed failure info)")
        # Return empty info for all tests
        info_for_each_test = {test_id: "" for test_id in failing_tests}
    else:
        failing_tests_info = subprocess.run(['cat', failing_tests_path], capture_output=True, text=True).stdout
        if not failing_tests_info:
            print(f"[DEBUG] Warning: failing_tests file exists but is empty")
            info_for_each_test = {test_id: "" for test_id in failing_tests}
        else:
            info_for_each_test = tsh.get_each_failing_test_info(failing_tests, failing_tests_info)

    for test_identifier in failing_tests:
        test_info = info_for_each_test.get(test_identifier)
        
        # Debug: Check if test_info is empty
        if not test_info:
            print(f"[DEBUG] Test info is empty for: {test_identifier}")
            print(f"[DEBUG] This means the test identifier was not found in the failing_tests file")
        
        failure_message = tsh.get_failure_message(test_info)

        buggy_method = "not found"
        buggy_method_with_marker = "not found"
        buggy_line = "not found"

        package_path, method_name, line_number = tsh.get_failing_test_method_and_line(test_identifier, test_info)
        
        # Debug: Check extraction results
        if line_number == -1:
            print(f"[DEBUG] Line number extraction failed for: {test_identifier}")
            print(f"[DEBUG]   Package path: {package_path}")
            print(f"[DEBUG]   Method name: {method_name}")
            print(f"[DEBUG]   Test info length: {len(test_info) if test_info else 0}")
            if test_info:
                # Check if stack trace is in test_info
                test_id_with_dots = test_identifier.replace('::', '.')
                if f"at {test_id_with_dots}" in test_info:
                    print(f"[DEBUG]   Stack trace line IS in test_info")
                else:
                    print(f"[DEBUG]   Stack trace line NOT in test_info")
                    print(f"[DEBUG]   Looking for: 'at {test_id_with_dots}'")
                    # Show first 200 chars of test_info
                    print(f"[DEBUG]   Test info preview: {test_info[:200]}")
        
        if (line_number != -1):
            test_path = tsh.get_full_test_path(project_name, working_dir, package_path)

            with open(test_path, 'rb') as f:
                code = f.read()
            
            if cr is None:
                buggy_method = "context_retrieval module not available"
                buggy_method_with_marker = "context_retrieval module not available"
                buggy_line = "context_retrieval module not available"
            else:
                method_node = cr.retrieve_method_by_name(test_path, method_name)
                if method_node:
                    print(f"[DEBUG] Successfully found method '{method_name}' in {test_path}")
                    buggy_method = cr.get_node_text(method_node, code)
                    # Mark the failing line in the full method with line numbers
                    buggy_method_with_marker = cr.mark_failing_line_in_method(buggy_method, line_number, method_node.start_point[0] + 1)
                    buggy_line = cr.retrieve_code_by_line_number(test_path, (line_number, line_number))
                else:
                    print(f"[DEBUG] Method '{method_name}' NOT found in {test_path}")
                    print(f"[DEBUG]   File exists: {os.path.exists(test_path)}")
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