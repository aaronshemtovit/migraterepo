#!/usr/bin/env python3

import os
import sys
import time
import logging
import requests
import shutil
import stat
from pathlib import Path

from git import Repo, GitCommandError
from dotenv import load_dotenv
import urllib.parse

# ---------------------------------------------------------------------
# Load environment variables from .env file
# ---------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('migration.log', mode='a', encoding='utf-8'),
    ]
)

GITLAB_TOKEN = os.getenv('GITLAB_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

if not GITLAB_TOKEN:
    logging.error("GITLAB_TOKEN not found. Make sure it's set in your .env file or environment.")
    sys.exit(1)

if not GITHUB_TOKEN:
    logging.error("GITHUB_TOKEN not found. Make sure it's set in your .env file or environment.")
    sys.exit(1)

# Base API URLs
GITHUB_API_URL = "https://api.github.com"
GITLAB_API_URL = "https://gitlab.com/api/v4"

# ---------------------------------------------------------------------
# Retry Callback for Windows "Access Denied"
# ---------------------------------------------------------------------

def on_rm_error(func, path, exc_info):
    """
    Error handler for shutil.rmtree to handle locked files on Windows.
    1) Try removing read-only attribute.
    2) Wait briefly.
    3) Retry the original operation.
    If it still fails, we log the exception and re-raise.
    """
    logging.warning(f"on_rm_error called for {path}, error={exc_info[1]}")

    # Remove read-only if it’s set
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception as e:
        logging.warning(f"Could not remove read-only from {path}: {e}")

    # Sleep a bit in case an antivirus or indexer is scanning
    time.sleep(0.5)

    try:
        func(path)
    except Exception as e:
        logging.exception(f"Retry failed to remove {path}: {e}")
        raise  # re-raise the exception so rmtree fails if still locked

# ---------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------

def parse_gitlab_project_path(gitlab_url: str) -> str:
    prefix = "https://gitlab.com/"
    if gitlab_url.startswith(prefix):
        project_path = gitlab_url[len(prefix):]
    else:
        idx = gitlab_url.find("gitlab.com/")
        if idx != -1:
            project_path = gitlab_url[idx + len("gitlab.com/"):]
        else:
            project_path = gitlab_url

    if project_path.endswith(".git"):
        project_path = project_path[:-4]

    return urllib.parse.quote(project_path, safe="")


def get_gitlab_releases(project_path_encoded: str) -> list:
    url = f"{GITLAB_API_URL}/projects/{project_path_encoded}/releases"
    headers = {
        "Private-Token": GITLAB_TOKEN,
        "Accept": "application/json"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        logging.warning(f"Could not fetch GitLab releases: {resp.text}")
        return []


def create_github_repo(repo_name, owner_type, owner_name=None, private=True, description=""):
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    if owner_type.lower() == "org":
        if not owner_name:
            logging.error("No organization name provided for owner_type='org'.")
            return None
        url = f"{GITHUB_API_URL}/orgs/{owner_name}/repos"
    else:
        url = f"{GITHUB_API_URL}/user/repos"

    data = {
        "name": repo_name,
        "private": private,
        "description": description,
        "auto_init": False
    }

    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 201:
        repo_info = response.json()
        logging.info(f"GitHub repository '{repo_name}' created successfully.")
        return repo_info['clone_url']
    else:
        logging.error(f"Failed to create GitHub repo '{repo_name}': {response.text}")
        return None


def create_github_release(owner_type, owner_name, repo_name, tag_name, release_name, body):
    if owner_type.lower() == "org":
        gh_owner = owner_name
    else:
        if owner_name:
            gh_owner = owner_name
        else:
            gh_owner = get_authenticated_username()
            if not gh_owner:
                logging.error("Could not determine GitHub username to create release.")
                return None

    create_url = f"{GITHUB_API_URL}/repos/{gh_owner}/{repo_name}/releases"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }
    data = {
        "tag_name": tag_name,
        "name": release_name,
        "body": body,
        "draft": False,
        "prerelease": False
    }
    r = requests.post(create_url, headers=headers, json=data)
    if r.status_code in [201, 200]:
        logging.info(f"GitHub release created for tag '{tag_name}' with name '{release_name}'.")
        return r.json()
    else:
        logging.warning(f"Failed to create GitHub release for tag '{tag_name}': {r.text}")
        return None


def copy_gitlab_releases_to_github(gitlab_url, owner_type, owner_name, repo_name):
    project_path_encoded = parse_gitlab_project_path(gitlab_url)
    gitlab_releases = get_gitlab_releases(project_path_encoded)
    if not gitlab_releases:
        logging.info("No GitLab releases found (or not accessible). Skipping release copy.")
        return

    logging.info(f"Found {len(gitlab_releases)} GitLab release(s). Creating them on GitHub...")

    for gr in gitlab_releases:
        tag_name = gr.get("tag_name")
        release_name = gr.get("name") or tag_name
        description = gr.get("description") or ""

        create_github_release(
            owner_type=owner_type,
            owner_name=owner_name,
            repo_name=repo_name,
            tag_name=tag_name,
            release_name=release_name,
            body=description
        )


def add_default_access_permissions(org, repo_name, team_slug, permission="push"):
    url = f"{GITHUB_API_URL}/orgs/{org}/teams/{team_slug}/repos/{org}/{repo_name}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }
    data = {"permission": permission}
    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        logging.info(f"Default access permissions set for team '{team_slug}' on repo '{repo_name}'.")
    else:
        logging.warning(f"Could not set default access permissions: {response.text}")


def update_github_repo_settings(owner_type, owner_name, repo_name,
                                has_issues=True,
                                has_projects=True,
                                has_wiki=True,
                                allow_squash_merge=True,
                                allow_merge_commit=True,
                                allow_rebase_merge=True,
                                delete_branch_on_merge=False):
    if owner_type.lower() == "org":
        gh_owner = owner_name
    else:
        if owner_name:
            gh_owner = owner_name
        else:
            gh_owner = get_authenticated_username()
            if not gh_owner:
                logging.error("Could not determine GitHub username to patch repo settings.")
                return

    repo_settings_url = f"{GITHUB_API_URL}/repos/{gh_owner}/{repo_name}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }
    payload = {
        "has_issues": has_issues,
        "has_projects": has_projects,
        "has_wiki": has_wiki,
        "allow_squash_merge": allow_squash_merge,
        "allow_merge_commit": allow_merge_commit,
        "allow_rebase_merge": allow_rebase_merge,
        "delete_branch_on_merge": delete_branch_on_merge,
    }

    logging.info(f"Updating repository settings for {gh_owner}/{repo_name}...")
    resp = requests.patch(repo_settings_url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"Repository settings updated for '{repo_name}'.")
    else:
        logging.warning(f"Failed to update settings for '{repo_name}': {resp.text}")


def get_authenticated_username():
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }
    resp = requests.get(f"{GITHUB_API_URL}/user", headers=headers)
    if resp.status_code == 200:
        return resp.json().get("login")
    return None


