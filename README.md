# scripts
A collection of useful scripts

# XportReddit
An automated tool for cross-posting Reddit saved posts to X (formerly Twitter). Uses Selenium WebDriver to automate the entire posting workflow with intelligent features:

**Features:**
- **Automated posting**: Reads from an exported saved posts JSON file and processes posts sequentially
- **Smart media handling**: Downloads images from Reddit, batches them (up to 4 per tweet), and creates threaded posts when needed
- **Human-like behavior**: Includes randomized delays, simulated typing with occasional typos/corrections, and anti-bot detection measures
- **Progress tracking**: Maintains a log of successfully posted URLs to avoid duplicates and resume interrupted sessions
- **Flexible posting modes**: 
  - Auto mode: Fully automated posting with human-like delays
  - Interactive mode: Review, skip, or customize titles for each post
  - Custom title support: Edit post titles before posting
- **Retry logic**: Automatically retries failed posts with configurable attempts

**Requirements:**
- Exported saved posts file from [RedditManager](https://redditmanager.com/)
- Selenium WebDriver (Edge/Chrome)
- Active X (Twitter) session in browser

**Utilities:**
- `parse_reddit_export.py`: Extract saved post URLs from Reddit HTML export files
- `sort_saved_posts.py`: Sort posts from oldest to newest based on Reddit post IDs

# ArchiveReplayer

A utility script for reconstructing a Git repository’s commit history from archived project files.
It scans an original source directory to map file modification times, then replays those files into a local, offline Git repository as backdated commits, grouped by date and module structure.

ArchiveReplayer is ideal for archival and academic use, such as rebuilding historical coursework or research projects into a versioned Git timeline—without connecting to or pushing to a remote repository.
