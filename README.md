# CodeSight — Backend

The Spring Boot REST API for CodeSight. Handles authentication, organizations, projects, codebase ingestion, and orchestrates the Python analysis engine.

## Tech Stack

- **Java 21**
- **Spring Boot 3.4** (Web, Security, Data JPA, Mail, Validation)
- **PostgreSQL**
- **JWT** (jjwt 0.12)
- **JGit** — GitHub repository cloning
- **Apache Commons Compress** — ZIP/archive extraction
- **Lombok**
- **Maven**

## Prerequisites

- Java 21+
- Maven 3.9+
- PostgreSQL (local or hosted, e.g. Neon)
- Python analysis engine running on port `8000` (see [`python_analyzer/README.md`](python_analyzer/README.md))
- A Gmail account (or any SMTP provider) for email verification

## Getting Started

### 1. Configure environment

The app loads secrets from `src/main/resources/secret/.env`. Create that file:

```bash
mkdir -p src/main/resources/secret
touch src/main/resources/secret/.env
```

Add the following to `.env`:

```properties
DB_URL=jdbc:postgresql://localhost:5432/codesight
DB_USERNAME=your_db_user
DB_PASSWORD=your_db_password

JWT_SECRET=your_very_long_random_secret_key

MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_gmail_app_password
```

> For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833), not your account password.

### 2. (Optional) Update analysis output path

In `src/main/resources/application.properties`, update this path to an absolute directory where analysis results will be stored:

```properties
codesight.analysis.output-dir=/your/path/to/analysis/output
```

### 3. Run the application

```bash
./mvnw spring-boot:run
```

Or on Windows:

```bash
mvnw.cmd spring-boot:run
```

The API will be available at `http://localhost:8081`.

## Project Structure

```
src/main/java/com/codesight/codesight/
├── app/
│   ├── auth/               # Registration, login, email verification, password reset
│   ├── organization/       # Organization CRUD and membership
│   ├── project/            # Projects, codebase upload, analysis orchestration
│   └── user/               # User profile
├── common/
│   ├── config/             # App-wide Spring beans
│   ├── exception/          # Global exception handling
│   └── utils/              # Shared utilities
└── config/                 # HTTP client config
```

## API Overview

All endpoints are prefixed with `/api`.

| Group | Base Path | Description |
|-------|-----------|-------------|
| Auth | `/api/auth` | Register, login, verify email, forgot/reset password |
| Users | `/api/users` | Get profile, get user by ID |
| Organizations | `/api/organizations` | Create, list, get organization |
| Projects | `/api/organizations/{orgId}/projects` | Create, list, get, delete project |
| Project Members | `/api/organizations/{orgId}/projects/{projectId}/members` | Invite, list, update role, remove |
| Codebase Upload | `/api/organizations/{orgId}/projects/{projectId}/upload` | Upload ZIP, local folder, or GitHub repo |

Postman collections are available in the [`postman/collections/`](postman/collections/) directory.

## How Analysis Works

1. User uploads a codebase (ZIP, folder, or GitHub URL)
2. Spring Boot extracts and stores the files under `./storage/codebases/`
3. Spring Boot calls `POST /analyze` on the Python engine with the path
4. The Python engine parses the AST, builds a dependency graph, and clusters modules
5. Results (`graph_blueprint.json`) are saved and served back to the frontend

## Configuration Reference

| Property | Default | Description |
|----------|---------|-------------|
| `server.port` | `8081` | API server port |
| `app.frontend.url` | `http://localhost:3000` | Allowed CORS origin |
| `codesight.python-analyzer.base-url` | `http://localhost:8000` | Python engine URL |
| `codesight.storage.root` | `./storage/codebases` | Codebase file storage path |
| `app.jwt.expiration` | `86400000` | JWT TTL in ms (24 hours) |

## Python Analysis Engine

The analysis engine is a separate FastAPI microservice in [`python_analyzer/`](python_analyzer/). It must be running before any codebase analysis can take place. See its [README](python_analyzer/README.md) for setup instructions.
