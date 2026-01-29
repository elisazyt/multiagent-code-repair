import subprocess
import os
import re
import json
import sys
from typing import Optional, Tuple, List, Dict, Any

# Add current directory to path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

import retrieval_utils as utils
import isolate_bug as ib

# Add test_suites to path for checkout function
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_suites'))
import test_suites_helpers as tsh


# TODO: improve CFG by providing list of nodes and edges and consider more than 1-hop distance. additionally,
# consider cases where the bug location is not a method. also, check location of workspace


class JoernSession:
    """
    Simple Joern session manager that loads CPG and runs queries in separate processes.
    This is more reliable than trying to maintain an interactive session.
    """
    
    def __init__(self, java_file_path: str, joern_executable: str, joern_directory: str):
        """
        Initialize Joern session.
        
        Args:
            java_file_path: Path to a Java file (deprecated, not used - kept for backward compatibility with existing code)
            joern_executable: Path to Joern executable
            joern_directory: Path to Joern installation directory (contains workspace subdirectory)
        """
        # java_file_path parameter kept for backward compatibility but not stored
        # All methods that need file paths now accept them as parameters
        self.joern_executable = joern_executable
        self.joern_directory = joern_directory
        self.project_name = None


    def create_cpg_from_defects4j(self, project_name: str, bug_id: str, 
                                   checkout_dir: str,
                                   joern_github_dir: str) -> bool:
        """
        Create a CPG for an entire Defects4J project using javasrc2cpg.
        Automatically checks out the project if it doesn't exist.
        
        Args:
            project_name: Defects4J project name (e.g., "Closure", "Chart")
            bug_id: Bug ID (e.g., "4", "2")
            checkout_dir: Base directory where Defects4J checkouts are stored
            joern_github_dir: Path to the root directory where Joern was cloned from GitHub
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Set project name for CPG
            cpg_project_name = f"{project_name}{bug_id}"
            self.project_name = cpg_project_name
            
            # Derive javasrc2cpg path from GitHub clone directory
            javasrc2cpg_path = os.path.join(joern_github_dir, 'joern-cli', 'javasrc2cpg')
            
            # Validate javasrc2cpg exists
            if not os.path.exists(javasrc2cpg_path):
                print(f"ERROR: javasrc2cpg not found at {javasrc2cpg_path}")
                print(f"  Expected location: {joern_github_dir}/joern-cli/javasrc2cpg")
                return False
            
            # Checkout Defects4J project (will skip if already exists)
            success = tsh.checkout_defects4j_project(
                project_name, bug_id, checkout_dir
            )
            if not success:
                print(f"ERROR: Failed to checkout Defects4J project")
                return False
            
            defects4j_working_dir = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
            
            # Export classpath from Defects4J project
            print("Exporting classpath...")
            cp_result = subprocess.run(
                ['defects4j', 'export', '-p', 'cp.compile'],
                cwd=defects4j_working_dir,
                capture_output=True,
                text=True,
                env=tsh._get_java11_env()
            )
            
            if cp_result.returncode != 0:
                print(f"Failed to export classpath: {cp_result.stderr}")
                return False
            
            classpath = cp_result.stdout.strip()
            print(f"✓ Classpath: {classpath[:100]}...")  # Print first 100 chars
            
            # Create output directory
            output_dir = os.path.join(self.joern_directory, 'workspace', cpg_project_name)
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, 'cpg.bin.zip')
            
            # Check if CPG already exists
            if os.path.exists(output_path):
                print(f"CPG already exists at {output_path}, skipping creation")
                return True
            
            # Run javasrc2cpg
            print(f"Creating CPG using javasrc2cpg...")
            print(f"  Input: {defects4j_working_dir}")
            print(f"  Output: {output_path}")
            
            javasrc2cpg_cmd = [
                javasrc2cpg_path,
                defects4j_working_dir,
                '--inference-jar-paths', classpath,
                '--output', output_path
            ]
            
            result = subprocess.run(
                javasrc2cpg_cmd,
                capture_output=True,
                text=True,
                env=tsh._get_java11_env()
            )
            
            if result.returncode != 0:
                print(f"Error creating CPG with javasrc2cpg:")
                print(f"  stdout: {result.stdout}")
                print(f"  stderr: {result.stderr}")
                return False
            
            print(f"✓ CPG created successfully at {output_path}")
            return True
            
        except Exception as e:
            print(f"Error creating CPG from Defects4J: {e}")
            import traceback
            traceback.print_exc()
            return False


    def load_cpg(self, project_name: str) -> bool:
        """
        Load a CPG for a specific project.
        
        Args:
            project_name: Name of the project whose CPG to load (e.g., "Chart15")
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Construct the path to the CPG file
            cpg_path = f"{self.joern_directory}/workspace/{project_name}/cpg.bin.zip"
            
            # Check if the CPG file exists
            if not os.path.exists(cpg_path):
                print(f"CPG file not found: {cpg_path}")
                return False
            
            self.project_name = project_name
            return True
            
        except Exception as e:
            print(f"Error setting CPG path: {e}")
            return False


    def get_full_signatures_in_buggy_class(self, java_file_path: str, line_numbers: Tuple[int, int]) -> List[str]:
        """
        Get all function signatures in the buggy class.
        
        Args:
            java_file_path: Path to the Java file containing the bug
            line_numbers: Tuple of (start_line, end_line) to search
            
        Returns:
            List of function signatures
        """
        # Step 1: Use tree-sitter to find the class containing the bug
        class_node = ib.retrieve_buggy_class(java_file_path, line_numbers)
        if class_node:
            # Extract class name from tree-sitter node
            class_name = ib.extract_class_name_from_node(class_node, java_file_path)
            print("class name:", class_name)
            
            # Step 2: Use class name in Joern query
            query = f'cpg.typeDecl.name("{class_name}").method.map(m => (m.name, m.fullName)).toJson'
            stdout, stderr = self._run_joern_query(query)
            if not stdout:
                return []
            
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
                        while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                            json_str = json_str[1:-1]
                        # Handle escaped quotes
                        json_str = json_str.replace('\\"', '"')
                        break
                
                if not json_str:
                    return []
                
                # Parse the JSON
                data = json.loads(json_str)
                
                # If data is still a string, try parsing it again
                if isinstance(data, str):
                    data = json.loads(data)
                
                # Extract method full names from the list of dicts
                # Format: [{"methodName": "fullName"}, ...]
                method_signatures = []
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            # Each dict has one key-value pair: {methodName: fullName}
                            method_signatures.extend(item.values())
                
                return method_signatures
                
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                return []
            except Exception as e:
                print(f"Error processing output: {e}")
                return []
        
        return []


    @staticmethod
    def _parse_joern_json_with_unescaped_quotes(json_str: str) -> Optional[list]:
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
        # Replace \" with " (handles double-escaped quotes from Joern output)
        try:
            json_str_unescaped = json_str.replace('\\"', '"')
            return json.loads(json_str_unescaped)
        except (json.JSONDecodeError, ValueError):
            pass
            
            # If parsing fails, try to extract data manually using regex
            # This handles cases like: {"_1":729,"_2":"code with \"unescaped\" quotes"}
            import re
            results = []
            
            # Find all {"_1":value patterns and extract the values
            # Try with escaped quotes first, then unescaped
            json_str_for_regex = json_str.replace('\\"', '"')  # Unescape for regex matching
            for match in re.finditer(r'\{"_1":([^,]+),"_2":"', json_str_for_regex):
                value1 = match.group(1)
                code_start = match.end()
                
                # Find the closing " before } or ,
                code_end = code_start
                while code_end < len(json_str_for_regex):
                    if json_str_for_regex[code_end] == '"' and code_end + 1 < len(json_str_for_regex):
                        next_char = json_str_for_regex[code_end + 1]
                        if next_char in [',', '}']:
                            break
                    code_end += 1
                
                code = json_str_for_regex[code_start:code_end]
                
                # Try to parse value1 as int, otherwise keep as string
                try:
                    value1 = int(value1)
                except ValueError:
                    pass
                
                results.append({'_1': value1, '_2': code})
            
        # Pattern 2: 3-value tuples {"_1":value1,"_2":value2,"_3":"code"}
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
            
            # Parse values as int if possible
            try:
                value1 = int(value1)
            except ValueError:
                pass
            try:
                value2 = int(value2)
            except ValueError:
                pass
            
            results.append({'_1': value1, '_2': value2, '_3': code})
        
        # Return results if found, otherwise None
        return results if results else None

    # Example: org.jfree.data.general.DatasetUtilities.iterateDomainBounds:org.jfree.data.Range(org.jfree.data.xy.XYDataset,boolean)
    def get_full_method_signature_from_line_numbers(self, java_file_path: str, line_numbers: Tuple[int, int], class_name: str) -> Optional[str]:
        """
        Get the full method signature from a given line number range for a specific file.
        
        Args:
            java_file_path: Path to the Java file to filter by
            line_numbers: Tuple of (start_line, end_line) to search for method
            class_name: Class name (e.g., "CategoryPlot") to filter by file name.
                       Filters results to methods in files ending with "{class_name}.java"
            
        Returns:
            Full method signature if found, None otherwise
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        start_line, end_line = line_numbers
        # Find methods that contain the line range, excluding static initializers
        # Filter by class name in file path
        query = f'cpg.method.filter(m => m.lineNumber.isDefined && m.lineNumber.get <= {start_line} && m.lineNumberEnd.isDefined && m.lineNumberEnd.get >= {end_line} && m.name != "<clinit>" && m.file.name.filter(_.endsWith("{class_name}.java")).nonEmpty).map(m => (m.fullName)).toJson'
        
        stdout, stderr = self._run_joern_query(query)
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
    
    def get_code_from_full_signatures_batch(self, full_signatures: List[str]) -> Dict[str, Optional[str]]:
        """
        Get method code for multiple signatures in a single Joern query (much faster than individual calls).
        
        Args:
            full_signatures: List of full method signatures
            
        Returns:
            Dictionary mapping signature -> code (or None if not found)
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        if not full_signatures:
            return {}
        
        # Build a batch query that gets code for all signatures at once
        # Create a map of signature -> code
        signature_list_str = ', '.join([f'"{sig}"' for sig in full_signatures])
        query = f'cpg.method.filter(m => List({signature_list_str}).contains(m.fullName)).map(m => (m.fullName, m.code)).toJson'
        
        stdout, stderr = self._run_joern_query(query)
        if stderr and not any(harmless in stderr for harmless in ['sun.misc.Unsafe', 'scala.runtime.LazyVals', 'java.lang.System::load']):
            print(f"DEBUG get_code_from_full_signatures_batch stderr: {stderr}")
        if not stdout:
            # Fallback: return None for all signatures
            return {sig: None for sig in full_signatures}
        
        try:
            # Parse JSON output: List[(String, String)] where first is fullName, second is code
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
                return {sig: None for sig in full_signatures}
            
            # Parse JSON array - Joern returns array of objects: [{"signature1": "code1"}, {"signature2": "code2"}, ...]
            data = json.loads(json_str)
            if isinstance(data, str):
                data = json.loads(data)
            
            # Build result dictionary
            result = {sig: None for sig in full_signatures}  # Initialize all to None
            if isinstance(data, list):
                for item in data:
                    # Each item is a dict like {"signature": "code"}
                    if isinstance(item, dict):
                        for full_name, code in item.items():
                            if full_name in result:
                                result[full_name] = code
            
            return result
            
        except Exception as e:
            print(f"Error parsing batch code results: {e}")
            return {sig: None for sig in full_signatures}

    def get_method_bodies_from_signatures_batch(self, java_file_path: str, full_signatures: List[str]) -> List[Tuple[str, Tuple[int, int]]]:
        """
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
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        if not full_signatures:
            return []
        
        # Step 1: Get line ranges from Joern for all signatures (batch query)
        signature_list_str = ', '.join([f'"{sig}"' for sig in full_signatures])
        query = f'cpg.method.filter(m => List({signature_list_str}).contains(m.fullName)).map(m => (m.fullName, m.lineNumber.get, m.lineNumberEnd.get)).toJson'
        
        stdout, stderr = self._run_joern_query(query)
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
                    method_node = ib.retrieve_buggy_method_or_constructor(java_file_path, method_line_range)
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


    # Assume that there is only one variable with the given name within the buggy line range
    def get_buggy_variable_type(self, java_file_path: str, var_name, line_numbers: Tuple[int, int]) -> Optional[str]:
        """
        Get the type of the buggy variable.
        
        Args:
            java_file_path: Path to the Java file containing the bug
            var_name: Name of the variable to find
            line_numbers: Tuple of (start_line, end_line) to search
        """
        # Get the class name to filter by file
        class_node = ib.retrieve_buggy_class(java_file_path, line_numbers)
        class_name = ib.extract_class_name_from_node(class_node, java_file_path)
        
        start_line, end_line = line_numbers
        # Filter by class name first (to limit to the correct file), then filter identifiers by line number
        query = f'cpg.typeDecl.name("{class_name}").ast.isIdentifier.filter(i => i.name == "{var_name}" && i.lineNumber.isDefined && i.lineNumber.get >= {start_line} && i.lineNumber.get <= {end_line}).typeFullName.l'
        
        stdout, stderr = self._run_joern_query(query)
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

    def get_apis_from_var(self, java_file_path: str, var_name: str, line_numbers: Tuple[int, int], project_name: str, bug_id: str, checkout_dir: str) -> List[str]:
        """
        Get all APIs (methods) available for a variable by first getting its type, then retrieving APIs for that type.
        
        Args:
            java_file_path: Path to the Java file containing the bug
            var_name: Name of the variable to get APIs for
            line_numbers: Tuple of (start_line, end_line) where the variable is used
            project_name: Defects4J project name (e.g., "Chart", "Closure")
            bug_id: Defects4J bug ID (e.g., "4", "8")
            checkout_dir: Base directory where Defects4J checkouts are stored
            
        Returns:
            List of method signatures (as strings), or empty list if error or variable type not found
        """
        # First, get the variable type
        variable_type = self.get_buggy_variable_type(java_file_path, var_name, line_numbers)
        
        if variable_type is None:
            print(f"ERROR: Could not determine type for variable '{var_name}' at lines {line_numbers}")
            return []
        
        # Then, get APIs for that type
        return self.get_apis_from_var_type(variable_type, project_name, bug_id, checkout_dir)

    def get_apis_from_var_type(self, variable_type: str, project_name: str, bug_id: str, checkout_dir: str) -> List[str]:
        """
        Get all APIs (methods) available for a variable type using javap.
        
        Args:
            variable_type: Fully qualified class name (e.g., "org.jfree.chart.axis.CategoryAxis" 
                          or "com.google.javascript.jscomp.Scope$Var" for inner classes)
            project_name: Defects4J project name (e.g., "Chart", "Closure")
            bug_id: Defects4J bug ID (e.g., "4", "8")
            checkout_dir: Base directory where Defects4J checkouts are stored
            
        Returns:
            List of method signatures (as strings), or empty list if error
        """
        try:
            # Ensure checkout exists (reuse if available, don't check compilation)
            success = tsh.checkout_defects4j_project(project_name, bug_id, checkout_dir)
            if not success:
                print(f"ERROR: Failed to ensure checkout is available")
                return []
            
            project_checkout = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
            
            # Get the classpath from Defects4J
            # Run: defects4j export -p cp.compile
            # Need to use Java 11 environment (same as create_cpg_from_defects4j)
            export_cmd = ["defects4j", "export", "-p", "cp.compile", "-w", project_checkout]
            result = subprocess.run(
                export_cmd,
                capture_output=True,
                text=True,
                cwd=project_checkout,
                env=tsh._get_java11_env()
            )
            
            if result.returncode != 0:
                # Export failed - checkout might be broken (e.g., from a previous failed patch)
                # Reset and retry once
                print(f"ERROR: Failed to export classpath (checkout may be broken). Resetting checkout...")
                reset_success = tsh.reset_checkout(project_name, bug_id, checkout_dir)
                if not reset_success:
                    print(f"ERROR: Failed to reset checkout")
                    return []
                
                # Retry export after reset
                result = subprocess.run(
                    export_cmd,
                    capture_output=True,
                    text=True,
                    cwd=project_checkout,
                    env=tsh._get_java11_env()
                )
                
                if result.returncode != 0:
                    print(f"ERROR: Failed to export classpath even after reset: {result.stderr}")
                    return []
            
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
                cwd=project_checkout
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



    def get_callees_in_line_range(self, java_file_path: str, line_numbers: Tuple[int, int], class_name: str) -> List[Tuple[str, int, str]]:
        """
        Get all method calls within a specific line range for a specific file.
        
        Args:
            java_file_path: Path to the Java file to filter by
            line_numbers: Tuple of (start_line, end_line) to search
            class_name: Class name (e.g., "CategoryPlot") to filter by file name.
                       Filters results to calls in files ending with "{class_name}.java"
            
        Returns:
            List of tuples (method_name, line_number, code) for each callee
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        start_line, end_line = line_numbers
        
        # Get all method calls directly within the specific line range
        # Filter out operators (they start with "<operator>.") to only get actual method calls
        # Filter by class name in file path
        query = f'cpg.call.filter(call => call.lineNumber.isDefined && call.lineNumber.get >= {start_line} && call.lineNumber.get <= {end_line} && !call.name.startsWith("<operator>") && call.file.name.filter(_.endsWith("{class_name}.java")).nonEmpty).map(call => (call.name, call.lineNumber.get, call.code)).toJson'
        
        stdout, stderr = self._run_joern_query(query)
        if stderr:
            print(f"DEBUG get_callees_in_line_range stderr: {stderr}")
        if not stdout:
            return []
        
        try:
            # Extract JSON string from Joern output
            lines = stdout.strip().split('\n')
            json_str = None
            
            # Try multiple patterns to find the JSON output
            for line in lines:
                # Strip ANSI color codes
                line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                
                # Pattern 1: "val resX: String = ..."
                if 'val res' in line_clean and 'String = ' in line_clean:
                    json_start = line_clean.find('String = ') + 8
                    json_str = line_clean[json_start:].strip()
                    break
                # Pattern 2: Look for lines that start with "[" (JSON array)
                elif line_clean.strip().startswith('[') and line_clean.strip().endswith(']'):
                    json_str = line_clean.strip()
                    break
                # Pattern 3: Look for lines containing JSON-like structure
                elif ('[' in line_clean and '{' in line_clean and '_1' in line_clean):
                    # Try to extract JSON from this line
                    # Find the JSON array part
                    start_idx = line_clean.find('[')
                    end_idx = line_clean.rfind(']') + 1
                    if start_idx >= 0 and end_idx > start_idx:
                        json_str = line_clean[start_idx:end_idx]
                    break
            
            if not json_str:
                print(f"DEBUG get_callees_in_line_range: No JSON found. stdout was:\n{stdout[:500]}")
                return []
            
            # Remove any extra quotes at the beginning and end
            # Handle both single and double quotes
            while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                json_str = json_str[1:-1]
            
            # Handle escaped quotes within the string
            json_str = json_str.replace('\\"', '"')
            
            # Try to parse the JSON (handles unescaped quotes in code strings)
            data = JoernSession._parse_joern_json_with_unescaped_quotes(json_str)
            if data is None:
                print(f"Failed to parse JSON. JSON string was: {json_str[:200]}")
                return []
                
                # If data is still a string, try parsing it again
                if isinstance(data, str):
                    data = json.loads(data)
            
            callees = []
            if isinstance(data, list):
                for callee in data:
                    if isinstance(callee, dict) and '_1' in callee and '_2' in callee and '_3' in callee:
                        # Joern serializes tuples as objects with _1, _2, _3 keys
                        # Format: {"_1": name, "_2": lineNumber, "_3": code}
                        method_name = callee['_1']
                        line_number = callee['_2']
                        code = callee['_3']
                        
                        if method_name and line_number:
                            callees.append((method_name, line_number, code if code else ""))
            else:
                print(f"Expected list but got {type(data)}: {data}")
            
            return callees
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            print(f"Raw output: {stdout}")
            return []
        except Exception as e:
            print(f"Error processing output: {e}")
            return []


    def get_function_callers(self, java_file_path: str, line_numbers: Tuple[int, int], class_name: str) -> List[Tuple[int, str]]:
        """
        Get all function callers of a given function.
        
        Args:
            java_file_path: Path to the Java file containing the bug
            line_numbers: Tuple of (start_line, end_line) to search
            class_name: Class name (e.g., "CategoryPlot") to filter method signature lookup
            
        Returns:
            List of tuples (line_number, content) where the function is called
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        method_signature = self.get_method_signature_from_line_numbers(java_file_path, line_numbers, class_name)
        if not method_signature:
            print(f"DEBUG get_function_callers: Could not find method signature for {java_file_path} at lines {line_numbers} with class_name {class_name}")
            return []
        
        print(f"DEBUG get_function_callers: Found method signature: {method_signature}")

        # Find calls to this method and get the line number where the call occurs
        # Search entire project for callers (callers can be in any file)
        query = f'cpg.call.filter(call => call.methodFullName == "{method_signature}").map(call => (call.lineNumber.get, call.code)).toJson'

        stdout, stderr = self._run_joern_query(query)
        if stderr:
            print(f"DEBUG get_function_callers stderr: {stderr}")
        if not stdout:
            print(f"DEBUG get_function_callers: No stdout. Query was: {query}")
            return []
        
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
                    print(f"DEBUG get_function_callers: Extracted from 'val res' pattern: {json_str[:100]}")
                    break
                # Also try pattern 2: lines that start with "[" (JSON array)
                elif line_clean.strip().startswith('[') and line_clean.strip().endswith(']'):
                    json_str = line_clean.strip()
                    print(f"DEBUG get_function_callers: Extracted from '[' pattern: {json_str[:100]}")
                    break
            
            if not json_str:
                print(f"DEBUG get_function_callers: No JSON found. stdout was:\n{stdout[:500]}")
                return []
            
            print(f"DEBUG get_function_callers: JSON string (first 500 chars): {json_str[:500]}")
            
            # Parse the JSON (handles unescaped quotes in code strings)
            data = JoernSession._parse_joern_json_with_unescaped_quotes(json_str)
            if data is None:
                print(f"Warning: Could not parse callers JSON, returning empty list")
                print(f"DEBUG: Full JSON string that failed: {json_str}")
                return []
            
            # If data is still a string, try parsing it again
            if isinstance(data, str):
                data = json.loads(data)
            
            callers = []
            if isinstance(data, list):
                for caller in data:
                    if isinstance(caller, dict) and '_1' in caller and '_2' in caller:
                        # Joern serializes tuples as objects with _1, _2 keys
                        # Format: {"_1": lineNumber, "_2": code}
                        line_number = caller['_1']
                        code = caller['_2']
                        if line_number:
                            callers.append((line_number, code if code else ""))
            else:
                print(f"Expected list but got {type(data)}")
            
            return callers
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            print(f"JSON string that failed: {json_str}")
            return []
        except Exception as e:
            print(f"Error processing output: {e}")
            return []
    

    def _run_joern_query(self, query: str) -> Tuple[Optional[str], str]:
        """
        Helper method to run a Joern query with CPG loading.
        
        Args:
            query: The Joern query to execute
            
        Returns:
            Tuple of (stdout, stderr) - stdout is None if there was an error
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        try:
            if not self.project_name:
                raise RuntimeError("Project name not set. Call load_cpg() first.")
            
            # Check if project.json exists (project already imported) or if we have a zip file
            cpg_zip_path = f"{self.joern_directory}/workspace/{self.project_name}/cpg.bin.zip"
            project_json_path = f"{self.joern_directory}/workspace/{self.project_name}/project.json"
            
            # If project.json exists, use open() (project already imported)
            # If only zip exists, use importCpg() to import it
            if os.path.exists(project_json_path):
                load_command = f'open("{self.project_name}")'
            elif os.path.exists(cpg_zip_path):
                # Import the zip file - Joern will derive project name from path
                load_command = f'importCpg("{cpg_zip_path}")'
            else:
                raise RuntimeError(f"CPG not found for project {self.project_name}")
            
            commands = f"{load_command}\n{query}\n"
            
            # Run in a new process
            process = subprocess.Popen(
                [self.joern_executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.joern_directory
            )
            
            stdout, stderr = process.communicate(input=commands)
            
            if process.returncode != 0:
                print(f"Error running query: {stderr}")
                return None, stderr
                
            return stdout, stderr
            
        except Exception as e:
            print(f"Error running query: {e}")
            return None, str(e)
