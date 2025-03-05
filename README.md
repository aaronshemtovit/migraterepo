# 🛠 GitLab to GitHub Migration Tool

This repository contains a Python script for migrating repositories from GitLab to GitHub, preserving all branches, tags, commit history, and optionally setting default access permissions.

---

## 📋 Features

- **Authentication:**  
  Uses Personal Access Tokens (PAT) for both GitLab and GitHub.

- **Migration Capabilities:**  
  - Supports single and bulk repository migrations.  
  - Preserves all branches, tags, and commit history.  

- **Logging & Reporting:**  
  - Logs all steps and errors to `migration.log`.  
  - Provides a summary report after bulk migrations.

---

## 🐳 Run in Docker Container

### 1. Create a `.env` File in local directory

Add your GitLab and GitHub Personal Access Tokens to a `.env` file in the root directory:

```bash
GITLAB_TOKEN=<your_gitlab_token>
GITHUB_TOKEN=<your_github_token>
```

### 4. Build the Docker Image

Run this command in the terminal:

```bash
 docker build -t gitlab2github:latest .
```

### 5. Run the Docker Container

**Single Repository Migration:**

```bash
 docker run --rm -v ${PWD}:/app gitlab2github:latest python migrate.py single https://gitlab.com/Mr_Goldberg/goldberg_emulator user aaronshemtovit test
```

**Bulk Repository Migration:**

Edit a `repos_to_migrate.txt` file with content like:

```plaintext
https://gitlab.com/mygroup/repo1.git, my-repo1
https://gitlab.com/mygroup/repo2.git, my-repo2
```

Then run:

```bash
docker run --rm -v ${PWD}/migration.log:/app/migration.log gitlab2github:latest python migrate.py bulk user aaronshemtovit repos_to_migrate.txt
```

---

## 🛠 How to Use the Migration Script Directly

### 1. Clone the Repository

```bash
git clone <this-repository-url>
cd <cloned-directory>
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Environment Variables

Use a `.env` file.

```bash
GITLAB_TOKEN=<your_gitlab_token>
GITHUB_TOKEN=<your_github_token>
```

### 4. Run the Script

**Single Repository Migration:**

```bash
python migrate.py single "https://gitlab.com/mygroup/myproject.git" my-github-org my-github-repo
```

**Bulk Repository Migration:**

Create `repos_to_migrate.txt`:

```plaintext
https://gitlab.com/mygroup/repo1.git, my-repo1
https://gitlab.com/mygroup/repo2.git, my-repo2
```

Then run:

```bash
python migrate.py bulk my-github-org repos_to_migrate.txt
```

---

## 📄 Log and Report

- **Logs:** Check `migration.log` for detailed logs of each step.  
- **Reports:** The script prints a summary at the end indicating which repositories were successfully migrated and which failed.

---

## 📌 Example Usage Summary

**Single Repository:**

```bash
python migrate.py single "https://gitlab.com/namespace/my-repo.git" my-github-org my-github-repo
```

**Bulk Migration:**

```bash
python migrate.py bulk my-github-org repos_to_migrate.txt
```