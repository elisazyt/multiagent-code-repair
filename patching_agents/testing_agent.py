import os
import sys

# Add parent directory to path to import test_suites
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_suites import test_suites as ts
from info_dict import InfoDict

class TestingAgent:
    def __init__(self, information: InfoDict):
        self.information = information
    
    def run(self, mapping: dict[str, str]):
        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        working_directory = self.information.get_info("working directory")
        test_result = ts.run_defects4j_test(project_name, bug_id, working_directory, mapping)
        return test_result
'''
for entry in test_result:
    if 'error' in entry:
        print(f"Error: {entry['error']}")
        continue
    
    if 'failing_tests' in entry:
        failing_tests = entry['failing_tests']
        if failing_tests:  # Only get info if there are failing tests
            failing_test_info = ts.get_failing_test_info(working_directory, 'Chart', failing_tests)
            if failing_test_info:
                print(failing_test_info[0].get('buggy method'))
    else:
        print(f"Unexpected entry format: {entry}")
'''