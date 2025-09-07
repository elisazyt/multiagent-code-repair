import logging
import sys
import os
from openai import OpenAI

from typing import List
import openai

class GPTClient:
    def __init__(self):
        self.api_key = None
    
    def initialize_agent(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not found in environment variables")
        self.client = OpenAI(api_key=self.api_key)

    def send_prompt(self, prompt):
        client = OpenAI(api_key=self.api_key)
        
        gpt_model = os.environ.get("GPT_MODEL", "gpt-4-turbo-2024-04-09")
        response = client.chat.completions.create(model=gpt_model,
        messages=[{"role": "user", "content": prompt}])
        
        return response

    def receive_response(self, response):
        content = response.choices[0].message.content if response and hasattr(response, 'choices') else None
            
        return content
    
    def send_prompt_with_functions(self, prompt, functions):
        """Send a prompt with function calling enabled"""
        gpt_model = os.environ.get("GPT_MODEL", "gpt-4-turbo-2024-04-09")
        
        response = self.client.chat.completions.create(
            model=gpt_model,
            messages=[{"role": "user", "content": prompt}],
            functions=functions,
            function_call="auto"  # Let AI decide whether to call functions
        )
        
        return response