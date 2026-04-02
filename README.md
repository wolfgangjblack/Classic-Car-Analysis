# Classic Car Analysis Pipeline

An AI-powered pipeline for analyzing classic car videos, extracting detailed information, and generating comprehensive summaries.

## Project Overview

This system processes videos of classic cars (typically dealer walkarounds), extracts audio and visual information, and uses AI to generate detailed reports on each vehicle. The pipeline uses speech-to-text transcription and a multi-agent approach to identify key vehicle attributes including:

- Make, model, and year
- Vehicle condition details
- Maintenance and service history
- Accident history and repairs
- Noteworthy features and options

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   FastAPI       │────▶│   Background    │
│   (HTML/JS)     │     │   Backend       │     │   Workers       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │                        │
                               ▼                        ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │   SQLite DB     │     │   Video/Agent   │
                        │   (Jobs)        │     │   Processing    │
                        └─────────────────┘     └─────────────────┘
```

## Quick Start

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/wolfgangjblack/Classic-Car-Analysis.git
cd Classic-Car-Analysis
```

2. Create your `.env` file:
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

3. Start the services:
```bash
docker-compose up --build
```

4. Access the application:
   - Frontend: http://localhost:3000
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Manual Installation

1. Install system dependencies:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg
```

2. Install Python dependencies:
```bash
cd backend
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export OPENAI_API_KEY="your-api-key-here"
```

4. Run the API server:
```bash
cd backend
uvicorn app.main:app --reload
```

## Usage

### Web Interface

1. Open http://localhost:3000 in your browser
2. Either drag-and-drop a video file or enter a YouTube URL
3. Wait for processing to complete
4. View the generated summary

### CLI

The CLI provides direct access to all processing functionality:

```bash
cd backend

# Process a local video file
python -m cli.main process /path/to/video.mp4

# Process with custom output directory
python -m cli.main process video.mp4 --output ./my-output

# Download and process a YouTube video
python -m cli.main download "https://youtube.com/watch?v=..."

# Generate summary from existing transcript
python -m cli.main summarize /path/to/transcript.json

# List available transcripts
python -m cli.main list-transcripts

# Show configuration
python -m cli.main config
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/videos/upload` | Upload a video file |
| POST | `/api/videos/url` | Submit a YouTube/video URL |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Get job status and details |
| GET | `/api/jobs/{id}/summary` | Get job summary |
| DELETE | `/api/jobs/{id}` | Delete/cancel a job |
| GET | `/api/costs` | Get cost report |
| GET | `/health` | Health check |

## Project Structure

```
classic-car-analysis/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI route handlers
│   │   ├── core/             # Core processing logic
│   │   │   ├── agents.py     # AI agent definitions
│   │   │   ├── nlp_utils.py  # NLP utilities
│   │   │   ├── valuation.py  # Market value lookup & bid calculation
│   │   │   ├── video_classes.py  # Data models
│   │   │   ├── video_pipeline.py # Video processing
│   │   │   └── vision_analyzer.py # GPT-4o frame condition analysis
│   │   ├── models/           # Database & Pydantic schemas
│   │   ├── services/         # Service layer
│   │   ├── workers/          # Background task handlers
│   │   ├── config.py         # Configuration
│   │   └── main.py           # FastAPI application
│   ├── cli/                  # Command-line interface
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── nginx.conf
│   └── Dockerfile
├── agent_prompts/            # AI agent system prompts
├── data/                     # Processing data (created at runtime)
├── docker-compose.yml
├── .env.example
└── README.md
```

## Configuration

Configuration is managed through environment variables. See `.env.example` for all available options:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (required) | - |
| `WHISPER_MODEL_SIZE` | Whisper model size | `medium` |
| `FRAME_EXTRACT_INTERVAL` | Seconds between frame extractions | `5` |
| `VISION_MODEL` | OpenAI model for vision analysis | `gpt-4o` |
| `MAX_VISION_FRAMES` | Max frames sent to vision model | `10` |
| `MAX_UPLOAD_SIZE_MB` | Maximum upload file size | `500` |

## AI Agents

The system uses specialized AI agents to extract information:

- **BasicAgent**: Extracts make, model, year, and package information
- **HistoryAgent**: Extracts mileage, owners, accident history, maintenance
- **ConditionAgent**: Extracts exterior, interior, and mechanical condition (from transcript)
- **SummaryAgent**: Generates comprehensive vehicle summaries
- **VisionConditionAgent**: GPT-4o vision analysis of extracted video frames for paint, body, chrome, interior condition scoring (1-5 scale per area)

## Vision Analysis & Market Valuation

After transcript analysis, the pipeline runs two additional phases:

1. **Vision Condition Analysis**: Selects evenly-spaced frames from the video, encodes them as base64, and sends them to GPT-4o for visual inspection. The model rates 8 condition areas (exterior paint, body panels, chrome/trim, wheels/tires, glass, seats, dashboard, carpet/headliner) on a 1-5 scale and produces good/bad observation lists.

2. **Market Valuation**: Uses OpenAI's Responses API with built-in web search to look up current market values from sources like Hagerty, Bring a Trailer, and Hemmings. The condition score is then used to calculate a suggested starting bid range (higher condition = bid closer to market value).

## Cost Tracking

The system tracks API usage costs for each processed video. View costs via:
- Web UI: Displayed in summary cards
- CLI: Shown after processing
- API: `GET /api/costs`

## Development

### Running Tests

```bash
cd backend
pytest
```

### Code Style

```bash
# Format code
black backend/

# Type checking
mypy backend/
```

## Future Development

- [x] Pricing model integration (market valuation via web search)
- [x] Bidding recommendation system (condition-adjusted bid range)
- [x] Enhanced visual analysis of vehicle condition (GPT-4o vision)
- [ ] Dealer guidance for video capture
- [ ] VIN and CarFax API integration
- [ ] Multi-language support

## License

This project is licensed under the terms included in the LICENSE file.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
