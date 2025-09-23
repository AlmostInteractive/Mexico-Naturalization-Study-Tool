# Mexico Study Guide

An adaptive learning quiz application for Mexican history and culture, featuring AI-generated distractors and spaced repetition learning algorithms.

## Features

- **Adaptive Learning**: Questions are weighted based on your performance using exponential decay algorithms
- **Progressive Chunking**: Unlock new questions as you master previous ones (80% success rate required)
- **AI-Generated Distractors**: Contextually appropriate wrong answers using local LLM (Ollama)
- **Text-to-Speech**: Spanish audio for questions and answers
- **Progress Tracking**: Detailed statistics and learning progress monitoring
- **Spaced Repetition**: Questions you struggle with appear more frequently

## Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Ollama (for AI distractor generation)

1. Download and install Ollama from [https://ollama.ai/](https://ollama.ai/)
2. Download a language model:
   ```bash
   ollama pull llama3.2
   ```
3. Verify Ollama is running:
   ```bash
   curl http://localhost:11434/api/tags
   ```

### 3. Prepare Your Questions

Create a CSV file with your questions in this format:

```csv
Question,Answer
"¿Cuál es la capital de México?","Ciudad de México"
"¿En qué año fue la Independencia?","1810"
"¿Qué civilización construyó Teotihuacán?","Teotihuacanos"
```

#### CSV Formatting Requirements

- **Header Row**: Must include exactly `Question,Answer` as the first line
- **Encoding**: Save file as UTF-8 to properly handle Spanish characters (ñ, á, é, í, ó, ú, ü)
- **Quotes**: Wrap both questions and answers in double quotes to handle commas and special characters
- **No Empty Rows**: Remove any blank lines between questions
- **Content Guidelines**:
  - Questions should be clear and specific
  - Answers should be concise but complete
  - Use proper Spanish spelling and accents
  - Avoid very short answers (less than 3 characters) as they may not generate good distractors


Issues with the poor example:
- Wrong header format (lowercase, different names)
- Missing quotes around answers
- Inconsistent language mixing
- Abbreviations that are unclear
- Missing quotes and malformed CSV structure

## Usage

### Import Questions

Use the complete workflow to generate AI distractors and import to database:

```bash
python setup_questions.py your_questions.csv
```

**Options:**
- `--model MODEL` - Change LLM model (default: llama3.2)
- `--subject "SUBJECT"` - Change subject context (default: "Mexican history and culture")
- `--batch-size N` - Questions per LLM request (default: 1, max: 3)
- `--keep-distractors` - Keep the intermediate CSV file with distractors

**Examples:**
```bash
python setup_questions.py data/history.csv
python setup_questions.py data/culture.csv --model mistral --subject "Mexican Culture"
python setup_questions.py data/questions.csv --keep-distractors --batch-size 2
```

### Run the Quiz

```bash
python app.py
```

Open your browser to [http://localhost:5000](http://localhost:5000)

### Reset Progress

To start over and clear all learning statistics:

```bash
python reset_progress.py
```

## Manual Workflow (Advanced)

If you prefer to run each step separately:

### 1. Generate Distractors Only

```bash
python create_distractors.py your_questions.csv
```

This creates `your_questions_distractors.csv` with 8 AI-generated wrong answers per question.

### 2. Import to Database

```bash
python import_distractors.py your_questions_distractors.csv
```

### 3. Check Database Status

```bash
python import_distractors.py --status
```

## How It Works

### Learning Algorithm

- **Initial Weight**: New questions start with maximum weight (10.0)
- **Success Rate Tracking**: Each question tracks success percentage
- **Confidence Building**: Statistical confidence improves over 3+ attempts
- **Exponential Decay**: Poor performance exponentially increases question weight
- **Progressive Unlocking**: Master current chunk (80% success) to unlock next 10 questions

### AI Distractor Generation

- Uses local LLM (Ollama) to generate contextually appropriate wrong answers
- **Retry Logic**: Makes second attempt for failed questions
- **Intelligent Parsing**: Extracts distractors from various response formats
- **Fallback System**: Uses static distractors if AI generation fails
- **No API Keys**: Completely free and offline after initial setup

### Text-to-Speech

- **Spanish Voice Priority**: Prefers es-MX, es-US, then any Spanish voice
- **Configurable Speed**: Lenta (0.7x), Normal (1.0x), Rápida (1.2x)
- **Auto-advancement**: Proceeds to next question after audio completes
- **Toggle Control**: Enable/disable audio in top menu

## Project Structure

```
Mexico Study Guide/
├── app.py                   # Main Flask application
├── create_distractors.py    # AI distractor generator
├── import_distractors.py    # Database import tool
├── setup_questions.py       # Complete workflow, runs both create_ and import_distractors
├── reset_progress.py        # Progress reset utility
├── requirements.txt         # Python dependencies
├── quiz.db                  # SQLite database
└── templates/
    └── index.html           # Quiz interface
```

## Database Schema

- **questions**: Question text, correct answers, distractors, chunk assignments
- **question_stats**: Performance tracking (attempts, success rate, weight)
- **user_progress**: Current chunk and learning progress

## Configuration

The learning algorithm can be customized by editing constants in `app.py`:

```python
MAX_SUCCESS_RATE_CAP = 0.95    # Maximum success rate for weight calculation
CONFIDENCE_THRESHOLD = 3       # Attempts needed for statistical confidence
```

## Troubleshooting

### Ollama Issues

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama (Windows)
ollama serve

# Pull a different model
ollama pull mistral
```

### Audio Issues

- **Chrome**: Usually works with Spanish voices automatically
- **Firefox**: May need manual Spanish voice installation (do you know how? Leave me a comment)
- **No Audio**: Check browser permissions and enable audio in menu

### Database Issues

```bash
# Reset everything and start fresh
python reset_progress.py

# Check current status
python import_distractors.py --status
```

## License

Open source project for educational use.