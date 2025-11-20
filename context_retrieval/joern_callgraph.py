import subprocess
import os
import re
import json
from typing import Optional, Tuple, List
import retrieval_utils as utils


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


    def create_cpg(self, project_path: str, project_name: str) -> bool:
        """
        Create and save a CPG for a given project
        
        Args:
            project_path: Path to the source code directory/file
            project_name: Name for the Joern project
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Set project name immediately
            self.project_name = project_name
            
            # Ensure the main workspace directory exists
            os.makedirs(self.joern_directory, exist_ok=True)
            
            # Commands to import code and save CPG
            commands = [
                f'importCode(inputPath="{project_path}", projectName="{project_name}")',
                'save'
            ]
            
            # Run Joern with the commands from the main workspace directory
            process = subprocess.Popen(
                [self.joern_executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.joern_directory
            )
            
            command_string = "\n".join(commands) + "\n"
            stdout, stderr = process.communicate(input=command_string)
            
            if process.returncode != 0:
                print(f"Error creating CPG: {stderr}")
                return False
            
            return True
            
        except Exception as e:
            print(f"Error creating CPG: {e}")
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
            cpg_path = f"{self.joern_directory}/workspace/{project_name}/cpg.bin"
            
            # Check if the CPG file exists
            if not os.path.exists(cpg_path):
                print(f"CPG file not found: {cpg_path}")
                return False
            
            self.project_name = project_name
            return True
            
        except Exception as e:
            print(f"Error setting CPG path: {e}")
            return False



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
            # Use open() to load existing project - this doesn't overwrite the CPG
            # open(projectName) opens the existing project and makes it active
            # This is safer than importCpg() which can overwrite/corrupt the CPG
            if not self.project_name:
                raise RuntimeError("Project name not set. Call load_cpg() first.")
            
            load_command = f'open("{self.project_name}")'
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
