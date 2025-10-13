# ClippyFront

A Flask-based web application with Celery for background task processing.

## Features

- Flask web framework with REST API
- Celery for asynchronous task processing
- Redis as message broker and result backend
- Comprehensive testing with pytest
- Code formatting with Black
- Linting with Ruff
- Pre-commit hooks for code quality
- GitHub Actions CI/CD pipeline
- Docker support (planned)

## Setup

### Prerequisites

- Python 3.10+
- Redis server

### Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd ClippyFront
```

2. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy environment configuration:
```bash
cp .env.example .env
```

5. Start Redis server:
```bash
# On Ubuntu/Debian
sudo systemctl start redis-server

# Or using Docker
docker run -d -p 6379:6379 redis:7-alpine
```

6. Install pre-commit hooks:
```bash
pre-commit install
```

## Running the Application

### Start the Flask application:
```bash
python main.py
```

### Start Celery worker (in another terminal):
```bash
source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info
```

### Start Celery monitoring (optional):
```bash
source venv/bin/activate
celery -A app.tasks.celery_app flower
```

## API Endpoints

- `GET /api/health` - Health check
- `POST /api/tasks/start` - Start background task
- `GET /api/tasks/<task_id>` - Get task status

## Development

### Running Tests
```bash
pytest
```

### Code Formatting
```bash
black .
```

### Linting
```bash
ruff check .
```

### Coverage Report
```bash
pytest --cov=app --cov-report=html
```

## Project Structure

```
ClippyFront/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py        # API endpoints
│   └── tasks/
│       ├── __init__.py
│       ├── celery_app.py    # Celery configuration
│       └── background_tasks.py # Celery tasks
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuration settings
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Test configuration
│   └── test_api.py          # API tests
├── .github/
│   └── workflows/
│       └── ci.yml           # GitHub Actions CI/CD
├── main.py                  # Application entry point
├── celery_worker.py         # Celery worker startup
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Tool configurations
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore patterns
├── .pre-commit-config.yaml # Pre-commit hooks
└── README.md               # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and ensure all checks pass
5. Submit a pull request

## License

[Add your license here]
