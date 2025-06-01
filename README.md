# Unicourt Case Processor API

This FastAPI application serves as a backend to automate the processing of Unicourt case information, including searching for cases, downloading "Final Judgment" PDF documents, and extracting creditor information using an LLM.

## Features

-   **Case Submission:** Submit case numbers for processing via API.
-   **Automated Unicourt Interaction:** Handles login, session management, case searching, and navigation.
-   **PDF Downloading:** Downloads "Final Judgment" PDFs associated with cases.
-   **LLM Integration:** Extracts creditor information from downloaded PDFs using OpenRouter.ai.
-   **Database Storage:** Persists case data, document metadata, and extracted information in an SQLite database.
-   **Status Tracking:** Provides API endpoints to check the status of submitted cases and individual documents.
-   **Dynamic Configuration:** Allows certain operational parameters (e.g., Unicourt credentials, download location, LLM model, selectors) to be updated via API through a `config.json` file.
-   **Controlled Restarts:** Supports API-triggered graceful shutdowns, relying on an external wrapper script for automatic restarts to apply configuration changes.
-   **Secure API:** Uses API key authentication for sensitive endpoints.

## Project Structure

```
.
├── app/                  # Main application code
│   ├── api/              # API routers and dependencies
│   ├── core/             # Core logic (config, security, lifespan)
│   ├── db/               # Database (models, CRUD, session, init)
│   ├── models_api/       # Pydantic models for API req/res
│   ├── services/         # Business logic services
│   ├── utils/            # Utility functions
│   ├── workers/          # Background worker logic
│   └── main.py           # FastAPI app instantiation
├── config.json.example   # Example user-configurable settings
├── .env.example          # Example environment variables for secrets/server settings
├── .gitignore
├── Dockerfile            # For containerizing the application
├── requirements.txt
├── README.md
└── run_server.sh         # Wrapper script for running and restarting the server
```

## Setup

1.  **Prerequisites:**
    *   Python 3.9+
    *   `pip` for installing Python packages.
    *   `jq` command-line JSON processor (for the `run_server.sh` script). Install via your system's package manager (e.g., `sudo apt-get install jq` on Debian/Ubuntu).
    *   (If using Docker) Docker installed.

2.  **Clone the repository (if applicable):**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

3.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

4.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Install Playwright browsers:**
    ```bash
    playwright install chromium # Or playwright install --with-deps chromium
    ```

6.  **Configure Environment Variables:**
    Copy `.env.example` to `.env` and fill in the required values:
    ```bash
    cp .env.example .env
    # Edit .env with your details (PORT, API_ACCESS_KEY, DATABASE_FILENAME, LOG_LEVEL)
    ```
    *   `API_ACCESS_KEY`: A strong, secret key for authenticating API requests.

7.  **Configure Application Settings (`config.json`):**
    Copy `config.json.example` to `config.json`.
    ```bash
    cp config.json.example config.json
    ```
    Edit `config.json` with your Unicourt credentials, OpenRouter API key, desired download locations, LLM model, and any selector overrides if needed.
    *   `CURRENT_DOWNLOAD_LOCATION` and `REQUESTED_DOWNLOAD_LOCATION` should initially be the same.
    *   The `DATABASE_FILENAME` from `.env` will be placed inside `CURRENT_DOWNLOAD_LOCATION`.

8.  **Make the wrapper script executable:**
    ```bash
    chmod +x run_server.sh
    ```

## Running the Application

Use the wrapper script to start the server. This script also handles automatic restarts and pre-startup tasks like renaming the download directory if configured.

```bash
./run_server.sh
```

The API will be available at `http://<HOST>:<PORT>` (e.g., `http://0.0.0.0:8000` by default).
API documentation (Swagger UI) will be at `http://<HOST>:<PORT>/api/v1/openapi.json` (raw spec) or typically `http://<HOST>:<PORT>/docs` for the interactive UI.

## API Endpoints

All endpoints are prefixed with `/api/v1`. Authentication is required for most endpoints using the `X-API-KEY` header.

**Health:**
*   `GET /healthz`: Service health check.

**Cases:**
*   `POST /cases/submit`: Submit one or more case numbers for processing.
    *   Payload: `CaseSubmitRequest` (list of cases with `case_number` and `reprocess_all_pdfs` flag).
