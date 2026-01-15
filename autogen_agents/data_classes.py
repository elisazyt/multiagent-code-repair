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
    response: str
    # TODO: add patch directory to send to testing agent

@dataclass
class TestingTask:
    # patcher_id is the id of the PatchingAgent whose patch is being tested (i.e., "basic", "cot")
    patcher_id: str
    # message is the prompt for the testing agent
    message: str

@dataclass
class TestingResponse:
    # patcher_id is the id of the PatchingAgent whose patch was tested (i.e., "basic", "cot")
    patcher_id: str
    # success is a boolean indicating if the test ran successfully
    # 0 if test failed, 1 if test passed, 2 if test didn't run/compile
    success: int
    # result is the testing result if the test ran successfully
    result: str