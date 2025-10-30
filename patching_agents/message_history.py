from pprint import pformat
import os

# Partially taken from autocoderover

class MessageHistory:
    """
    Represents a thread of conversation with the model.
    Abstrated into a class so that we can dump this to a file at any point.
    """

    def __init__(self, history_file_directory: str, project_name: str):
        self.messages = []
        
        # Create project-specific message file inside the specified directory
        filename = f"{project_name}_messages.txt"
        self.history_file = os.path.join(history_file_directory, filename)
    

    def update_history_file(self):
        """Write current message history to file, removing redundant message history portions"""
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        
        with open(self.history_file, 'w') as f:
            for message in self.messages:
                content = message['content']
                
                # Replace message history portion with placeholder to avoid redundancy
                if "For reference, here is the past message history:" in content:
                    # Check if this is already the "no previous message history" text BEFORE splitting
                    if "This is the first message in the conversation thread, no previous message history is available. Proceed with your task, ignoring this message." in content:
                        # Keep the original content as-is
                        pass
                    else:
                        content = content.split("For reference, here is the past message history:")[0].strip()
                        content += "\n\nFor reference, here is the past message history: {message_history}"
                
                if message["role"] == "system":
                    f.write(f"SYSTEM INSTRUCTIONS: {content}\n\n")
                elif message["role"] == "prompt":
                    f.write(f"PROMPT:\n{content}\n\n")
                else:
                    f.write(f"AGENT RESPONSE:\n{content}\n\n")
    
    def get_messages(self) -> list[dict]:
        """
        Get the messages in the thread.
        Returns:
            List[Dict]: The message thread.
        """
        return self.messages
    
    def add_system_message(self, message: str):
        """
        Add a new system message to the thread.
        Args:
            message (str): The content of the new system message.
        """
        self.messages.append({"role": "system", "content": message})
    
    def add_prompt(self, role: str, message: str):
        """
        Add a new prompt to the thread.
        Args:
            message (str): The content of the new prompt.
        """
        self.messages.append({"role": "prompt", "content": message})
        self.update_history_file()

    def add_agent(self, agent_role: str, message: str):
        """
        Add a new agent response to the thread.
        Args:
            message (str): The content of the new message.
            role (str): The role of the agent giving the message.
        """
        self.messages.append({"role": agent_role, "content": message})
        self.update_history_file()
    
    def add_message_history(self, new_msg_history):
        """
        Add a new message history to the thread.
        Args:
            new_msg_history (MessageHistory): The message history to add.
        """
        self.messages.extend(new_msg_history.get_messages())

    # TODO: incorporate this later
    def get_round_number(self) -> int:
        """
        From the current message history, decide how many rounds have been completed.
        """
        completed_rounds = 0
        for message in self.messages:
            if message["role"] == "prompt":
                completed_rounds += 1
        return completed_rounds

    def format_history(self) -> str:
        """Read from the clean history file"""
        try:
            with open(self.history_file, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""

    def __str__(self):
        """Called when printing the message history"""
        return self.format_history()