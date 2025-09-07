from typing import List, Tuple
from message_history import MessageHistory

class InfoDict:
    def __init__(self):
        self.info_dict = {}

    def create_info_dict(self, agent_role: str, agent_task: str, bug_locations: List[Tuple[str, List[Tuple[int, int]]]], message_history: MessageHistory):
        self.add_info("agent role", agent_role)
        self.add_info("agent task", agent_task)
        self.add_info("bug files and locations", bug_locations)
        self.add_info("message history", message_history)

    def add_info(self, info_type, info):
        self.info_dict[info_type] = info

    def get_info(self, info_type):
        return self.info_dict[info_type]
    
    def get_message_history(self):
        return self.info_dict["message history"]

