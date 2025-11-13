import os
import sys

# Add parent directory to path to import test_suites
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_suites import test_suites as ts
from info_dict import InfoDict

class TestingAgent:
    def __init__(self, information: InfoDict):
        self.information = information
    
    # If run returns a string, that means there are failing tests and we need to regenerate the patch.
    # Else, the patch passed the test suite and can be stored as a candidate.
    def run(self, mapping: dict[str, str]):
        self.information.get_info("message history").add_prompt("Run the test suites for the generated patches.")

        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        working_directory = self.information.get_info("working directory")
        test_result = ts.run_defects4j_test(project_name, bug_id, working_directory, mapping)

        failing_test_info_string = ""

        for test_info in test_result:
            if test_info['success'] == False:
                failing_test_info_string += 'Error: Test command did not run. Check for possible errors such as compile errors.'
            if len(test_info['failing_tests']) > 0:
                failing_test_info_string += ts.get_failing_test_info(self.information.get_info("working directory"), self.information.get_info("project name"), test_info['failing_tests'])
                failing_test_info_string += '\n'
        
        if failing_test_info_string != "":
            self.information.get_info("message history").add_agent("testing", failing_test_info_string)
            return failing_test_info_string
        else:
            self.information.get_info("message history").add_agent("testing", "Patch passed the test suite and can be stored as a candidate.")
            return None