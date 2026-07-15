"""
Helper functions for running Defects4J commands

- Defects4J API reference: https://defects4j.org/html_doc/index.html
"""

import os
import shutil
import subprocess


def checkout_defects4j_project(project_name: str, bug_id: str, checkout_dir: str, buggy: bool) -> bool:
    """
    Checkout the buggy version of a Defects4J project.
    Can specify any arbirary checkout_dir, for this project we always checkout to the reference directory
    
    Parameters:
    - project_name (str): Project name (e.g., 'Chart', 'Closure', 'Lang')
    - bug_id (str): Bug ID (e.g., '2', '3', '4')
    - checkout_dir (str): Exact directory to checkout the project to
    - buggy (bool): Specifies whether to check out the buggy or fixed version
    
    Returns:
    - bool: True if checkout succeeded or already exists, False otherwise
    """
    try:
        if buggy:
            version_id = bug_id + 'b'
        else:
            version_id = bug_id + 'f'

        def run_checkout():
            return subprocess.run(
                    ['defects4j', 'checkout', '-p', project_name, '-v', version_id, '-w', checkout_dir],
                    capture_output=True,
                    text=True,
                    env=get_java11_env()
                )

        result = run_checkout()
        if result.returncode == 0:
            return True

        # Checkout can fail if checkout_dir already contains a stale/corrupted checkout
        # (e.g. from a previous run that crashed mid-checkout). Wipe it and retry once.
        if os.path.exists(checkout_dir):
            shutil.rmtree(checkout_dir)
            os.makedirs(checkout_dir, exist_ok=True)
        result = run_checkout()
        return result.returncode == 0

    except Exception as e:
        print(f"[ERROR] checkout_defects4j_project hit an exception: {e}")
        return False


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
            print(f"[ERROR] get_modified_sources: Failed to run command to get modified sources: {result.stderr}")
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
        print(f"[ERROR] get_modified_sources hit an exception: {e}")
        return []


def get_java11_env():
    """
    Get Java 11 env dict for running Defects4J-related subprocess commands.

    Note that some tools (e.g. Joern) expect newer Java versions so our environment has multiple
    JDKs, we specifically want Java 11 for Defects4J
    """
    # make a copy of the existing dict of environment variables, etc
    env = os.environ.copy()

    # JAVA11_HOME is the location where JDK is installed, it should already be set
    # in the environment but added a fallback just in case
    java11_path = env.get('JAVA11_HOME')
    if not java11_path:
        try:
            java11_path = subprocess.run(['/usr/libexec/java_home', '-v', '11'], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            java11_path = None  # Fallback to default if Java 11 not found

    if java11_path:
        # set path to JDK 11
        env['JAVA_HOME'] = java11_path
        existing_path = env.get('PATH', '')
        # set path to JDK 11 binary
        env['PATH'] = f"{java11_path}/bin:{existing_path}"
    
    return env