SYSTEM_DESCRIPTION = """
TASK:
Generate a patch for the buggy Java code.

Do not assume any methods exist unless they are explicitly called or defined.
If the patch calls a new method, it should be explicitly defined and fully implemented,
without any placeholder logic.

All buggy locations should be fixed. Refactoring and commenting should not be considered fixes.

The user cannot modify your code, so do not suggest incomplete code which requires others to modify.
Suggest the full code instead of partial code or code changes.

RETURN FORMAT:
For every single bug location, return the patch for the entire buggy node in markdown format, enclosed in the following syntax:
```java

```
Additionally, briefly explain your reasoning for the patch.

Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
The number of markdown blocks should equal the number of bug locations.
The patch should contain the full code for the bug location.
"""


BASIC_PROMPT = "Carry out the given task given by the system description."

# TODO: placeholder, add actual COT prompt later
COT_PROMPT = f"""
You are a highly skilled software engineer with expertise in debugging and patching programs.
    Carry out the task by generating a patch for the buggy code. Carefully read the code to understand its purpose and
    logic, then identify issues that could cause the code to fail or produce incorrect results. Rewrite the code,
    correcting the identified bugs, and add detailed comments explaining the changes you made and why they address the
    issues.
"""

API_PROMPT = f"""
You are an agent that retrieves and uses any necessary APIs to carry out the task given by the system
description. Some bug fixes don't require API usage, so you should first analyze the context and determine
if new APIs are needed.

Whenever possible, use the retrieved APIs instead of creating your own functions."""


CONTEXT_PROMPT = "" # TODO: add context prompt