def clone_from_gitlab(gitlab_url, clone_dir):
    try:
        token_in_url = gitlab_url.replace("https://", f"https://oauth2:{GITLAB_TOKEN}@")
        logging.info(f"Cloning from GitLab (bare): {gitlab_url}")

        repo = Repo.clone_from(
            token_in_url,
            clone_dir,
            bare=True
        )

        logging.info("Fetching all refs from GitLab...")
        repo.git.fetch('--all')

        logging.info("Local refs after fetch-all:")
        refs_output = repo.git.show_ref() or "(No refs found)"
        logging.info(refs_output)

        return repo
    except GitCommandError as e:
        logging.error(f"Git clone/fetch failed for {gitlab_url}: {e}")
        return None


def push_to_github(local_repo_path, github_url):
    try:
        repo = Repo(local_repo_path)
        secure_github_url = github_url.replace("https://", f"https://{GITHUB_TOKEN}@")

        if 'github' not in [r.name for r in repo.remotes]:
            repo.create_remote('github', secure_github_url)
        else:
            repo.remotes.github.set_url(secure_github_url)

        logging.info("Pushing all refs to GitHub (mirror push)...")
        repo.git.push('github', '--mirror')

        logging.info("All refs pushed successfully.")
        return True
    except GitCommandError as e:
        logging.error(f"Error pushing to GitHub: {e}")
        return False


def migrate_repository(
    gitlab_url, 
    owner_type, 
    owner_name, 
    new_repo_name, 
    private=True, 
    description="", 
    team_slug=None,
    apply_repo_settings=True,
    copy_releases=True
):
    """
    Main function to copy a repository from GitLab to GitHub.
    We'll remove the local clone directory with a retry callback for locked files.
    """
    local_clone_dir = Path(f"./temp_clone_{new_repo_name}_{int(time.time())}")

    success = False
    try:
        # 1. Bare clone + fetch
        local_repo = clone_from_gitlab(gitlab_url, local_clone_dir)
        if not local_repo:
            logging.error(f"Migration aborted for {gitlab_url}")
            return False

        # 2. Create GitHub repository
        github_clone_url = create_github_repo(
            repo_name=new_repo_name,
            owner_type=owner_type,
            owner_name=owner_name,
            private=private,
            description=description
        )
        if not github_clone_url:
            logging.error("Cannot proceed without GitHub repo creation.")
            return False

        # 3. Push all refs
        push_success = push_to_github(local_clone_dir, github_clone_url)
        if not push_success:
            logging.error(f"Push failed for {new_repo_name}.")
            return False

        # 4. Copy releases if requested
        if copy_releases:
            logging.info("Copying GitLab releases to GitHub...")
            copy_gitlab_releases_to_github(
                gitlab_url=gitlab_url,
                owner_type=owner_type,
                owner_name=owner_name,
                repo_name=new_repo_name
            )

        # 5. Update GH repo settings if requested
        if apply_repo_settings:
            update_github_repo_settings(
                owner_type=owner_type,
                owner_name=owner_name,
                repo_name=new_repo_name,
                has_issues=True,
                has_projects=True,
                has_wiki=True,
                allow_squash_merge=True,
                allow_merge_commit=True,
                allow_rebase_merge=True,
                delete_branch_on_merge=False
            )

        # 6. Add default team permissions (org only)
        if team_slug and owner_type.lower() == "org":
            add_default_access_permissions(
                org=owner_name,
                repo_name=new_repo_name,
                team_slug=team_slug,
                permission="push"
            )

        logging.info(f"Repository '{new_repo_name}' migrated successfully from GitLab to GitHub.")
        success = True
        return True

    finally:
        # Always remove local clone directory, with a retry callback
        logging.info(f"Removing local clone directory: {local_clone_dir}")
        try:
            shutil.rmtree(local_clone_dir, onerror=on_rm_error)
            if local_clone_dir.is_dir():
                logging.warning(f"Folder {local_clone_dir} still exists after rmtree, possibly locked.")
            else:
                logging.info(f"Folder {local_clone_dir} successfully removed.")
        except Exception as e:
            logging.exception(f"Error while removing folder {local_clone_dir}: {e}")

        if not success:
            logging.warning("Migration did not complete successfully.")


