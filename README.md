# Classic Car Analysis Pipeline
An AI-powered pipeline for analyzing classic car videos, extracting detailed information, and generating comprehensive summaries.

## Project Overview
This system processes videos of classic cars (typically dealer walkarounds), extracts audio and visual information, and uses AI to generate detailed reports on each vehicle. The pipeline uses speech-to-text transcription and a multi-agent approach to identify key vehicle attributes including:

- Make, model, and year
- Vehicle condition details
- Maintenance and service history
- Accident history and repairs
- Noteworthy features and options

## System Architecture
The project consists of two main pipelines:

1. Video Processing Pipeline - Extracts audio, performs transcription, and captures key frames
2. Text Summarization Pipeline - Analyzes transcripts with specialized AI agents to extract relevant details

### Pipeline Flow
```
Car Video → Video Processing → Transcription → Agent Analysis → Summary Generation
```

## Getting Started
### Prerequisites
- Python 3.12+
- OpenAI API key
- FFmpeg installed on your system
- Required Python libraries (see requirements.txt)

### Installation

1. Clone the repository:
```
Copygit clone https://github.com/yourusername/classic-car-analysis.git
cd classic-car-analysis
```

2. Install the required packages:
```
pip install -r requirements.txt
```

3. Set up your OpenAI API key:
```
# For macOS/Linux
vim ~/.zshrc
# Add the following line:
export OPENAI_KEY="your-api-key-here"
# Save and exit (type ":wq")
source ~/.zshrc
```

4. Prepare your data directory structure:
```
mkdir -p data/videos
mkdir -p data/processed_videos
mkdir -p results
```

## Usage
### Processing Videos
The system processes videos in two stages:

1. Video Processing: Extracts audio, transcribes speech, and captures frames

```
#python
from utils import VideoProcessingPipeline

# Initialize the pipeline
pipeline = VideoProcessingPipeline(
    model_size="medium",
    extract_frames_interval=5,
    output_dir='data/processed_videos'
)

# Process a single video
result = pipeline.process_video('data/videos/example.mp4')

# Or batch process multiple videos
video_paths = ['data/videos/car1.mp4', 'data/videos/car2.mp4']
results = pipeline.batch_process(video_paths)
```

2. Text Analysis: Analyzes transcripts and generates summaries

```
#python
from utils import AgentPipeline

# Initialize the agent pipeline
agent_pipe = AgentPipeline(agents_dir='agent_prompts/')

# Process a single transcript
agent_pipe.process_transcript('data/processed_videos/transcripts/example.json')

# Or process multiple transcripts
transcript_paths = [
    'data/processed_videos/transcripts/car1.json',
    'data/processed_videos/transcripts/car2.json'
]
agent_pipe.process_all_transcripts(transcript_paths)

# Save the generated summaries
agent_pipe.save_summaries(output_dir='results/')

```
### Example Notebooks
The project includes two main Jupyter notebooks that demonstrate the complete workflow:

1. video_processing_pipeline.ipynb - Processes videos, extracts audio, and generates transcripts
2. summarize_text_pipeline.ipynb - Analyzes transcripts and generates vehicle summaries

## System Components
### Video Processing Pipeline
The VideoProcessingPipeline class handles:

- Audio extraction from video
- Speech-to-text transcription using Whisper
- Subtitle generation and video captioning
- Key frame extraction at specified intervals

### Agent Pipeline
The AgentPipeline class manages specialized AI agents that:

- Process transcript segments to extract relevant information
- Identify vehicle details from spoken content
- Generate comprehensive summaries

### Key Utilities

- agents.py - Defines the agent classes and interactions
- nlp_utils.py - Provides text processing utilities
- video_classes.py - Defines data structures for video processing

### Cost Monitoring
The system tracks token usage and API costs to help monitor expenses:
```
# Get cost report
print(agent_pipe.get_cost_report())
```

## Future Development

- Pricing model integration
- Bidding recommendation system
- Dealer guidance for video capture
- Enhanced visual analysis of vehicle condition
- VIN and CarFax API calls

## Project Structure
```
├── agent_prompts/            # System prompts for specialized AI agents
├── data/
│   ├── videos/               # Input car videos
│   └── processed_videos/     # Processed outputs (transcripts, frames, etc.)
├── notebooks/
│   ├── summarize_text_pipeline.ipynb
│   └── video_processing_pipeline.ipynb
├── results/                  # Generated summaries
├── utils/
│   ├── __init__.py
│   ├── agents.py             # Agent definitions and pipeline
│   ├── nlp_utils.py          # NLP utility functions
│   ├── video_classes.py      # Data models
│   └── video_pipeline.py     # Video processing pipeline
└── requirements.txt
```
