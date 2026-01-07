import subprocess
import os
import re
import json
import sys
from typing import Optional, Tuple, List

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
            java_file_path: Path to the Java file
            joern_executable: Path to Joern executable
            joern_directory: Path to Joern installation directory (contains workspace subdirectory)
        """
        self.java_file_path = java_file_path
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
            success, defects4j_working_dir = tsh.checkout_defects4j_project(
                project_name, bug_id, checkout_dir
            )
            if not success:
                print(f"ERROR: Failed to checkout Defects4J project")
                return False
            
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


    def get_functions_in_buggy_class(self, line_numbers: Tuple[int, int]) -> List[str]:
        """
        Get all functions in the buggy class.
        
        Args:
            line_numbers: Tuple of (start_line, end_line) to search
            
        Returns:
            List of function signatures
        """
        # Step 1: Use tree-sitter to find the class containing the bug
        class_node = ib.retrieve_buggy_class(self.java_file_path, line_numbers)
        if class_node:
            # Extract class name from tree-sitter node
            class_name = ib.extract_class_name_from_node(class_node, self.java_file_path)
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


    def get_method_signature_from_line_numbers(self, line_numbers: Tuple[int, int]) -> Optional[str]:
        """
        Get the full method signature from a given line number range.
        
        Args:
            line_numbers: Tuple of (start_line, end_line) to search for method
            
        Returns:
            Full method signature if found, None otherwise
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        start_line, end_line = line_numbers
        # Originally: query = f'cpg.method.filter(m => m.lineNumber.isDefined && m.lineNumber.get >= {start_line} && m.lineNumber.get <= {end_line}).call.filter(call => call.label == "CALL" && call.name.matches("^[a-zA-Z][a-zA-Z0-9]*$")).toJson'
        # Find methods that contain the line range: method.startLine <= start_line AND method.endLine >= end_line
        query = f'cpg.method.filter(m => m.lineNumber.isDefined && m.lineNumber.get <= {start_line} && m.lineNumberEnd.isDefined && m.lineNumberEnd.get >= {end_line}).map(m => (m.fullName)).toJson'
        
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
                print("No JSON output found in Joern response")
                return None
            
            # Parse the JSON
            data = json.loads(json_str)
            
            # If data is still a string, try parsing it again
            if isinstance(data, str):
                data = json.loads(data)
            
            # The result should be a list with one method signature
            if isinstance(data, list) and len(data) > 0:
                return data[0]  # Return the first (and only) method signature
            
            return None
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            print(f"JSON string that failed: {json_str}")
            return None
        except Exception as e:
            print(f"Error processing output: {e}")
            return None
    

    # Assume that there is only one variable with the given name within the buggy line range
    def get_buggy_variable_type(self, var_name, line_numbers: Tuple[int, int]) -> Optional[str]:
        """
        Get the type of the buggy variable.
        
        Args:
            var_name: Name of the variable to find
            line_numbers: Tuple of (start_line, end_line) to search
        """
        # Get the class name to filter by file
        class_node = ib.retrieve_buggy_class(self.java_file_path, line_numbers)
        class_name = ib.extract_class_name_from_node(class_node, self.java_file_path)
        
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



    def get_callees_in_line_range(self, line_numbers: Tuple[int, int]) -> List[Tuple[str, int, str]]:
        """
        Get all method calls within a specific line range.
        
        Args:
            line_numbers: Tuple of (start_line, end_line) to search
            
        Returns:
            List of dictionaries containing method_name, method_line, and line_content
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        start_line, end_line = line_numbers
        # Get all method calls directly within the specific line range
        # Filter out operators (they start with "<operator>.") to only get actual method calls
        query = f'cpg.call.filter(call => call.lineNumber.isDefined && call.lineNumber.get >= {start_line} && call.lineNumber.get <= {end_line} && !call.name.startsWith("<operator>")).map(call => (call.name, call.lineNumber.get, call.code)).toJson'
        
        stdout, stderr = self._run_joern_query(query)
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
                return []
            
            # Remove any extra quotes at the beginning and end
            # Handle both single and double quotes
            while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                json_str = json_str[1:-1]
            
            # Handle escaped quotes within the string
            json_str = json_str.replace('\\"', '"')
            
            # Try to parse the JSON
            try:
                data = json.loads(json_str)
                
                # If data is still a string, try parsing it again
                if isinstance(data, str):
                    data = json.loads(data)
                    
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
                print(f"JSON string was: {json_str}")
                return []
            
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


    # line number, content
    def get_function_callers(self, line_numbers: Tuple[int, int]) -> Tuple[int, str]:
        """
        Get all function callers of a given function.
        
        Args:
            line_numbers: Tuple of (start_line, end_line) to search
        """
        if not self.project_name:
            raise RuntimeError("No project loaded. Call load_cpg() first.")
        
        method_signature = self.get_method_signature_from_line_numbers(line_numbers)

        query = f'cpg.call.filter(call => call.methodFullName == "{method_signature}").map(call => (call.methodFullName, call.lineNumber)).toJson'

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
                    # Handle both single and double quotes
                    while (json_str.startswith('"') and json_str.endswith('"')) or (json_str.startswith("'") and json_str.endswith("'")):
                        json_str = json_str[1:-1]
                    break
            
            if not json_str:
                print("No JSON output found in Joern response")
                return []
            
            # Handle escaped quotes within the string
            json_str = json_str.replace('\\"', '"')
            
            # Parse the JSON
            data = json.loads(json_str)
            
            # If data is still a string, try parsing it again
            if isinstance(data, str):
                data = json.loads(data)
            
            callers = []
            if isinstance(data, list):
                for caller in data:
                    if isinstance(caller, dict):
                        # Extract lineNumber from the caller object
                        # The structure is {method_name: line_number}
                        for method_name, line_number in caller.items():
                            if line_number:
                                line_content = utils.retrieve_code_by_line_number(self.java_file_path, (line_number, line_number))
                                callers.append((line_number, line_content.strip() if line_content else ""))
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
