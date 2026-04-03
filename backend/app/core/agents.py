import concurrent.futures
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from openai import OpenAI
from tqdm import tqdm

from .nlp_utils import chunk_transcript_by_time
from .retry import openai_retry

logger = logging.getLogger(__name__)


class Agent(ABC):
    def __init__(
        self,
        system_prompt: str,
        llm: str = "gpt-4o-mini",
        temperature: float = 0.0,
        client: Optional[OpenAI] = None,
    ):
        self.system_prompt = system_prompt
        self.token_cost = 0.0
        self.temperature = temperature
        self.llm = llm
        self._client = client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            from ..deps import get_openai_client
            self._client = get_openai_client()
        return self._client

    @abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        """Execute the agent's primary function."""
        pass

    def describe(self) -> str:
        return (
            f"{self.__class__.__name__}\n"
            f"  LLM: {self.llm}\n"
            f"  Prompt: {self.system_prompt[:120]}...\n"
        )

    def get_cost(self):
        return self.token_cost

    @openai_retry
    def _call_openai_json(
        self,
        messages,
        max_tokens=400,
        temperature=0.3,
        input_cost=0.15 / 1e6,
        output_cost=0.60 / 1e6,
    ):
        """Call the OpenAI Chat Completion API requesting JSON output."""
        completion = self.client.chat.completions.create(
            model=self.llm,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        cost = (
            completion.usage.prompt_tokens * input_cost
            + completion.usage.completion_tokens * output_cost
        )
        return completion.choices[0].message.content.strip(), cost

    @openai_retry
    def _call_openai_chat(
        self,
        messages,
        max_tokens=400,
        temperature=0.3,
        input_cost=0.15 / 1e6,
        output_cost=0.60 / 1e6,
    ):
        """Call the OpenAI Chat Completion API."""
        completion = self.client.chat.completions.create(
            model=self.llm,
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
    def __init__(
        self,
        system_prompt: Optional[str] = None,
        name: Optional[str] = None,
        data: Optional[Dict] = None,
        client: Optional[OpenAI] = None,
    ):
        super().__init__(system_prompt=system_prompt, client=client)
        self.name = name
        self.data = data or {}
        self.token_cost = 0
        self._lock = threading.Lock()

    def __call__(self, text):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]

        response, cost = self._call_openai_json(messages, temperature=self.temperature)
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from agent %s: %s", self.name, response[:200])
            return {}

        with self._lock:
            for k, v in response.items():
                if v is not None:
                    if k in self.data and self.data[k] is not None:
                        self.data[k].append(v)
                    else:
                        self.data[k] = [v]
            self.token_cost += cost

        return response


class ChatAgent(Agent):
    def __init__(
        self,
        system_prompt: Optional[str] = None,
        name: Optional[str] = None,
        data: Optional[Dict] = None,
        client: Optional[OpenAI] = None,
    ):
        super().__init__(system_prompt=system_prompt, client=client)
        self.name = name
        self.data = data or {}
        self.token_cost = 0

    def __call__(self, text):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]

        response, cost = self._call_openai_chat(messages, temperature=self.temperature)
        self.token_cost += cost
        return response


