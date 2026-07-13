import os
import shutil


def reset_checkout(reference_dir: str, agent_checkout_dir: str) -> bool:
    """
    Reset an agent checkout by copying the original reference checkout

    Parameters:
    - reference_dir (str): Unmodified Defects4J checkout (e.g. .../Closure3/reference_checkout)
    - checkout_dir (str): Agent checkout to restore (e.g. .../Closure3/basic)

    Returns:
    - bool: True if copy succeeded, False otherwise
    """
    # Delete existing checkout if it exists
    if os.path.exists(agent_checkout_dir):
        shutil.rmtree(agent_checkout_dir)
    # Replace with copy of the reference checkout
    shutil.copytree(reference_dir, agent_checkout_dir)
    return True


def apply_java_file_patch(java_file: str, target_file_path: str):
    try:
        # Copy the Java file to the target location
        shutil.copy2(java_file, target_file_path)
        return True
    except Exception as e:
        print(f"[ERROR] apply_java_file_patch hit an exception: {e}")
        return False


def get_full_source_path(project_name: str, working_dir: str, modified_source: str):
    """
    Construct the target_java_path by combining connecting path with modified source.
    
    Parameters:
    - project_name: Project name (e.g., 'Chart', 'Closure', 'Math')
    - modified_source: Modified source from Defects4J (e.g., 'org.apache.commons.math3.dfp.Dfp')
    
    Returns:
    - str: Full target_java_path relative to working_dir
    """

    # Get the connecting path for this project
    paths = {
        'chart': 'source',
        'closure': 'src',
        'mockito': 'src', 
        'math': 'src/main/java',
        'lang': 'src/main/java',
        'time': 'src/main/java'
    }

    # Combine connecting path with file path
    full_source_path = connect_paths(project_name, working_dir, paths, modified_source)
    return full_source_path


def get_each_failing_test_info(failing_tests: list[str], failing_tests_info: str) -> dict[str, str]:
    info_for_each_test = {}

    for test_identifier in failing_tests:
        # Find the start of this test's info (starts with "--- test_identifier")
        start_marker = f"--- {test_identifier}"
        start_index = failing_tests_info.find(start_marker)
        
        if start_index == -1:
            # Test info not found, add empty string
            info_for_each_test[test_identifier] = ""
            continue
        
        # Find the end of this test's info (next "---" or end of string)
        next_start = failing_tests_info.find("---", start_index + 1)
        
        if next_start == -1:
            # This is the last test, take everything to the end
            test_info = failing_tests_info[start_index:]
        else:
            # Take everything up to the next test
            test_info = failing_tests_info[start_index:next_start]
        
        info_for_each_test[test_identifier] = test_info

    return info_for_each_test


def get_failure_message(test_info: str) -> str:
    """
    Extract the failure message from the failing test info for a specific test.
    
    Args:
        test_info (str): The failing test info for a specific test
        
    Returns:
        str: The complete failure message from the second line
    """
    lines = test_info.split('\n')
    
    # Return the second line (index 1) if it exists
    if len(lines) > 1:
        return lines[1].strip()
    
    return ""  # Return empty string if not found


def get_full_test_path(project_name: str, working_dir: str, test_package_path: str) -> str:
    """
    Construct the full path to the test file
    
    Parameters:
    - project_name: Project name (e.g., 'Chart', 'Closure', 'Math')
    - working_dir: Working directory (e.g., .../Closure3/basic)
    - test_package_path: Given by the test identifier, but without the method name
    """

    # Get the connecting path for this project
    paths = {
        'chart': 'tests',
        'closure': 'test',
        'mockito': 'test', 
        'math': 'src/test/java',
        'lang': 'src/test/java',
        'time': 'src/test/java'
    }

    # Combine connecting path with file path
    full_test_path = connect_paths(project_name, working_dir, paths, test_package_path)
    return full_test_path


def get_failing_test_method_and_line(test_identifier: str, failing_test_info: str) -> tuple[str, str, int]:
    """
    Extract the method name and line number from the failing test info for a specific test.
    
    Parameters:
    - test_identifier: The specific test identifier to look for
    - failing_tests_info: String containing the failing test information
    
    Returns:
    - tuple[str, int]: (package_path, method_name, line_number)
    """
    
    # Split the test identifier to get package path and method name
    parts = test_identifier.split('::')
    if len(parts) != 2:
        return ("", "", 0)
    
    package_path = parts[0]  # org.mockito.internal.util.TimerTest
    method_name = parts[1]   # should_throw_friendly_reminder_exception_when_duration_is_negative
    
    # Convert :: to . for searching in stack trace
    test_identifier_with_dots = test_identifier.replace('::', '.')
    
    # Search for the test identifier in the "at..." lines
    lines = failing_test_info.split('\n')
    for line in lines:
        if line.strip().startswith('at ') and test_identifier_with_dots in line:
            # Extract line number from parentheses
            # Format: "at org.mockito.internal.util.TimerTest.should_throw_friendly_reminder_exception_when_duration_is_negative(TimerTest.java:42)"
            if '(' in line and ')' in line:
                file_line_part = line.split('(')[1].split(')')[0]
                if ':' in file_line_part:
                    line_number = int(file_line_part.split(':')[1])
                    return (package_path, method_name, line_number)
    
    return (package_path, method_name, -1)  # Return -1 if line number not found


def mark_failing_line_in_method(method_code: str, failing_line_number: int, method_start_line: int, window_size: int = 10) -> str:
    """
    Add line numbers to a short method excerpt and mark the failing line.
    
    Args:
        method_code: The full method code as a string
        failing_line_number: The absolute line number where failure occurred (1-based)
        method_start_line: The line number where the method starts (1-based)
        window_size: Number of lines to include before and after the failing line
    
    Returns:
        Method code with line numbers prefixed and failing line marked
    """
    lines = method_code.split('\n')
    method_relative_line = failing_line_number - method_start_line + 1  # 1-based within method

    start_index = max(method_relative_line - window_size - 1, 0)
    end_index = min(method_relative_line + window_size, len(lines))
    
    result_lines = []
    for i, line in enumerate(lines[start_index:end_index], start=start_index + 1):  # i is 1-based relative to method
        absolute_line = method_start_line + i - 1
        if i == method_relative_line:
            # Mark the failing line
            result_lines.append(f"{absolute_line:4d} >>> {line} <<< FAILED HERE")
        else:
            result_lines.append(f"{absolute_line:4d}     {line}")
    
    return '\n'.join(result_lines)


def connect_paths(project_name: str, working_dir: str, paths: dict[str, str], package_path: str):
    """
    Parameters:
    - project_name: e.g. 'Chart', 'Closure', 'Math'
    - working_dir: Working directory (e.g., .../Closure3/basic)
    - paths: dictionary specifying the connecting path for each project
    - package_path: Package path (e.g., 'org.mockito.internal.util.TimerTest')

    Returns:
    - str: Full path to the test file
    """
    connecting_path = paths.get(project_name.lower())
    file_path = package_path.replace('.', '/') + '.java'
    full_path = os.path.join(working_dir, connecting_path, file_path)
    return full_path