def bulk_migrate_repositories(
    repo_mapping, 
    owner_type, 
    owner_name,
    private=True, 
    description="", 
    team_slug=None,
    apply_repo_settings=True,
    copy_releases=True
):
    """
    Bulk-migrate multiple GitLab repos to GitHub.
    """
    results = {}
    for gitlab_repo_url, new_repo_name in repo_mapping:
        logging.info(f"Starting migration for: {gitlab_repo_url} -> {new_repo_name}")
        try:
            success = migrate_repository(
                gitlab_url=gitlab_repo_url,
                owner_type=owner_type,
                owner_name=owner_name,
                new_repo_name=new_repo_name,
                private=private,
                description=description,
                team_slug=team_slug,
                apply_repo_settings=apply_repo_settings,
                copy_releases=copy_releases
            )
            results[new_repo_name] = "Success" if success else "Failed"
        except Exception as e:
            logging.exception(f"Unexpected error migrating {gitlab_repo_url}: {e}")
            results[new_repo_name] = "Exception"
    
    return results


if __name__ == "__main__":
    """
    USAGE:
      1) Single repo migration:
         python migrate.py single <GITLAB_REPO_URL> <OWNER_TYPE> <OWNER_NAME> <NEW_REPO_NAME>
         
      2) Bulk migration from file:
         python migrate.py bulk <OWNER_TYPE> <OWNER_NAME> <FILE_PATH>
    """

    if len(sys.argv) < 2:
        print("Usage:")
        print("  SINGLE MIGRATION:")
        print("    python migrate.py single <GITLAB_REPO_URL> <OWNER_TYPE> <OWNER_NAME> <NEW_REPO_NAME>")
        print("  BULK MIGRATION:")
        print("    python migrate.py bulk <OWNER_TYPE> <OWNER_NAME> <FILE_PATH>")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "single":
        if len(sys.argv) != 6:
            print("Usage: python migrate.py single <GITLAB_REPO_URL> <OWNER_TYPE> <OWNER_NAME> <NEW_REPO_NAME>")
            sys.exit(1)
        gitlab_repo_url = sys.argv[2]
        owner_type = sys.argv[3]
        owner_name = sys.argv[4]
        new_github_repo_name = sys.argv[5]

        success = migrate_repository(
            gitlab_url=gitlab_repo_url,
            owner_type=owner_type,
            owner_name=owner_name,
            new_repo_name=new_github_repo_name,
            copy_releases=True
        )
        logging.info(f"Single migration completed: {'Success' if success else 'Failed'}")

    elif mode == "bulk":
        if len(sys.argv) != 5:
            print("Usage: python migrate.py bulk <OWNER_TYPE> <OWNER_NAME> <FILE_PATH>")
            sys.exit(1)

        owner_type = sys.argv[2]
        owner_name = sys.argv[3]
        file_path = sys.argv[4]

        if not os.path.isfile(file_path):
            logging.error(f"File not found: {file_path}")
            sys.exit(1)

        repo_list = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 2:
                    repo_list.append((parts[0], parts[1]))
        
        logging.info(f"Starting bulk migration for {len(repo_list)} repositories...")
        results = bulk_migrate_repositories(
            repo_list,
            owner_type,
            owner_name,
            copy_releases=True
        )
        
        logging.info("===== Bulk Migration Report =====")
        for repo_name, status in results.items():
            logging.info(f"{repo_name}: {status}")
        logging.info("=================================")

    else:
        logging.error(f"Unknown mode: {mode}")
        sys.exit(1)
