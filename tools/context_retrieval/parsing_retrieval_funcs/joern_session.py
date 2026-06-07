import subprocess
import os
import sys
from typing import Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from tools import defects4j_utils as d4j_utils


# TODO: improve CFG by providing list of nodes and edges and consider more than 1-hop distance. additionally,
# consider cases where the bug location is not a method.


class JoernSession:
    """
    Simple Joern session manager that loads CPG and runs queries in separate processes.
    This is more reliable than trying to maintain an interactive session.
    """
    
    def __init__(
        self,
        joern_executable: str,
        joern_workspace_path: str,
        joern_working_dir: str,
    ):
        """
        Initialize Joern session.
        
        Args:
            joern_executable: Path to Joern executable
            joern_workspace_path: Path to workspace folder for this specific project
            joern_working_dir: where Joern is installed and runs from
        """
        self.joern_executable = joern_executable
        self.joern_workspace_path = joern_workspace_path
        self.joern_working_dir = joern_working_dir
        self.project_name = None

    def create_cpg_from_defects4j(self, project_name: str, bug_id: str, 
                                   reference_checkout_dir: str) -> bool:
        """
        Create a CPG for an entire Defects4J project using javasrc2cpg.
        Automatically checks out the project if it doesn't exist.
        
        Args:
            project_name: Defects4J project name (e.g., "Closure", "Chart")
            bug_id: Bug ID (e.g., "4", "2")
            reference_checkout_dir: Unmodified reference checkout directory where we perform all CPG operations
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Set project name for CPG
            cpg_project_name = f"{project_name}{bug_id}"
            self.project_name = cpg_project_name
            
            # Homebrew: javasrc2cpg lives next to joern in joern_working_dir
            javasrc2cpg_path = os.path.join(self.joern_working_dir, "javasrc2cpg")
            if not os.path.exists(javasrc2cpg_path):
                print(f"ERROR: javasrc2cpg not found at {javasrc2cpg_path}")
                return False
            
            # Checkout Defects4J project (will skip if already exists)
            success = d4j_utils.checkout_defects4j_project(
                project_name, bug_id, reference_checkout_dir
            )
            if not success:
                print(f"ERROR: Failed to checkout Defects4J project")
                return False
            
            # Export classpath from Defects4J project
            print("Exporting classpath...")
            cp_result = subprocess.run(
                ['defects4j', 'export', '-p', 'cp.compile'],
                cwd=reference_checkout_dir,
                capture_output=True,
                text=True,
                env=d4j_utils.get_java11_env()
            )
            
            if cp_result.returncode != 0:
                print(f"Failed to export classpath: {cp_result.stderr}")
                return False
            
            classpath = cp_result.stdout.strip()
            print(f"✓ Classpath: {classpath[:100]}...")  # Print first 100 chars
            
            # Create output directory
            os.makedirs(self.joern_workspace_path, exist_ok=True)
            output_path = os.path.join(self.joern_workspace_path, 'cpg.bin.zip')
            
            # Check if CPG already exists
            if os.path.exists(output_path):
                print(f"CPG already exists at {output_path}, skipping creation")
                return True
            
            # Run javasrc2cpg
            print(f"Creating CPG using javasrc2cpg...")
            print(f"  Input: {reference_checkout_dir}")
            print(f"  Output: {output_path}")
            
            javasrc2cpg_cmd = [
                javasrc2cpg_path,
                reference_checkout_dir,
                '--inference-jar-paths', classpath,
                '--output', output_path
            ]
            
            result = subprocess.run(
                javasrc2cpg_cmd,
                capture_output=True,
                text=True,
                env=d4j_utils.get_java11_env()
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
            cpg_path = os.path.join(self.joern_workspace_path, "cpg.bin.zip")
            
            # Check if the CPG file exists
            if not os.path.exists(cpg_path):
                print(f"CPG file not found: {cpg_path}")
                return False
            
            self.project_name = project_name
            return True
            
        except Exception as e:
            print(f"Error setting CPG path: {e}")
            return False
    

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
            cpg_zip_path = os.path.join(self.joern_workspace_path, "cpg.bin.zip")
            project_json_path = os.path.join(self.joern_workspace_path, "project.json")
            
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
                cwd=self.joern_working_dir
            )
            
            stdout, stderr = process.communicate(input=commands)
            
            if process.returncode != 0:
                print(f"Error running query: {stderr}")
                return None, stderr
                
            return stdout, stderr
            
        except Exception as e:
            print(f"Error running query: {e}")
            return None, str(e)
