Overview:
- Supports multi-location patching across multiple files
- Input:
    - Bug project and ID (e.g. Chart 1)
    - Relevant directories for running test suites and saving the patch
    - List of bug locations as (start line, end line) tuples
    - Agent prompts
- Output:
    - Patched .java file(s)
    - Message history, saved as a .txt file

COMPONENTS OF SYSTEM:

API database (complete):
- Existing APIs:
    - Retrieve existing API imports in each file
- New APIs:
    - json database of relevant APIs, classified by purpose: Javascript handling, Collection, I/O handling, built-in, miscellaneous/other
    - Function call for agent to analyze file and return APIs from relevant categories
        - Input: prompt, bug context, and list of existing APIs
        - Output: list of candidate APIs that haven’t already been imported
- Final output:
    - List of existing APIs
    - List of relevant API categories, and the corresponding candidate APIs
    - Agent explanation for why the APIs might be useful

Test suites (complete):
- Runs tests:
    - Input: Bug project and ID, working directory to check out the project and run the test, path(s) to the patch file(s)
    - Output: List of failing tests for each buggy function
- If the test runs successfully (success code = 0), returns details about the test results:
    - Failing test name
    - Failure message
    - Entire failing method in the test file, and the exact line at which it fails

Context retrieval (incomplete):
- AST (tree sitter):
    - Retrieve code by line number: get exact code at bug locations
    - Retrieve method by name: extract entire buggy function
    - Get comments before node
- CPG (joern):
    - Get function callers and callees
- To be implemented: data dependency graph, expand context retrieval beyond function scope

Information storage for agents (complete):
- Message history: full conversation history for each agent, containing prompts and agent responses
    - Prompts: human prompt and retrieved context
    - Agent responses: patches and test suite feedback
- Info dict: dictionary of relevant info, stored as an instance variable for each agent
    - Contains message history and project info (bug project and ID, relevant file paths, bug locations)

Agents (incomplete):
- GPT client: initialize agent, send prompt, receive response
- Patching agent:
    - Instance variables: role, prompt, info dict, GPT client
    - Methods:
        - Run: generate and save the patch
        - Regenerate patch: rerun, given failing test info
        - Helper methods to retrieve and format relevant bug context
    - Subclasses: Basic, API, repair pattern, chain of thought?
- Testing agent: runs the tests suites
