# TODO: transfer InfoDict here and integrate with the current architecture

from dataclasses import dataclass


@dataclass
class PatchingTask:
    # patcher_id is the id of the agent that will generate the patch (i.e., "basic", "cot")
    patcher_id: str
    # message is the prompt
    message: str

@dataclass
class PatchingResponse:
    # patcher_id is the id of the agent that generated the patch
    patcher_id: str
    # result is the agent response
    result: str
    # mapping is the mapping of (modified_source_name, patch_file_path) to send to the testing agent
    mapping: dict[str, str]
    # TODO: add patch directory to send to testing agent

@dataclass
class TestingTask:
    # patcher_id is the id of the PatchingAgent whose patch is being tested (i.e., "basic", "cot")
    patcher_id: str
    # TODO: check to confirm this is true
    # mapping is the mapping of (modified_source_name, patch_file_path)
    mapping: dict[str, str]

@dataclass
class TestingResponse:
    # patcher_id is the id of the PatchingAgent whose patch was tested (i.e., "basic", "cot")
    patcher_id: str
    # success is a bool: True if all tests passed, False if tests failed or didn't run/compile
    success: bool
    # result is the testing result message
    result: str