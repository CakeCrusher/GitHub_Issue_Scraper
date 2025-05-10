#!/usr/bin/env python3
"""
Fetch issues from any public GitHub repo and save as CSV and JSON.

Usage:
    python main.py <repo_url> <max_issues> <require_open>

Arguments:
    <repo_url>      GitHub repository URL (https://github.com/owner/repo)
    <max_issues>    Maximum number of issues to fetch (use 0 for all)
    <require_open>  Set to "true" for only open issues, "false" for all issues

Examples:
    python main.py https://github.com/Arize-ai/phoenix 50 true
    python main.py https://github.com/tensorflow/tensorflow 100 false

Requires: 
    requests, tqdm (pip install requests tqdm)

Optional: 
    Set GITHUB_TOKEN env var for higher rate limits.

Output:
    - CSV and JSON files saved to ./tmp/
    - CSV summary printed to stdout
    - If rate limit is hit, partial results are saved

Notes:
    - Will automatically handle GitHub API rate limits
    - Comments are included in JSON output but not in CSV
"""
import os, sys, csv, re, requests, json, time
from urllib.parse import urlparse
from tqdm import tqdm

def slug_from_url(url: str):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)?", url)
    if not m:
        raise ValueError("Expect URL like https://github.com/OWNER/REPO")
    return m.group(1), m.group(2)

def fetch_issues(owner, repo, state="open", per_page=100, max_issues=None, require_open=True):
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    params = {"state": state, "per_page": per_page, "page": 1}
    
    # Try to get total count for progress bar, handle errors gracefully
    try:
        r = requests.get(url, headers=headers, params={"state": state, "per_page": 1}, timeout=30)
        r.raise_for_status()
        
        # Parse Link header to get total pages/count if available
        if 'Link' in r.headers and 'last' in r.headers.get('Link'):
            link_header = r.headers.get('Link')
            total_pages = int(re.search(r'page=(\d+)>; rel="last"', link_header).group(1))
            total_count = total_pages * per_page  # Approximate
        else:
            # If no pagination info, use a reasonable default
            total_count = 100
            
        if max_issues:
            total_count = min(max_issues, total_count)
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not determine total count: {e}", file=sys.stderr)
        total_count = max_issues if max_issues else 100
    
    # Create progress bar
    progress_bar = tqdm(total=total_count, 
                        desc=f"Fetching issues from {owner}/{repo}", 
                        unit="issue")
    
    issues_processed = 0
    max_pages = 1000  # Safety limit to prevent infinite loops
    current_page = 1
    
    # Collection to store fetched issues
    fetched_issues = []
    
    try:
        while current_page <= max_pages:  # Safety limit
            try:
                r = requests.get(url, headers=headers, params=params, timeout=30)
                r.raise_for_status()
                
                # Check rate limit headers
                remaining = int(r.headers.get('X-RateLimit-Remaining', 0))
                reset_time = int(r.headers.get('X-RateLimit-Reset', 0))
                
                if remaining < 10:  # Getting low on requests
                    current_time = time.time()
                    wait_time = reset_time - current_time
                    if wait_time > 0 and wait_time < 3600:  # Less than an hour wait
                        print(f"\nRate limit getting low! Waiting {wait_time:.0f} seconds until reset...", file=sys.stderr)
                        for _ in tqdm(range(int(wait_time)), desc="Waiting for rate limit reset", unit="s"):
                            time.sleep(1)
                    else:
                        print(f"\nWarning: Rate limit almost reached ({remaining} requests left)", file=sys.stderr)
                
                data = r.json()
                if not data:
                    print("\nReached end of available issues.", file=sys.stderr)
                    break
                
                # Check if we have a next page
                has_next_page = False
                if 'Link' in r.headers:
                    link_header = r.headers.get('Link')
                    has_next_page = 'rel="next"' in link_header
                
                rate_limited = False
                for issue in data:
                    # skip PRs (they share the /issues endpoint)
                    if "pull_request" in issue: 
                        continue
                    if require_open and issue["state"] != "open":
                        continue
                        
                    # Check if we've reached the maximum number of issues
                    if max_issues is not None and issues_processed >= max_issues:
                        break
                    
                    # Extract assignee information
                    try:
                        assignee = issue["assignee"]["login"] if issue["assignee"] else "None"
                        assignees = [a["login"] for a in issue["assignees"]] if issue["assignees"] else []
                    except (KeyError, TypeError) as e:
                        print(f"\nWarning: Error parsing assignee for issue #{issue.get('number')}: {e}", file=sys.stderr)
                        assignee = "Error"
                        assignees = []
                    
                    # Update progress bar description to show current issue
                    title_preview = issue.get('title', 'No title')[:30]
                    progress_bar.set_description(f"Fetching issue #{issue.get('number')}: {title_preview}...")
                    
                    # Fetch comments for this issue
                    try:
                        comments_data = fetch_issue_comments(owner, repo, issue["number"], headers)
                    except requests.exceptions.RequestException as e:
                        print(f"\nWarning: Could not fetch comments for issue #{issue.get('number')}: {e}", file=sys.stderr)
                        # Stop the loop
                        rate_limited = True
                        break
                    
                    issues_processed += 1
                    progress_bar.update(1)
                    
                    # Create issue object
                    issue_obj = {
                        "number": issue["number"],
                        "title": issue["title"],
                        "state": issue["state"],
                        "author": issue["user"]["login"],
                        "created_at": issue["created_at"][:10],
                        "updated_at": issue["updated_at"][:10],
                        "closed_at": issue["closed_at"][:10] if issue["closed_at"] else None,
                        "comments": issue["comments"],
                        "assignee": assignee,
                        "assignees": ",".join(assignees),
                        "labels": ",".join(l["name"] for l in issue["labels"]),
                        "reactions_count": issue["reactions"]["total_count"] if "reactions" in issue else 0,
                        "url": issue["html_url"],
                        "body": issue["body"],
                        "comments_data": comments_data
                    }
                    
                    # Both yield and save to our collection
                    fetched_issues.append(issue_obj)
                    yield issue_obj
                    
                    # Check again after processing the issue
                    if max_issues is not None and issues_processed >= max_issues:
                        print(f"\nReached maximum requested issues: {max_issues}", file=sys.stderr)
                        break
                
                # If no next page or we hit the max issues, break the loop
                if not has_next_page or (max_issues is not None and issues_processed >= max_issues):
                    break
                
                if rate_limited:
                    break
                
                # Move to next page
                params["page"] += 1
                current_page += 1
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403 and 'X-RateLimit-Remaining' in e.response.headers and int(e.response.headers['X-RateLimit-Remaining']) == 0:
                    reset_time = int(e.response.headers['X-RateLimit-Reset'])
                    wait_time = reset_time - time.time()
                    print(f"\nRate limit exceeded! Reset in {wait_time:.0f} seconds. Stopping fetch.", file=sys.stderr)
                    print(f"Fetched {issues_processed} issues before hitting rate limit.", file=sys.stderr)
                    break
                else:
                    print(f"\nHTTP error: {e}", file=sys.stderr)
                    break
            except Exception as e:
                print(f"\nUnexpected error: {e}", file=sys.stderr)
                break
    finally:
        progress_bar.close()
        
    # Print summary
    print(f"\nCompleted fetching {issues_processed} issues from {owner}/{repo}", file=sys.stderr)
    return

