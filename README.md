
# GitHub Issue Scraper

A command-line tool to fetch issues from any public GitHub repository and save them as CSV and JSON files.

## Installation

```bash
# Clone this repository
git clone https://github.com/yourusername/github-issue-scraper
cd github-issue-scraper

# Install with uv (uses pyproject.toml)
uv pip install -e .
```

If you don't have uv installed:

```bash
# Install uv
curl -sSf https://astral.sh/uv/install.sh | bash

# Then install the package
uv pip install -e .
```

## Usage

```bash
uv run main.py <repo_url> <max_issues> <require_open>
```

## GitHub API Rate Limits

- Unauthenticated: 60 requests per hour
- With authentication (recommended): 5,000 requests per hour
  ```bash
  export GITHUB_TOKEN=your_github_personal_access_token
  ```
  - You can generate a personal access token from [here](https://github.com/settings/tokens)

### Parameters

- `<repo_url>`: GitHub repository URL (e.g., https://github.com/tensorflow/tensorflow)
- `<max_issues>`: Maximum number of issues to fetch (use 0 for all available)
- `<require_open>`: Set to "true" for only open issues, "false" for all issues

### Examples

```bash
# Fetch 50 open issues from Phoenix repo
uv run main.py https://github.com/Arize-ai/phoenix 50 true

# Fetch 100 issues (both open and closed) from TensorFlow
uv run main.py https://github.com/tensorflow/tensorflow 100 false
```

## Output

- Files saved to `./tmp/` directory
- CSV file for simple viewing/importing to spreadsheets
- JSON file with complete data including comments
- Partial results saved if rate-limited

## GitHub API Rate Limits

- Unauthenticated: 60 requests per hour
- With authentication: 5,000 requests per hour
  ```bash
  export GITHUB_TOKEN=your_github_personal_access_token
  ```

## Features

- Live progress tracking
- Graceful rate limit handling
- Error recovery with partial data saving
- Full issue comments in JSON output
