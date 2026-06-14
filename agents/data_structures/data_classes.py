from dataclasses import dataclass


@dataclass
class PatchingTask:
    # patcher_id is the id of the agent that will generate the patch (i.e., "basic", "cot", "context")
    patcher_id: str
    # message is the prompt
    message: str
    # Optional context summary from context retrieval agent
    context_summary: str = ""
    # Patching attempt number (1, 2, 3, etc.) - used for context retrieval attempt numbering
    patching_attempt: int = 1

@dataclass
class PatchingResponse:
    # patcher_id is the id of the agent that generated the patch
    patcher_id: str
    # result is the agent response
    result: str
    # mapping is the mapping of modified_source_name -> (patch_file_path, patched_nodes)
    mapping: dict[str, tuple[str, list[str]]]

@dataclass
class TestingTask:
    # patcher_id is the id of the PatchingAgent whose patch is being tested (i.e., "basic", "cot")
    patcher_id: str
    # mapping is the mapping of modified_source_name -> (patch_file_path, patched_nodes)
    mapping: dict[str, tuple[str, list[str]]]

@dataclass
class TestingResponse:
    # patcher_id is the id of the PatchingAgent whose patch was tested (i.e., "basic", "cot")
    patcher_id: str
    # success is a bool: True if all tests passed, False if tests failed or didn't run/compile
    success: bool
    # testing result message formatted as a string, used for logging/prompting
    str_result: str
    # testing result message formatted as a list of dicts, used for bm25/rag
    list_result: list[dict[str, str]]

@dataclass
class ContextRetrievalTask:
    # Attempt number (e.g., 1, 2, 3) - each attempt consists of up to 3 rounds internally
    # Used by SummaryAgent to label the summary
    retrieval_attempt: int  # Actually represents attempt number, not round number

@dataclass
# send this response to the summary agent? this agent will format the context nicely into a string
class ContextRetrievalResponse:
    # Attempt number (e.g., 1, 2, 3) - used by SummaryAgent to label the summary
    retrieval_attempt: int  # Note: Represents attempt number, NOT round number
    # function_results is the formatted string of all rounds' context retrieval results for this attempt
    # Contains reasoning and results for each round (from format_current_context)
    function_results: str

@dataclass
class SelectionTask:
    """Task for SelectionAgent to select the best candidate patch from the candidate patches directory."""
    # List of candidate patches
    candidate_patches: list
    # note: we don't have a message here because the prompt is hardcoded in SelectionAgent

@dataclass
class SelectionResponse:
    """Response from SelectionAgent with the best candidate patch, formatted as a string."""
    selected_patch_description: str

@dataclass
class SummaryTask:
    """Task for SummaryAgent to summarize context retrieval results."""
    # Formatted string containing all rounds' results and reasoning for this attempt
    # This is the concatenated output from format_current_context() for each round
    function_results: str  # String with reasoning and results for all rounds
    # Attempt number (e.g., 1, 2, 3) - each attempt consists of up to 3 rounds
    retrieval_attempt: int  # Actually represents attempt number, not round number
    # message is the prompt
    message: str

@dataclass
class SummaryResponse:
    """Response from SummaryAgent with formatted summary."""
    summary: str  # Formatted summary string

@dataclass
class FunctionCall:
    """FunctionCall object returned by LLM when it decides to call a function."""
    name: str
    arguments: dict | str = ""  # Can be dict (for testing) or JSON string (from API)
    
    def get_arguments_dict(self) -> dict:
        """Get arguments as a dict, parsing JSON string if needed."""
        import json
        if isinstance(self.arguments, str):
            return json.loads(self.arguments) if self.arguments else {}
        return self.arguments