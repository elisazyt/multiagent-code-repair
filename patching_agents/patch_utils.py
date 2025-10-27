import os
import shutil

def extract_markdown_blocks(agent_response) -> list[str]:
    '''
    Extract the markdown blocks from the agent response. Each element in the list corresponds to
    the bug fix for one location.
    '''
    pass

def replace_buggy_node(java_file_path, buggy_node_location, fixed_code) -> str:
    """
    Delete the old code at the line range and insert the new code.
    
    Args:
        java_file_path: Path to the original Java file
        buggy_node_location: Tuple of (start_line, end_line) in 1-based indexing (from retrieve_buggy_node)
        fixed_code: The fixed code to insert
    
    Returns:
        The modified Java file content
    """
    # Read the file
    with open(java_file_path, 'r', encoding='utf-8') as f:
        java_file = f.read()
    
    lines = java_file.split('\n')
    
    # Extract start line and get the first line of the buggy node for indentation reference
    start_line, end_line = buggy_node_location
    first_buggy_line = lines[start_line - 1]  # Convert to 0-based
    
    # Fix indentation to match the original code
    adjusted_fixed_code = fix_indentation(first_buggy_line, fixed_code)
    
    # Convert to 0-based indexing for Python list slicing
    start_idx = start_line - 1  # Convert to 0-based
    end_idx = end_line  # end_line is inclusive in 1-based, but exclusive in Python slicing
    
    # Get the parts before and after the bug
    before = '\n'.join(lines[:start_idx])
    after = '\n'.join(lines[end_idx:])
    
    # Insert the fixed code between before and after
    result = before + '\n' + adjusted_fixed_code + '\n' + after
    
    return result

def apply_all_patches(java_file_path, buggy_node_locations, fixed_code_blocks) -> str:
    """
    Apply all patches to a Java file, working from the end to avoid line number shifts.
    
    Args:
        java_file_path: Path to the original Java file
        buggy_node_locations: List of (start_line, end_line) tuples for each bug (1-based, inclusive)
        fixed_code_blocks: List of fixed code strings (one per bug)
    
    Returns:
        The patched Java file content
    """
    if len(buggy_node_locations) != len(fixed_code_blocks):
        raise ValueError("The number of buggy node locations and fixed code blocks must be the same")

    # Create a copy in the patches folder
    patches_dir = os.path.join(os.path.dirname(os.path.dirname(java_file_path)), 'patches')
    os.makedirs(patches_dir, exist_ok=True)
    
    # Get the filename and create patched version
    original_filename = os.path.basename(java_file_path)
    patched_filename = original_filename.replace('.java', '_patched.java')
    patched_file_path = os.path.join(patches_dir, patched_filename)
    
    # Copy the original file to the patches folder
    shutil.copy2(java_file_path, patched_file_path)
    
    num_patches = len(buggy_node_locations)
    
    # Apply patches in reverse order (from highest line numbers to lowest)
    for i in range(num_patches - 1, -1, -1):
        # Get patched content
        patched_content = replace_buggy_node(patched_file_path, buggy_node_locations[i], fixed_code_blocks[i])
        
        # Write it back to the file
        with open(patched_file_path, 'w', encoding='utf-8') as f:
            f.write(patched_content)
    
    return patched_content


def fix_indentation(first_buggy_line, fixed_code) -> str:
    """
    Fix the indentation of fixed code to match the indentation of the first line of the original buggy code.
    
    Args:
        first_buggy_line: The first line of the original buggy code (string)
        fixed_code: The fixed code string to adjust
    
    Returns:
        The fixed code with adjusted indentation
    """
    # Split fixed code into lines
    fixed_lines = fixed_code.split('\n')
    
    if not fixed_lines:
        return fixed_code  # No change if empty
    
    # Get leading whitespace from first line of original and fixed code
    first_line_fixed = fixed_lines[0]
    
    indent_original = len(first_buggy_line) - len(first_buggy_line.lstrip())
    indent_fixed = len(first_line_fixed) - len(first_line_fixed.lstrip())
    
    # Calculate the adjustment needed
    indent_adjustment = indent_original - indent_fixed
    
    # Apply adjustment to all lines in fixed_code
    adjusted_lines = []
    for line in fixed_lines:
        if line.strip():  # Non-empty line
            # Get the relative indentation of this line in the fixed code
            current_indent = len(line) - len(line.lstrip())
            # Apply the adjustment to match the original indentation level
            adjusted_line = ' ' * (indent_adjustment + current_indent) + line.lstrip()
        else:  # Empty line - keep as is
            adjusted_line = line
        adjusted_lines.append(adjusted_line)
    
    return '\n'.join(adjusted_lines)