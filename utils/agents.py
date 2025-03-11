import os
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

class Agent(ABC):
    def __init__(
        self, system_prompt: str, llm: str = "gpt-3.5-turbo", temperature: float = 0.0
    ):
        self.system_prompt = system_prompt
        self.token_cost = 0.0
        self.temperature = temperature
        self.llm = llm

    @abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        """
        Execute the agent's primary function
        """
        pass

    def describe(self) -> str:
        return f"{self.__class__.__name__}\n llm: {self.llm} -Note: Only GPT support atm \n Agentic Prompt:{self.system_prompt}\n"

    def get_cost(self):
        return self.token_cost

    @staticmethod
    def gpt_jsonic(
        messages,
        max_tokens=400,
        temperature=0.3,
        input_cost=0.5 / 1e6,
        output_cost=1.5 / 1e6,
    ):
        """Calls the OpenAI Chat Completion API with the provided messages."""
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type":"json_object"},
        )

        cost = (
            completion.usage.prompt_tokens * input_cost
            + completion.usage.completion_tokens * output_cost
        )
        return completion.choices[0].message.content.strip(), cost
    
    @staticmethod
    def chat_with_gpt(
        messages,
        max_tokens=400,
        temperature=0.3,
        input_cost=0.5 / 1e6,
        output_cost=1.5 / 1e6,
    ):
        """Calls the OpenAI Chat Completion API with the provided messages."""
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        cost = (
            completion.usage.prompt_tokens * input_cost
            + completion.usage.completion_tokens * output_cost
        )
        return completion.choices[0].message.content.strip(), cost

    
class JsonicAgent(Agent):
    def __init__(self,
                 system_prompt: str = None,
                 name: Optional[str] = None,
                 data: Optional[Dict] = None):
        super().__init__(
            system_prompt= system_prompt)
        self.name = name
        self.data = data or {}
        self.token_cost = 0
        
    def __call__(self, text):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]

        response, cost = self.gpt_jsonic(messages, temperature = self.temperature)
        try:
            response = json.loads(response)
        except Exception as e:
            return e

        for k, v in response.items():
           if v is not None:
                if k in self.data and self.data[k] is not None:
                   self.data[k].append(v)
                else:
                    self.data[k] = [v]
        self.token_cost += cost

        return response
    
class ChatAgent(Agent):
    def __init__(self,
                 system_prompt: str = None,
                 name: Optional[str] = None,
                 data: Optional[Dict] = None):
        super().__init__(system_prompt=system_prompt)
        self.name = name
        self.data = data or {}
        self.token_cost = 0
    
    def __call__(self, text):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]

        response, cost = self.chat_with_gpt(messages, temperature = self.temperature)
        self.token_cost += cost
        return response
    