*   `GET /cases/{case_number}/status`: Get detailed status and data for a specific case.
*   `GET /cases/{case_number}/pdfs/{document_id_or_filename}`: Download a processed PDF file. `document_id_or_filename` can be the database ID of the document or its sanitized filename.

**Service Control:**
*   `GET /service/status`: Get the overall status of the service (queue size, active tasks, etc.). (Secured)
*   `GET /service/config`: Retrieve the current `config.json` content. (Secured)
*   `PUT /service/config`: Update `config.json`. Most changes require a server restart. (Secured)
    *   Payload: `ConfigUpdateRequest`
*   `POST /service/request-restart`: Request a graceful server shutdown. The `run_server.sh` script will then restart it. (Secured)

## Configuration Updates

1.  Use the `PUT /api/v1/service/config` endpoint to send new configuration values.
2.  The server will update `config.json`.
3.  If significant changes are made (e.g., credentials, `MAX_CONCURRENT_TASKS`, `REQUESTED_DOWNLOAD_LOCATION`), the API response will indicate that a restart is required.
4.  Use the `POST /api/v1/service/request-restart` endpoint to initiate a graceful shutdown.
5.  The `run_server.sh` script will:
    *   Detect if `REQUESTED_DOWNLOAD_LOCATION` differs from `CURRENT_DOWNLOAD_LOCATION` in `config.json`.
    *   If so, it will attempt to rename the directory.
    *   Then, it will update `CURRENT_DOWNLOAD_LOCATION` in `config.json` to match `REQUESTED_DOWNLOAD_LOCATION`.
    *   Finally, it will restart the Python application, which will then use the new settings.

## Docker (Optional)

A `Dockerfile` is provided for containerizing the application.

1.  **Build the Docker image:**
    ```bash
    docker build -t unicourt-processor .
    ```

2.  **Run the Docker container:**
    You'll need to manage `config.json` and the download directory (which includes the SQLite DB) using Docker volumes to persist data.
    Create `config.json` and an empty `unicourt_downloads` (or your configured name) directory on your host machine.
    ```bash
    # Create on host first
    # mkdir host_unicourt_downloads
    # cp config.json.example host_config.json
    # # Edit host_config.json
    
    docker run -d \
        --name unicourt-app \
        -p 8000:8000 \
        -v $(pwd)/host_config.json:/app/config.json \
        -v $(pwd)/host_unicourt_downloads:/app/unicourt_downloads_from_config \ # Match REQUESTED_DOWNLOAD_LOCATION
        -e API_ACCESS_KEY="your_strong_secret_api_key_here" \
        -e PORT="8000" \
        -e DATABASE_FILENAME="app_data.db" \
        # Add other .env vars as needed
        unicourt-processor
    ```
    *   **Note on Docker and `run_server.sh`:** The `run_server.sh` script's restart and directory rename logic is designed for a non-containerized environment where it directly manages the Python process. In Docker, the `CMD` in the Dockerfile typically runs the Uvicorn server directly. For config updates requiring directory renames and process restarts within Docker, you'd typically:
        1.  Update `config.json` on the host (mounted volume).
        2.  Stop the container.
        3.  Manually rename the host directory if `DOWNLOAD_LOCATION` changed.
        4.  Start a new container, or restart the existing one. The new container will pick up the updated `config.json` and use the (potentially renamed) volume.
        The API-triggered restart that relies on `sys.exit()` and `run_server.sh` might not behave as expected without further adaptation for Docker's process management (e.g., using a supervisor within the container or relying on Docker's restart policies). For simplicity, the Docker `CMD` is set to run `python app/main.py`.

## Logging

Logs are printed to standard output. The log level can be configured via the `LOG_LEVEL` environment variable in `.env`. Debug screenshots from Playwright errors are saved in a `debug_screenshots` subdirectory within `CURRENT_DOWNLOAD_LOCATION`.

## Development Notes

*   Ensure `jq` is installed for the `run_server.sh` script to function correctly.
*   The application uses an SQLite database, which is a single file (`app_data.db` by default) located within the `CURRENT_DOWNLOAD_LOCATION`.
*   Playwright browser contexts are created and destroyed per case processing task to ensure isolation, using a shared authenticated session state.