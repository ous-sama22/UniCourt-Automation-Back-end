# UniCourt Automation Backend API - V4

A comprehensive FastAPI-based backend service for automating UniCourt case processing, document extraction, and data analysis using Playwright automation and AI-powered document processing.

## 🔗 Related Rep#### Check Case Status

```bash
curl -X GET "http://localhost:8000/api/v1/cases/CASE-001/status" \
     -H "X-API-Key: your_api_key"
```

#### Get Batch Case Details

```bash
curl -X POST "http://localhost:8000/api/v1/cases/batch-details" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{
       "case_numbers_for_db_id": ["CASE-001", "CASE-002", "CASE-003"]
     }'
```

#### Update Configuration

```bash
curl -X PUT "http://localhost:8000/api/v1/service/config" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{
       "OPENROUTER_LLM_MODEL": "anthropic/claude-3-sonnet",
       "EXTRACT_ASSOCIATED_PARTY_ADDRESSES": true
     }'
```

#### Check Service Status

```bash
curl -X GET "http://localhost:8000/api/v1/service/status" \
     -H "X-API-Key: your_api_key"
```ies

- **Frontend Repository**: [Unicourt_Automation_Front-End](https://github.com/ous-sama22/Unicourt_Automation_Front-End) - Google Apps Script-based frontend interface for Google Sheets integration
- **This Repository**: [UniCourtAutomationBack-end---V4](https://github.com/ous-sama22/UniCourtAutomationBack-end---V4) - Backend API service

## 🌐 Quick Links

- **📊 API Documentation**: When running locally, visit [http://localhost:8000/docs](http://localhost:8000/docs) for interactive Swagger UI
- **📖 ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc) for alternative API documentation
- **🩺 Health Check**: [http://localhost:8000/api/v1/healthz](http://localhost:8000/api/v1/healthz) for service status
- **🔧 OpenAPI JSON**: [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json) for schema export

## 📋 Table of Contents

- [🌐 Quick Links](#-quick-links)
- [✨ Features](#-features)
- [🏗️ Architecture](#️-architecture)
- [🚀 Installation](#-installation)
- [⚙️ Configuration](#️-configuration)
- [📚 API Documentation](#-api-documentation)
- [📖 Usage](#-usage)
- [🛠️ Development](#️-development)
- [🐳 Docker Deployment](#-docker-deployment)
- [🐛 Troubleshooting](#-troubleshooting)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [🆘 Support](#-support)

## ✨ Features

### Core Functionality
- **Automated UniCourt Navigation**: Playwright-powered browser automation for UniCourt.com
- **Case Processing Pipeline**: Asynchronous case processing with queue management
- **Document Analysis**: AI-powered document extraction using OpenRouter LLM models
- **Data Extraction**: Creditor information, party details, final judgment analysis
- **RESTful API**: Comprehensive REST API for case management and status tracking
- **Google Sheets Integration**: Seamless integration with Google Apps Script frontend

### Technical Features
- **Async Processing**: Background workers with configurable concurrency
- **Database Integration**: SQLAlchemy with SQLite for data persistence
- **Session Management**: Persistent UniCourt login sessions
- **Error Handling**: Comprehensive error handling and retry mechanisms
- **Health Monitoring**: Health check endpoints for service monitoring
- **Configuration Management**: Dynamic configuration updates without restart
- **Frontend API**: Dedicated endpoints for Google Sheets frontend integration

### Integration Features
- **Frontend Compatibility**: Full compatibility with Google Apps Script frontend
- **Batch Processing**: Efficient batch operations for multiple case processing
- **Real-time Status**: Live status updates for frontend monitoring
- **Configuration Sync**: Dynamic configuration updates from frontend interface

## 🏗️ Architecture

```
├── app/
│   ├── api/                    # API layer
│   │   ├── routers/           # FastAPI routers
│   │   │   ├── cases.py       # Case management endpoints
│   │   │   ├── health.py      # Health check endpoints
│   │   │   └── service_control.py  # Service control endpoints
│   │   └── deps.py            # Dependency injection
│   ├── core/                  # Core configuration
│   │   ├── config.py          # Application settings
│   │   ├── lifespan.py        # Application lifecycle
│   │   └── security.py        # Security utilities
│   ├── db/                    # Database layer
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── crud.py            # Database operations
│   │   └── session.py         # Database session
│   ├── models_api/            # API models
│   │   ├── cases.py           # Case-related models
│   │   └── service.py         # Service-related models
│   ├── services/              # Business logic
│   │   ├── case_processor.py  # Main case processing logic
│   │   ├── unicourt_handler.py # UniCourt automation
│   │   ├── llm_processor.py   # AI document processing
│   │   └── config_manager.py  # Configuration management
│   ├── utils/                 # Utilities
│   │   ├── common.py          # Common utilities
│   │   └── playwright_utils.py # Playwright helpers
│   └── workers/               # Background workers
│       └── case_worker.py     # Case processing worker
├── tests/                     # Test suite
├── unicourt_downloads/        # Data storage
├── config.json                # Client configuration
├── requirements.txt           # Python dependencies
└── Dockerfile                 # Container configuration
```

## 🚀 Installation

### Prerequisites

- Python 3.11+
- UniCourt.com account with valid credentials
- OpenRouter API key for LLM processing

### Local Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/ous-sama22/UniCourtAutomationBack-end---V4.git
   cd UniCourtAutomationBack-end---V4
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers**
   ```bash
   playwright install chromium
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

6. **Configure client settings**
   ```bash
   cp config.json.example config.json
   # Edit config.json with your UniCourt and OpenRouter credentials
   ```

7. **Run the application**
   ```bash
   python app/main.py
   ```

## ⚙️ Configuration

### Environment Variables (.env)

Create a `.env` file in the root directory. See `.env.example` for all available options.

**Required Variables:**
- `API_ACCESS_KEY`: API access key for authentication
- `PORT`: Server port (default: 8000)
- `HOST`: Server host (default: 0.0.0.0)

### Client Configuration (config.json)

The `config.json` file contains client-specific credentials and settings that can be updated dynamically through the API or frontend interface.

**Required Settings:**
```json
{
    "UNICOURT_EMAIL": "your_unicourt_email@example.com",
    "UNICOURT_PASSWORD": "your_unicourt_password",
    "OPENROUTER_API_KEY": "your_openrouter_api_key",
    "OPENROUTER_LLM_MODEL": "anthropic/claude-3-haiku",
    "EXTRACT_ASSOCIATED_PARTY_ADDRESSES": true
}
```

**Available LLM Models:**
- `anthropic/claude-3-haiku` (Fast, cost-effective)
- `anthropic/claude-3-sonnet` (Balanced performance)
- `anthropic/claude-3-opus` (Highest quality)
- `google/gemini-2.0-flash-001` (Google's latest)
- `meta-llama/llama-3.1-70b-instruct` (Open source)

**Configuration Updates:**
- Can be updated through the frontend interface
- Can be updated via API: `PUT /api/v1/service/config`
- Changes take effect immediately without restart
- Credentials are validated on update

## 📚 API Documentation

### Base URL
- Development: `http://localhost:8000`
- Production: Your deployed URL

### Authentication
All API endpoints require the `X-API-Key` header with your configured API access key.

### Available Endpoints

#### Health Check
- `GET /api/v1/healthz` - Service health status and readiness check

#### Case Management
- `POST /api/v1/cases/submit` - Submit cases for processing (requires write access)
- `POST /api/v1/cases/batch-status` - Get batch case statuses (requires read access)
- `POST /api/v1/cases/batch-details` - Get batch case details (requires read access)
- `GET /api/v1/cases` - Get all cases (requires read access)
- `GET /api/v1/cases/{case_number}/status` - Get individual case status (requires read access)

#### Service Control
- `GET /api/v1/service/status` - Get detailed service status (requires write access)
- `GET /api/v1/service/config` - Get current client configuration (requires write access)
- `PUT /api/v1/service/config` - Update client configuration (requires write access)
- `POST /api/v1/service/request-restart` - Request service restart (requires write access)

#### Interactive Documentation
- `GET /docs` - Swagger UI for interactive API testing
- `GET /redoc` - ReDoc alternative documentation interface
- `GET /api/v1/openapi.json` - OpenAPI 3.0 specification in JSON format

### OpenAPI Documentation
When the service is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

## 📖 Usage

### Frontend Integration (Recommended)

The easiest way to use this backend is through the Google Apps Script frontend:

1. **Set up the frontend**: Follow the installation guide in the [Frontend Repository](https://github.com/ous-sama22/Unicourt_Automation_Front-End)
2. **Configure connection**: In Google Sheets, use the UniCourt Processor menu to configure your backend URL and API key
3. **Manage cases**: Use the intuitive Google Sheets interface for case management and monitoring

### Direct API Usage

#### Submit Cases for Processing

```bash
curl -X POST "http://localhost:8000/api/v1/cases/submit" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{
       "cases": [
         {
           "case_number_for_db_id": "CASE-001",
           "case_name_for_search": "John Doe vs ABC Corp",
           "input_creditor_name": "ABC Corp",
           "is_business": true,
           "creditor_type": "business"
         }
       ]
     }'
```

### Check Case Status

```bash
curl -X GET "http://localhost:8000/api/v1/cases/CASE-001/status" \
     -H "X-API-Key: your_api_key"
```

### Monitor Service Health

```bash
curl -X GET "http://localhost:8000/api/v1/healthz"
```

**Response Examples:**

Healthy service:
```json
{
  "status": "healthy",
  "message": "Service is ready, Unicourt session active, and Playwright is initialized."
}
```

Service issues:
```json
{
  "status": "degraded",
  "message": "Playwright initialized, but service not fully ready (e.g., Unicourt session failed)."
}
```

## 🔧 Monitoring and Maintenance

### Health Monitoring

The service provides comprehensive health checks:
- **Service readiness**: Backend initialization status
- **UniCourt session**: Login session validity
- **Playwright status**: Browser automation readiness
- **Queue status**: Processing queue health
- **Database connectivity**: SQLite database access

### Log Monitoring

Monitor these log patterns for issues:
- `CRITICAL ERROR initializing AppSettings`: Configuration problems
- `Health check: Playwright not initialized`: Browser automation issues
- `UniCourt session failed`: Authentication or site access problems
- `LLM processing failed`: Document analysis issues

### Performance Monitoring

Key metrics to monitor:
- **Queue size**: `GET /api/v1/service/status` → `current_queue_size`
- **Active tasks**: `active_processing_tasks_count`
- **Processing time**: Monitor case completion times
- **Error rates**: Check error logs for failure patterns

### Maintenance Tasks

#### Regular Maintenance
- **Session refresh**: UniCourt sessions expire periodically
- **Log rotation**: Monitor log file sizes and rotate as needed
- **Database cleanup**: Archive old case data periodically
- **Security updates**: Keep dependencies updated

#### Troubleshooting Commands
```bash
# Check service health
curl -X GET "http://localhost:8000/api/v1/healthz"

# Get detailed service status
curl -X GET "http://localhost:8000/api/v1/service/status" -H "X-API-Key: your_api_key"

# Request service restart
curl -X POST "http://localhost:8000/api/v1/service/request-restart" -H "X-API-Key: your_api_key"

# Check current configuration
curl -X GET "http://localhost:8000/api/v1/service/config" -H "X-API-Key: your_api_key"
```

## 🛠️ Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run specific test file
pytest tests/test_unicourt_handler_integration.py

# Run with verbose output
pytest -v
```

### Code Structure

- **FastAPI Application**: `app/main.py`
- **Configuration**: `app/core/config.py`
- **Database Models**: `app/db/models.py`
- **API Routes**: `app/api/routers/`
- **Business Logic**: `app/services/`
- **Background Workers**: `app/workers/`

### Adding New Features

1. Create new API models in `app/models_api/`
2. Add database models in `app/db/models.py`
3. Implement business logic in `app/services/`
4. Create API endpoints in `app/api/routers/`
5. Add tests in `tests/`

## 🐳 Docker Deployment

### Build and Run

```bash
# Build the image
docker build -t unicourt-automation-backend .

# Run the container
docker run -d \
  --name unicourt-backend \
  -p 8000:8000 \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/unicourt_downloads:/app/unicourt_downloads \
  -e API_ACCESS_KEY=your_api_key \
  unicourt-automation-backend
```

### Docker Compose

```yaml
version: '3.8'
services:
  unicourt-backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config.json:/app/config.json
      - ./unicourt_downloads:/app/unicourt_downloads
    environment:
      - API_ACCESS_KEY=your_api_key
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

## 🐛 Troubleshooting

### Common Issues

#### Service Not Ready
- **Issue**: `/healthz` returns "service not ready"
- **Solution**: Check UniCourt credentials in `config.json`

#### Playwright Browser Issues
- **Issue**: Browser automation fails
- **Solution**: Run `playwright install chromium`

#### Database Errors
- **Issue**: SQLite database errors
- **Solution**: Ensure `unicourt_downloads` directory is writable

#### LLM Processing Failures
- **Issue**: Document analysis fails
- **Solution**: Verify OpenRouter API key and model availability

### Logs and Debugging

- Check application logs for detailed error information
- Set `LOG_LEVEL=DEBUG` in `.env` for verbose logging
- Screenshots are saved to `unicourt_downloads/playwright_screenshots/`

### Performance Tuning

- Adjust `MAX_CONCURRENT_TASKS` based on your system resources
- Monitor memory usage during large batch processing
- Consider increasing timeout values for slow networks

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write comprehensive tests for new features
- Update documentation for API changes
- Use meaningful commit messages

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.