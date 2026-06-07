import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

from . import tree_sitter_utils as utils
from .joern_session import JoernSession

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from tools import defects4j_utils as d4j_utils


def parse_joern_json_with_unescaped_quotes(json_str: str) -> Optional[list]:
    """
    Parse JSON from Joern that may contain unescaped quotes in code strings.
    Returns the parsed data or None if parsing fails.
    """
    # Step 1: Try standard JSON parsing (most common case - valid JSON)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # Step 2: Try unescaping - Joern sometimes outputs escaped JSON strings
    try:
        json_str_unescaped = json_str.replace('\\"', '"')
        return json.loads(json_str_unescaped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 3: Extract data manually using regex when JSON is malformed
    results = []
    json_str_for_regex = json_str.replace('\\"', '"')

    for match in re.finditer(r'\{"_1":([^,]+),"_2":"', json_str_for_regex):
        value1 = match.group(1)
        code_start = match.end()

        code_end = code_start
        while code_end < len(json_str_for_regex):
            if json_str_for_regex[code_end] == '"' and code_end + 1 < len(json_str_for_regex):
                next_char = json_str_for_regex[code_end + 1]
                if next_char in [',', '}']:
                    break
            code_end += 1

        code = json_str_for_regex[code_start:code_end]

        try:
            value1 = int(value1)
        except ValueError:
            pass

        results.append({'_1': value1, '_2': code})

    for match in re.finditer(r'\{"_1":([^,]+),"_2":([^,]+),"_3":"', json_str_for_regex):
        value1 = match.group(1)
        value2 = match.group(2)
        code_start = match.end()

        code_end = code_start
        while code_end < len(json_str_for_regex):
            if json_str_for_regex[code_end] == '"' and code_end + 1 < len(json_str_for_regex):
                next_char = json_str_for_regex[code_end + 1]
                if next_char in [',', '}']:
                    break
            code_end += 1

        code = json_str_for_regex[code_start:code_end]

        try:
            value1 = int(value1)
        except ValueError:
            pass
        try:
            value2 = int(value2)
        except ValueError:
            pass

        results.append({'_1': value1, '_2': value2, '_3': code})

    return results if results else None


########################################################################################
# HELPER FUNCTIONS FOR RETRIEVING METHOD SIGNATURES AND BODIES
########################################################################################

# Example: org.jfree.data.general.DatasetUtilities.iterateDomainBounds:org.jfree.data.Range(org.jfree.data.xy.XYDataset,boolean)
def get_full_method_signature_from_line_numbers(session: JoernSession, java_file_path: str, line_numbers: Tuple[int, int], class_name: str) -> Optional[str]:
    """
    Helper for: top_k_class_signatures, get_function_callers
    Get the full method signature from a given line number range for a specific file.
    
    Args:
        java_file_path: Path to the Java file to filter by
        line_numbers: Tuple of (start_line, end_line) to search for method
        class_name: Class name (e.g., "CategoryPlot") to filter by file name.
                    Filters results to methods in files ending with "{class_name}.java"

    Returns:
        Full method signature if found, None otherwise
    """
    if not session.project_name:
        raise RuntimeError("No project loaded. Call load_cpg() first.")
    
    start_line, end_line = line_numbers
    # Find methods that contain the line range, excluding static initializers
    # Filter by class name in file path
    query = f'cpg.method.filter(m => m.lineNumber.isDefined && m.lineNumber.get <= {start_line} && m.lineNumberEnd.isDefined && m.lineNumberEnd.get >= {end_line} && m.name != "<clinit>" && m.file.name.filter(_.endsWith("{class_name}.java")).nonEmpty).map(m => (m.fullName)).toJson'
    
    stdout, _ = session._run_joern_query(query)
    if not stdout:
        return None
    
    try:
        # Extract JSON string from Joern output
        lines = stdout.strip().split('\n')
        json_str = None
        for line in lines:
            # Strip ANSI color codes
            line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            # Look for the JSON output line
            if 'val res' in line_clean and 'String = ' in line_clean:
                # Extract the JSON string from the output
                json_start = line_clean.find('String = ') + 8
                json_str = line_clean[json_start:].strip()
                # Remove any extra quotes at the beginning and end
                # Handle both single and double quotes
                while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                    json_str = json_str[1:-1]
                
                # Handle escaped quotes within the string
                json_str = json_str.replace('\\"', '"')
                break
        
        if not json_str:
            return None
        
        # Parse the JSON
        data = json.loads(json_str)
        # If data is still a string, try parsing it again
        if isinstance(data, str):
            data = json.loads(data)
        
        # Results are a list of method signatures (strings)
        # Return the first one (should only be one since we're filtering by class)
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        
        return None
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        print(f"JSON string that failed: {json_str}")
        return None
    except Exception as e:
        print(f"Error processing output: {e}")
        return None


def get_method_bodies_from_signatures_batch(session: JoernSession, java_file_path: str, full_signatures: List[str]) -> List[Tuple[str, Tuple[int, int]]]:
    """
    Helper for: top_k_code_snippets
    Get method bodies for multiple full signatures using Joern line numbers and tree-sitter.
    
    Args:
        java_file_path: Path to the Java source file
        full_signatures: List of full Joern signatures (e.g., "org.jfree.data.general.DatasetUtilities.iterateRangeBounds:org.jfree.data.Range(org.jfree.data.xy.XYDataset,boolean)")
        
    Returns:
        List of tuples (or None if not found), in the same order as input signatures.
        Each tuple is: (method_body: str, (start_line: int, end_line: int))
        - method_body: The method body code as a string
        - (start_line, end_line): Line range of the method body block in the file (1-based)
    """
    if not session.project_name:
        raise RuntimeError("No project loaded. Call load_cpg() first.")
    
    if not full_signatures:
        return []
    
    # Step 1: Get line ranges from Joern for all signatures (batch query)
    signature_list_str = ', '.join([f'"{sig}"' for sig in full_signatures])
    query = f'cpg.method.filter(m => List({signature_list_str}).contains(m.fullName)).map(m => (m.fullName, m.lineNumber.get, m.lineNumberEnd.get)).toJson'
    
    stdout, stderr = session._run_joern_query(query)
    if stderr and not any(harmless in stderr for harmless in ['sun.misc.Unsafe', 'scala.runtime.LazyVals', 'java.lang.System::load']):
        print(f"DEBUG get_method_bodies_from_signatures_batch stderr: {stderr}")
    if not stdout:
        return [("", (0, 0))] * len(full_signatures)
    
    try:
        # Parse JSON output: List[(String, Int, Int)] where:
        # - First is fullName
        # - Second is start line number
        # - Third is end line number
        lines = stdout.strip().split('\n')
        json_str = None
        for line in lines:
            line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            if 'val res' in line_clean and 'String = ' in line_clean:
                json_start = line_clean.find('String = ') + 8
                json_str = line_clean[json_start:].strip()
                while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                    json_str = json_str[1:-1]
                json_str = json_str.replace('\\"', '"')
                break
        
        if not json_str:
            return [("", (0, 0))] * len(full_signatures)
        
        # Parse JSON array
        data = json.loads(json_str)
        if isinstance(data, str):
            data = json.loads(data)
        
        # Step 2: Read file once for all methods
        try:
            with open(java_file_path, 'rb') as f:
                code = f.read()
        except Exception as e:
            print(f"Error reading file {java_file_path}: {e}")
            return [("", (0, 0))] * len(full_signatures)
        
        # Step 3: Create a mapping from signature to line range
        signature_to_range = {}
        if isinstance(data, list):
            for item in data:
                # Joern returns tuples as dictionaries with _1, _2, _3 keys
                full_signature = item.get('_1')
                start_line = item.get('_2')
                end_line = item.get('_3')
                
                if full_signature in full_signatures and start_line and end_line:
                    signature_to_range[full_signature] = (start_line, end_line)
        
        # Step 4: Extract bodies in the order of input signatures
        result = []
        for sig in full_signatures:
            if sig in signature_to_range:
                method_line_range = signature_to_range[sig]
                
                # Find method node using tree-sitter
                method_node = utils.retrieve_buggy_method_or_constructor(java_file_path, method_line_range)
                if method_node:
                    # Find the body block node
                    body_text = None
                    body_start_line = None
                    body_end_line = None
                    for child in method_node.children:
                        if child.type == 'block':  # The body is a block node
                            # Extract body text
                            body_text = utils.get_node_text(child, code)
                            # Get body block's line range (0-based from tree-sitter, convert to 1-based)
                            body_start_line = child.start_point[0] + 1
                            body_end_line = child.end_point[0] + 1
                            break
                    
                    if body_text:
                        result.append((body_text, (body_start_line, body_end_line)))
                    else:
                        result.append(("", (0, 0)))
                else:
                    result.append(("", (0, 0)))
            else:
                result.append(("", (0, 0)))
        
        return result
        
    except Exception as e:
        print(f"Error parsing batch method body results: {e}")
        import traceback
        traceback.print_exc()
        return [("", (0, 0))] * len(full_signatures)


########################################################################################
# HELPER FUNCTIONS FOR GET_APIS_FROM_VAR
########################################################################################

def get_buggy_variable_type(session: JoernSession, java_file_path: str, var_name, line_numbers: Tuple[int, int]) -> Optional[str]:
    # Assume that there is only one variable with the given name within the buggy line range
    """
    Get the type of the buggy variable.
    
    Args:
        java_file_path: Path to the Java file containing the bug
        var_name: Name of the variable to find
        line_numbers: Tuple of (start_line, end_line) to search
    """
    # Get the class name to filter by file
    class_node = utils.retrieve_buggy_class(java_file_path, line_numbers)
    class_name = utils.extract_class_name_from_node(class_node, java_file_path)
    
    start_line, end_line = line_numbers
    # Filter by class name first (to limit to the correct file), then filter identifiers by line number
    query = f'cpg.typeDecl.name("{class_name}").ast.isIdentifier.filter(i => i.name == "{var_name}" && i.lineNumber.isDefined && i.lineNumber.get >= {start_line} && i.lineNumber.get <= {end_line}).typeFullName.l'
    
    stdout, stderr = session._run_joern_query(query)
    if not stdout:
        return None
    
    try:
        # Extract the list from Joern output
        # Look for lines with "val resX: List[String] = List(" and collect all quoted strings
        lines = stdout.strip().split('\n')
        
        # Find the line with "List(" and collect all quoted strings from subsequent lines
        found_list = False
        quoted_strings = []
        
        for line in lines:
            line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            
            # Check if this is the start of the list
            if 'val res' in line_clean and 'List[String]' in line_clean and 'List(' in line_clean:
                found_list = True
            
            # If we're inside the list, extract all quoted strings
            if found_list:
                # Find all quoted strings in this line
                matches = re.findall(r'"([^"]+)"', line_clean)
                quoted_strings.extend(matches)
                
                # Stop when we find the closing parenthesis (end of list)
                # But only if we've already found some content (to avoid stopping on the opening line)
                if ')' in line_clean and found_list and quoted_strings:
                    break
        
        # Return the first quoted string if any were found
        if quoted_strings:
            return quoted_strings[0]
        
        return None
    except Exception as e:
        print(f"Error parsing variable type: {e}")
        return None


def get_apis_from_var_type(variable_type: str, reference_checkout_dir: str) -> List[str]:
    """
    Get all APIs (methods) available for a variable type using javap.
    
    Args:
        variable_type: Fully qualified class name (e.g., "org.jfree.chart.axis.CategoryAxis" 
                        or "com.google.javascript.jscomp.Scope$Var" for inner classes)
        reference_checkout_dir: Defects4J reference checkout (e.g. .../Closure3/reference_checkout)
        
    Returns:
        List of method signatures (as strings), or empty list if error
    """
    try:
        # Get the classpath from Defects4J
        # Run: defects4j export -p cp.compile
        # Need to use Java 11 environment (same as create_cpg_from_defects4j)
        export_cmd = ["defects4j", "export", "-p", "cp.compile", "-w", reference_checkout_dir]
        result = subprocess.run(
            export_cmd,
            capture_output=True,
            text=True,
            cwd=reference_checkout_dir,
            env=d4j_utils.get_java11_env()
        )
        
        if result.returncode != 0:
            # Export failed - checkout might be broken (e.g., from a previous failed patch)
            # Reset and retry once
            print(f"ERROR: Failed to export classpath (checkout may be broken).")
        
        classpath = result.stdout.strip()
        if not classpath:
            print(f"ERROR: Empty classpath returned from Defects4J")
            return []
        
        # Convert variable type format for javap
        # javap expects:
        # - Inner classes: com.google.javascript.jscomp.Scope$Var (with $, dots for package)
        # - Regular classes: org/jfree/chart/axis/CategoryAxis (slashes, not dots)
        # But actually, javap can accept dots for both, so let's try the original format first
        # Run javap to get all methods (including private)
        # javap -classpath "$CP" -p <variable_type>
        # Note: variable_type can be:
        # - Regular class: org.jfree.chart.axis.CategoryAxis (dots)
        # - Inner class: com.google.javascript.jscomp.Scope$Var (dots with $)
        # javap handles both formats the same way - no special processing needed
        javap_cmd = ["javap", "-classpath", classpath, "-p", variable_type]
        javap_result = subprocess.run(
            javap_cmd,
            capture_output=True,
            text=True,
            cwd=reference_checkout_dir
        )
        
        if javap_result.returncode != 0:
            print(f"ERROR: javap failed: {javap_result.stderr}")
            return []
        
        # Parse javap output to extract method signatures
        methods = []
        lines = javap_result.stdout.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            # Skip empty lines, class declaration, and field declarations
            if not line or line.startswith('Compiled from') or line.startswith('public class') or line.startswith('public interface') or line.startswith('public abstract class'):
                continue
            # Skip field declarations (they don't have parentheses)
            if not '(' in line:
                continue
            # Skip constructor declarations that are just the class name
            if line.startswith('public') or line.startswith('private') or line.startswith('protected') or line.startswith('static'):
                # This is a method signature
                # Remove access modifiers and clean up
                method_sig = line
                methods.append(method_sig)
        
        return methods
        
    except Exception as e:
        print(f"Error getting APIs from variable type: {e}")
        import traceback
        traceback.print_exc()
        return []