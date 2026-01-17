import os
import shutil
import sys

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as utils

def extract_markdown_blocks(agent_response) -> list[str]:
    '''
    Extract the markdown blocks from the agent response. Each element in the list corresponds to
    the bug fix for one location.
    
    Args:
        agent_response: The full response from the agent (string)
    
    Returns:
        List of code blocks extracted from markdown (```java ... ```)
    '''
    code_blocks = []
    
    # Split by markdown code block markers
    parts = agent_response.split('```java')
    
    # Skip the first part (everything before the first code block)
    for part in parts[1:]:
        # Find the closing ```
        code_block_end = part.find('```')
        if code_block_end != -1:
            # Extract the code block content
            code_block = part[:code_block_end].strip()
            code_blocks.append(code_block)
    
    return code_blocks


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


def apply_all_patches(bug_files_and_locations, agent_response, agent_role, unique_node_locations_per_file) -> dict[str, str]:
    """
    Apply all patches to multiple Java files.
    
    Args:
        bug_files_and_locations: List of tuples (java_file_path, modified_source_name, List of bug locations)
        agent_response: The agent's response containing markdown code blocks
        agent_role: The role of the agent (e.g., 'basic', 'api', 'context')
        unique_node_locations_per_file: List[List[Tuple[int, int]]] - pre-computed unique node locations per file
                                        Each inner list contains sorted (start_line, end_line) tuples for that file
    
    Returns:
        dict[str, str]: Mapping from modified_source_name to patch_file_path
                       e.g., {'org.jfree.chart.plot.PiePlot': '/path/to/PiePlot_patched_basic.java'}
    """
    fixed_code_blocks = extract_markdown_blocks(agent_response)

    if not bug_files_and_locations or not fixed_code_blocks:
        return {}
    
    # Count unique nodes per file from the pre-computed locations
    unique_nodes_per_file = [len(locations) for locations in unique_node_locations_per_file]
    
    # Split fixed_code_blocks based on unique nodes per file
    fixed_code_blocks_per_file = []
    start_idx = 0
    for count in unique_nodes_per_file:
        end_idx = start_idx + count
        fixed_code_blocks_per_file.append(fixed_code_blocks[start_idx:end_idx])
        start_idx = end_idx
    
    # Track mapping of modified_source_name -> patch_file_path
    patch_mapping = {}
    
    # Process each file
    # Structure: (file_path, modified_source_name, bug_locations_list)
    for i, (java_file_path, modified_source_name, bug_locations_list) in enumerate(bug_files_and_locations):
        print(f"[DEBUG] Processing file: {java_file_path} for source: {modified_source_name}")
        
        # Use pre-computed node locations
        buggy_node_locations = unique_node_locations_per_file[i]
        print(f"[DEBUG] Bug locations: {bug_locations_list}")
        print(f"[DEBUG] Unique buggy node locations (start,end): {buggy_node_locations}")
        
        if not buggy_node_locations:
            continue
        
        if len(buggy_node_locations) != len(fixed_code_blocks_per_file[i]):
            raise ValueError(f"Mismatch: {len(buggy_node_locations)} unique buggy nodes but {len(fixed_code_blocks_per_file[i])} code blocks for {java_file_path}. "
                           f"Note: Multiple bug locations in the same method/class should result in only one patch for that entire node.")

        # Create a copy in the patches folder
        patches_dir = os.path.join(os.path.dirname(os.path.dirname(java_file_path)), 'patches')
        os.makedirs(patches_dir, exist_ok=True)
        
        # Get the filename and create patched version
        original_filename = os.path.basename(java_file_path)
        patched_filename = original_filename.replace('.java', f'_patched_{agent_role}.java')
        patched_file_path = os.path.join(patches_dir, patched_filename)
        
        # Copy the original file to the patches folder
        shutil.copy2(java_file_path, patched_file_path)
        
        num_patches = len(buggy_node_locations)
        
        # Apply patches in reverse order (from highest line numbers to lowest)
        for j in range(num_patches - 1, -1, -1):
            # Get patched content
            block_preview = " ".join(fixed_code_blocks_per_file[i][j].splitlines()[:2])
            print(f"[DEBUG] Applying patch index {j} to lines {buggy_node_locations[j]} with block preview: {block_preview}")
            patched_content = replace_buggy_node(patched_file_path, buggy_node_locations[j], fixed_code_blocks_per_file[i][j])
            
            # Write it back to the file
            with open(patched_file_path, 'w', encoding='utf-8') as f:
                f.write(patched_content)
        
        # Store the mapping: modified_source_name -> patch_file_path
        patch_mapping[modified_source_name] = patched_file_path
    
    return patch_mapping


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