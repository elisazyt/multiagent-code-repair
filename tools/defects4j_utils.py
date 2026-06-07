"""
Helper functions for running Defects4J commands
"""

import os
import subprocess

def checkout_defects4j_project(project_name: str, bug_id: str, checkout_dir: str) -> bool:
    """Checkout the buggy version of a Defects4J project.
    Can specify any arbirary checkout_dir, for this project we always checkout to the reference directory
    
    Parameters:
    - project_name (str): Project name (e.g., 'Chart', 'Closure', 'Lang')
    - bug_id (str): Bug ID (e.g., '2', '3', '4') - will be converted to '2b', '3b', etc.
    - checkout_dir (str): Exact directory to checkout the project to
    
    Returns:
    - bool: True if checkout succeeded or already exists, False otherwise
    """
    try:
        print(f"Checking out Defects4J project {project_name} {bug_id} to {checkout_dir}...")
        result = subprocess.run(
            ['defects4j', 'checkout', '-p', project_name, '-v', bug_id + 'b', '-w', checkout_dir],
            capture_output=True,
            text=True,
            env=get_java11_env()
        )

        if result.returncode == 0:
            print(f"✓ Checked out to {checkout_dir}")
            return True
        else:
            print(f"Failed to checkout project: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error during checkout: {e}")
        return False

# Note: get_modified_sources is different from get_modified_source, defined in bugdict_helpers.py
# get_modified_source is used to get the modified source name for a single Java file, if we care about 
# which modified source name maps to which file. This is a helper for BugDict.add_bug_locations
# get_modified_sources is used to get all modified sources for a buggy project. This is a helper
# for test_suites.run_defects4j_test
def get_modified_sources(project_name: str, bug_id: str) -> list[str]:
    """
    Get the list of all modified sources for a specific bug.
    
    Parameters:
    - project_name (str): Project name (e.g., 'Chart', 'Closure', 'Lang')
    - bug_id (str): Bug ID (e.g., '2', '3', '4')
    
    Returns:
    - list[str]: List of modified source packages (e.g., ['com.google.javascript.jscomp.TypeCheck'])
    """
    try:
        # This command returns all bug ids and modified lines for a project, we later need to filter by bug id
        result = subprocess.run(
            ['defects4j', 'query', '-p', project_name, '-q', 'bug.id,classes.modified'],
            capture_output=True,
            text=True,
            env=get_java11_env(),
        )

        if result.returncode != 0:
            print(f"Failed to get modified sources: {result.stderr}")
            return []

        # result is a string of the form: bug id,"class1;class2;class3..."
        #  where the modified classes are separated by semicolons. One bug id per line
        bug_id = str(bug_id)
        for line in result.stdout.strip().splitlines():
            if ',' not in line:
                continue
            # bug id and the modified classes are separated by a comma
            row_bug_id, classes = line.split(',', 1)
            # search for the specific bug id we're looking for
            if row_bug_id != bug_id:
                continue
            classes = classes.strip().strip('"')
            return [source.strip() for source in classes.split(';') if source.strip()]
        return []
    except Exception as e:
        print(f"Error getting modified sources: {e}")
        return []

# All Defects4J commands run in Java 11
def get_java11_env():
    """
    Get environment with Java 11 for Defects4J.
    
    Returns:
        Environment dict with Java 11 and Defects4J variables set.
    
    Raises:
        ValueError: If DEFECTS4J_HOME is not set in the environment.
    """
    env = os.environ.copy()
    
    # Check for DEFECTS4J_HOME
    if 'DEFECTS4J_HOME' not in env:
        raise ValueError("DEFECTS4J_HOME environment variable is not set. Please set it according to Defects4J installation instructions.")
    
    # Set PERL5LIB to include Defects4J's core directory
    defects4j_home = env['DEFECTS4J_HOME']
    perl5lib = os.path.join(defects4j_home, 'core')
    existing_perl5lib = env.get('PERL5LIB', '')
    if existing_perl5lib:
        env['PERL5LIB'] = f"{perl5lib}:{existing_perl5lib}"
    else:
        env['PERL5LIB'] = perl5lib
    
    # Set Java 11
    try:
        java11_path = subprocess.run(['/usr/libexec/java_home', '-v', '11'], capture_output=True, text=True, check=True).stdout.strip()
        env['JAVA_HOME'] = java11_path
        existing_path = env.get('PATH', '')
        env['PATH'] = f"{java11_path}/bin:{existing_path}"
    except:
        pass  # Fallback to default if Java 11 not found
    
    return env