class AgentPipeline:
    def __init__(self, agents_dir: Optional[str] = None, client: Optional[OpenAI] = None):
        """
        Initialize the AgentPipeline with processing and summarizing agents.

        Args:
            agents_dir: Directory containing agent prompt files
            client: Shared OpenAI client (falls back to deps.get_openai_client)
        """
        self.agents = {'processing': [], 'summarizing': []}
        self.data = {}
        self.summaries = {}
        self.total_cost = 0.0
        self._client = client

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

            if not prompt.strip():
                continue

            agent_name = filename.split('.')[0]

            if 'summary' in filename.lower():
                self.agents['summarizing'].append(
                    ChatAgent(name=agent_name, system_prompt=prompt, client=self._client)
                )
            else:
                self.agents['processing'].append(
                    JsonicAgent(name=agent_name, system_prompt=prompt, client=self._client)
                )

        logger.info("Loaded %d processing agents and %d summarizing agents",
                    len(self.agents['processing']), len(self.agents['summarizing']))

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

    def process_transcript(
        self,
        transcript_path: str,
        parallel: bool = True,
        return_results: bool = True,
        progress_callback=None
    ):
        """
        Process a single transcript through the pipeline.

        Args:
            transcript_path: Path to the transcript file
            parallel: Whether to process chunks in parallel
            return_results: Whether to return the processed data dict
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary containing processing results and summary if return_results=True
        """
        transcript_name = os.path.basename(transcript_path)

        try:
            with open(transcript_path, 'r') as f:
                transcript = json.load(f)
        except json.JSONDecodeError:
            logger.error("Could not parse JSON from %s", transcript_path)
            return None
        except FileNotFoundError:
            logger.error("File not found: %s", transcript_path)
            return None

        chunks = chunk_transcript_by_time(transcript)

        self.data[transcript_name] = {
            'text': transcript.get('text', ''),
            'chunks': chunks,
            'processing_results': {},
            'summary': None,
            'token_costs': 0.0
        }

        for agent in self.agents['processing']:
            agent.data = {}
            agent.token_cost = 0

        if progress_callback:
            progress_callback("processing_chunks", 10)

        if parallel and len(chunks) > 1:
            self._parallel_process_chunks(transcript_name, chunks)
        else:
            self._sequential_process_chunks(transcript_name, chunks)

        transcript_cost = 0.0
        for agent in self.agents['processing']:
            clean_data = {}
            for k, v in agent.data.items():
                try:
                    clean_data[k] = list(set(v))
                except TypeError:
                    seen = []
                    for item in v:
                        if item not in seen:
                            seen.append(item)
                    clean_data[k] = seen
            self.data[transcript_name]['processing_results'][agent.name] = clean_data
            transcript_cost += agent.get_cost()

        self.data[transcript_name]['token_costs'] = transcript_cost
        self.total_cost += transcript_cost

        consolidated_text = self._consolidate_agent_results(transcript_name)

        if progress_callback:
            progress_callback("generating_summary", 80)

        if self.agents['summarizing']:
            summary = self._generate_summary(consolidated_text)
            self.data[transcript_name]['summary'] = summary
            self.summaries[transcript_name] = summary

            summary_cost = 0.0
            for agent in self.agents['summarizing']:
                summary_cost += agent.get_cost()

            self.data[transcript_name]['token_costs'] += summary_cost
            self.total_cost += summary_cost

        if progress_callback:
            progress_callback("complete", 100)

        if return_results:
            return self.data[transcript_name]

    def _parallel_process_chunks(self, transcript_name: str, chunks: List[str]):
        """Process chunks in parallel using ThreadPoolExecutor"""
        logger.info("Processing %d chunks in parallel for %s", len(chunks), transcript_name)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for chunk in chunks:
                for agent in self.agents['processing']:
                    futures.append(executor.submit(agent, chunk))

            for future in tqdm(
                concurrent.futures.as_completed(futures),
                total=len(futures),
                desc="Processing chunks"
            ):
                pass

    def _sequential_process_chunks(self, transcript_name: str, chunks: List[str]):
        """Process chunks sequentially"""
        logger.info("Processing %d chunks sequentially for %s", len(chunks), transcript_name)

        for i, chunk in enumerate(chunks):
            logger.debug("Processing chunk %d/%d", i + 1, len(chunks))
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
            agent.token_cost = 0
            agent_summary = agent(consolidated_text)
            summary += f"{agent.name} Summary:\n{agent_summary}\n\n"

        return summary

    def process_all_transcripts(
        self,
        transcript_paths: List[str],
        parallel_transcripts: bool = False,
        parallel_chunks: bool = True,
        return_results: bool = True
    ):
        """
        Process multiple transcripts through the pipeline.

        Args:
            transcript_paths: List of paths to transcript files
            parallel_transcripts: Whether to process transcripts in parallel
            parallel_chunks: Whether to process chunks within a transcript in parallel
            return_results: Whether to return the processed data dict

        Returns:
            Dict of all processed data if return_results=True
        """
        if parallel_transcripts and len(transcript_paths) > 1:
            logger.warning("Parallel processing of transcripts is experimental")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(self.process_transcript, path, parallel_chunks, False): path
                    for path in transcript_paths
                }

                for future in tqdm(
                    concurrent.futures.as_completed(futures),
                    total=len(futures),
                    desc="Processing transcripts"
                ):
                    transcript_path = futures[future]
                    try:
                        future.result()
                        if return_results:
                            logger.info("Completed processing %s", os.path.basename(transcript_path))
                    except Exception as e:
                        logger.error("Error processing transcript %s: %s", transcript_path, e)
        else:
            for path in tqdm(transcript_paths, desc="Processing transcripts"):
                try:
                    self.process_transcript(path, parallel_chunks, False)
                    if return_results:
                        logger.info("Completed processing %s", os.path.basename(path))
                except Exception as e:
                    logger.error("Error processing transcript %s: %s", path, e)

        if return_results:
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
            summary_text = summary
            token_cost = self.data[transcript_name].get('token_costs', 0)
            summary_with_cost = f"{summary_text}\n\n{'='*50}\nToken Cost: ${token_cost:.6f}"

            output_path = os.path.join(output_dir, f"{transcript_name}_summary.txt")
            with open(output_path, 'w') as f:
                f.write(summary_with_cost)

            return output_path

        if parallel and len(self.summaries) > 1:
            logger.info("Saving %d summaries in parallel", len(self.summaries))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(save_single_summary, transcript_name, summary): transcript_name
                    for transcript_name, summary in self.summaries.items()
                }

                saved_paths = []
                for future in tqdm(
                    concurrent.futures.as_completed(futures),
                    total=len(futures),
                    desc="Saving summaries"
                ):
                    transcript_name = futures[future]
                    try:
                        saved_path = future.result()
                        saved_paths.append(saved_path)
                    except Exception as e:
                        logger.error("Error saving summary for %s: %s", transcript_name, e)

                logger.info("Saved %d summaries to %s", len(saved_paths), output_dir)
        else:
            logger.info("Saving %d summaries sequentially", len(self.summaries))
            saved_paths = []
            for transcript_name, summary in tqdm(self.summaries.items(), desc="Saving summaries"):
                try:
                    saved_path = save_single_summary(transcript_name, summary)
                    saved_paths.append(saved_path)
                except Exception as e:
                    logger.error("Error saving summary for %s: %s", transcript_name, e)

            logger.info("Saved %d summaries to %s", len(saved_paths), output_dir)