def fetch_issue_comments(owner, repo, issue_number, headers):
    """Fetch all comments for a specific issue."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        comments = r.json()
        
        # Extract relevant information from each comment
        processed_comments = []
        
        # Use a nested progress bar for comments if there are many
        if len(comments) > 5:
            comment_progress = tqdm(comments, desc=f"  Fetching {len(comments)} comments", leave=False, unit="comment")
            for comment in comment_progress:
                try:
                    processed_comments.append({
                        "id": comment["id"],
                        "user": comment["user"]["login"],
                        "created_at": comment["created_at"],
                        "updated_at": comment["updated_at"],
                        "body": comment["body"],
                        "reactions": comment.get("reactions", {}).get("total_count", 0)
                    })
                except KeyError as e:
                    print(f"\nWarning: Missing key in comment data: {e}", file=sys.stderr)
            comment_progress.close()
        else:
            # For few comments, don't show a progress bar
            for comment in comments:
                try:
                    processed_comments.append({
                        "id": comment["id"],
                        "user": comment["user"]["login"],
                        "created_at": comment["created_at"],
                        "updated_at": comment["updated_at"],
                        "body": comment["body"],
                        "reactions": comment.get("reactions", {}).get("total_count", 0)
                    })
                except KeyError as e:
                    print(f"\nWarning: Missing key in comment data: {e}", file=sys.stderr)
        
        return processed_comments
        
    except requests.exceptions.RequestException as e:
        # Let this propagate up to be handled by the main function
        raise

def main():
    if len(sys.argv) != 4:
        sys.exit("Usage: python main.py <repo_url> <max_issues> <require_open>")
    
    try:
        owner, repo = slug_from_url(sys.argv[1])
        max_issues = int(sys.argv[2])
        require_open = sys.argv[3] == "true"
        
        # Use list() to force the generator to run and collect all issues
        issues = list(fetch_issues(owner, repo, max_issues=max_issues, require_open=require_open))
        
        if not issues:
            print("No issues were fetched. Check your inputs or try again later.", file=sys.stderr)
            sys.exit(1)
        
        # Create directory if it doesn't exist
        os.makedirs("tmp", exist_ok=True)
        
        # Save as CSV
        csv_path = f"tmp/{owner}_{repo}_issues.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=[f for f in issues[0].keys() if f != 'comments_data'])
            writer.writeheader()
            for issue in issues:
                # Create a copy of the issue without the comments_data field for CSV
                csv_issue = {k: v for k, v in issue.items() if k != 'comments_data'}
                writer.writerow(csv_issue)
        
        # Save as JSON
        json_path = f"tmp/{owner}_{repo}_issues.json"
        with open(json_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(issues, jsonfile, indent=4, ensure_ascii=False)
        
        # Also print to stdout for backward compatibility (without comments data)
        writer = csv.DictWriter(sys.stdout, fieldnames=[f for f in issues[0].keys() if f != 'comments_data'])
        writer.writeheader()
        for issue in issues:
            csv_issue = {k: v for k, v in issue.items() if k != 'comments_data'}
            writer.writerow(csv_issue)
        
        print(f"\nFetched {len(issues)} issues from {owner}/{repo}", file=sys.stderr)
        print(f"Saved to {csv_path} and {json_path}", file=sys.stderr)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        # If issues were collected before the error, try to save them
        if 'issues' in locals() and issues:
            try:
                print(f"Attempting to save {len(issues)} issues collected before error...", file=sys.stderr)
                
                # Create directory if it doesn't exist
                os.makedirs("tmp", exist_ok=True)
                
                # Save as JSON
                recovery_path = f"tmp/{owner}_{repo}_issues_recovered.json"
                with open(recovery_path, 'w', encoding='utf-8') as jsonfile:
                    json.dump(issues, jsonfile, indent=4, ensure_ascii=False)
                print(f"Successfully saved partial data to {recovery_path}", file=sys.stderr)
            except Exception as save_error:
                print(f"Failed to save partial data: {save_error}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
