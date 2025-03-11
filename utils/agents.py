import os
import json
from openai import OpenAI
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Union
from tqdm import tqdm 
from .nlp_utils import chunk_transcript_by_time

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

class AgentPipeline:
    def __init__(self, agents_dir: Optional[str] = None):
        """
        Initialize the AgentPipeline with processing and summarizing agents.
        
        Args:
            agents_dir: Directory containing agent prompt files
        """
        self.agents = {'processing': [], 'summarizing': []}
        self.data = {}  # Will store results per transcript
        self.summaries = {}  # Will store summaries per transcript
        self.total_cost = 0.0
        
        # Load agents if directory is provided
        if agents_dir and os.path.exists(agents_dir):
            self._load_agents_from_directory(agents_dir)
    
    def _load_agents_from_directory(self, agents_dir: str):
        """
        Load agents from prompt files in a directory.
        Prompt files with 'summary' in the name become ChatAgents for summarizing.
        All other prompt files become JsonicAgents for processing.
        """
        for filename in os.listdir(agents_dir):
            path = os.path.join(agents_dir, filename)
            if not os.path.isfile(path):
                continue
                
            with open(path, 'r') as f:
                prompt = f.read()
            
            agent_name = filename.split('.')[0]
            
            if 'summary' in filename.lower():
                self.agents['summarizing'].append(
                    ChatAgent(name=agent_name, system_prompt=prompt)
                )
            else:
                self.agents['processing'].append(
                    JsonicAgent(name=agent_name, system_prompt=prompt)
                )
        
        print(f"Loaded {len(self.agents['processing'])} processing agents and "
              f"{len(self.agents['summarizing'])} summarizing agents")
    
    def add_agent(self, agent, agent_type='processing'):
        """
        Add an agent to the pipeline.
        
        Args:
            agent: The agent to add (JsonicAgent or ChatAgent)
            agent_type: Either 'processing' or 'summarizing'
        """
        if agent_type not in self.agents:
            raise ValueError("agent_type must be 'processing' or 'summarizing'")
        
        self.agents[agent_type].append(agent)
    
    def process_transcript(self,
                           transcript_path: str,
                           parallel: bool = True,
                           verbose: bool = True):
        """
        Process a single transcript through the pipeline.
        
        Args:
            transcript_path: Path to the transcript file
            parallel: Whether to process chunks in parallel
            verbose: Whether to return the processed data
            
        Returns:
            Dictionary containing processing results and summary if verbose=True
        """
        
        transcript_name = os.path.basename(transcript_path)
        
        try:
            with open(transcript_path, 'r') as f:
                transcript = json.load(f)
        except json.JSONDecodeError:
            print(f"Error: Could not parse JSON from {transcript_path}")
            return None
        except FileNotFoundError:
            print(f"Error: File not found: {transcript_path}")
            return None
        
        chunks = chunk_transcript_by_time(transcript)
        
        # Initialize transcript in data store
        self.data[transcript_name] = {
            'text': transcript.get('text', ''),
            'chunks': chunks,
            'processing_results': {},
            'summary': None,
            'token_costs': 0.0
        }
        
        # Initialize each agent's data for this transcript
        for agent in self.agents['processing']:
            agent.data = {}
            agent.token_cost = 0
        
        # Process chunks with processing agents (parallel or sequential)
        if parallel and len(chunks) > 1:
            self._parallel_process_chunks(transcript_name, chunks)
        else:
            self._sequential_process_chunks(transcript_name, chunks)
        
        transcript_cost = 0.0
        # Consolidate results from each agent
        for agent in self.agents['processing']:
            # Remove duplicates from each agent's data values
            clean_data = {k: list(set(v)) for k, v in agent.data.items()}
            self.data[transcript_name]['processing_results'][agent.name] = clean_data
            transcript_cost += agent.get_cost()
        
        self.data[transcript_name]['token_costs'] = transcript_cost
        self.total_cost += transcript_cost
        
        # Generate a consolidated text from all agent results
        consolidated_text = self._consolidate_agent_results(transcript_name)
        
        # Generate summary if summarizing agents exist
        if self.agents['summarizing']:
            summary = self._generate_summary(consolidated_text)
            self.data[transcript_name]['summary'] = summary
            self.summaries[transcript_name] = summary

            summary_cost = 0.0
            for agent in self.agents['summarizing']:
                summary_cost += agent.get_cost()
                
            self.data[transcript_name]['token_costs'] += summary_cost
            self.total_cost += summary_cost
        
        if verbose:
            return self.data[transcript_name]
    
    def _parallel_process_chunks(self, transcript_name: str, chunks: List[str]):
        """Process chunks in parallel using ThreadPoolExecutor"""
        print(f"Processing {len(chunks)} chunks in parallel for {transcript_name}...")
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for chunk in chunks:
                for agent in self.agents['processing']:
                    futures.append(executor.submit(agent, chunk))
            
            # Show progress bar for processing
            for future in tqdm(concurrent.futures.as_completed(futures), 
                              total=len(futures),
                              desc="Processing chunks"):
                # Each future returns the agent's response; we don't need to do anything with it
                # as the agents store their results internally
                pass
    
    def _sequential_process_chunks(self, transcript_name: str, chunks: List[str]):
        """Process chunks sequentially"""
        print(f"Processing {len(chunks)} chunks sequentially for {transcript_name}...")
        
        for i, chunk in enumerate(chunks):
            print(f"Processing chunk {i+1}/{len(chunks)}")
            for agent in self.agents['processing']:
                agent(chunk)
    
    def _consolidate_agent_results(self, transcript_name: str) -> str:
        """
        Consolidate results from all processing agents into a text format
        that can be used for summarization.
        """
        consolidated_text = f"Transcript: {transcript_name}\n\n"
        
        for agent_name, agent_data in self.data[transcript_name]['processing_results'].items():
            consolidated_text += f"{agent_name}:\n{json.dumps(agent_data, indent=2)}\n\n"
        
        return consolidated_text
    
    def _generate_summary(self, consolidated_text: str) -> str:
        """Generate a summary from the consolidated text using summarizing agents"""
        summary = ""
        
        for agent in self.agents['summarizing']:
            agent.token_cost = 0  # Reset cost before processing
            agent_summary = agent(consolidated_text)
            summary += f"{agent.name} Summary:\n{agent_summary}\n\n"
        
        return summary
    
    def process_all_transcripts(self, transcript_paths: List[str], 
                               parallel_transcripts: bool = False,
                               parallel_chunks: bool = True,
                               verbose: bool = True):
        """
        Process multiple transcripts through the pipeline.
        
        Args:
            transcript_paths: List of paths to transcript files
            parallel_transcripts: Whether to process transcripts in parallel
            parallel_chunks: Whether to process chunks within a transcript in parallel
            verbose: Whether to print progress information
            
        Returns:
            Dict of all processed data
        """

        if parallel_transcripts and len(transcript_paths) > 1:
            Warning("Parallel processing of transcripts is not yet supported. ")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(self.process_transcript, path, parallel_chunks, False): path
                    for path in transcript_paths
                }
                
                for future in tqdm(concurrent.futures.as_completed(futures),
                                  total=len(futures),
                                  desc="Processing transcripts"):
                    transcript_path = futures[future]
                    try:
                        future.result()  # Get result to catch any exceptions
                        if verbose:
                            print(f"Completed processing {os.path.basename(transcript_path)}")
                    except Exception as e:
                        print(f"Error processing transcript {transcript_path}: {e}")
        else:
            for path in tqdm(transcript_paths, desc="Processing transcripts"):
                try:
                    self.process_transcript(path, parallel_chunks, False)
                    if verbose:
                        print(f"Completed processing {os.path.basename(path)}")
                except Exception as e:
                    print(f"Error processing transcript {path}: {e}")
        
        if verbose:
            return self.data
    
    def get_summaries(self) -> Dict[str, str]:
        """Get all transcript summaries."""
        return self.summaries
    
    def get_total_cost(self) -> float:
        """Get the total token cost for all processing."""
        return self.total_cost
    
    def get_cost_report(self) -> str:
        """Get a formatted cost report."""
        return f"Total Token Cost for all processing: ${self.total_cost:.6f}"
        
    def save_summaries(self, output_dir: str, parallel: bool = False):
        """
        Save individual summary files for each transcript with token costs included.
        
        Args:
            output_dir: Directory to save summary files to
            parallel: Whether to save summaries in parallel
        """
        os.makedirs(output_dir, exist_ok=True)
        
        def save_single_summary(transcript_name, summary):
            # Get the summary text
            summary_text = summary
            
            # Get the token cost for this transcript
            token_cost = self.data[transcript_name].get('token_costs', 0)
            
            # Add the token cost to the bottom of the summary
            summary_with_cost = f"{summary_text}\n\n{'='*50}\nToken Cost: ${token_cost:.6f}"
            
            # Save to file
            output_path = os.path.join(output_dir, f"{transcript_name}_summary.txt")
            with open(output_path, 'w') as f:
                f.write(summary_with_cost)
            
            return output_path
        
        # Save summaries either in parallel or sequentially
        if parallel and len(self.summaries) > 1:
            print(f"Saving {len(self.summaries)} summaries in parallel...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(save_single_summary, transcript_name, summary): transcript_name
                    for transcript_name, summary in self.summaries.items()
                }
                
                saved_paths = []
                for future in tqdm(concurrent.futures.as_completed(futures), 
                                  total=len(futures),
                                  desc="Saving summaries"):
                    transcript_name = futures[future]
                    try:
                        saved_path = future.result()
                        saved_paths.append(saved_path)
                    except Exception as e:
                        print(f"Error saving summary for {transcript_name}: {e}")
                
                print(f"Saved {len(saved_paths)} summaries to {output_dir}")
        else:
            print(f"Saving {len(self.summaries)} summaries sequentially...")
            saved_paths = []
            for transcript_name, summary in tqdm(self.summaries.items(), desc="Saving summaries"):
                try:
                    saved_path = save_single_summary(transcript_name, summary)
                    saved_paths.append(saved_path)
                except Exception as e:
                    print(f"Error saving summary for {transcript_name}: {e}")
            
            print(f"Saved {len(saved_paths)} summaries to {output_dir}")

