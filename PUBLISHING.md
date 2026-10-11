# Publish Human2API publicly on GitHub

The initial GitHub connection supports working with existing repositories but not creating a new one. This script is a one-time GitHub CLI publisher for the owner `karemfree1282-gif`. It creates a **public** repository and pushes the source.

## From Windows PowerShell, macOS Terminal, or Linux shell

1. Install [Git](https://git-scm.com/downloads) and [GitHub CLI](https://cli.github.com/).
2. Extract the source ZIP to a folder you control, and open a terminal in `human2api/`.
3. Sign in to the right GitHub account using `gh auth login` (choose GitHub.com and the browser flow). **Do not paste your password or authentication token into this project or a chat.**
4. Run `python scripts/publish_github.py`.
5. Check the printed GitHub URL and the Actions tab. Wait for successful checks; enable GitHub Pages under Settings > Pages (source: branch `main`, folder `/docs`) if automatic setup wasn't allowed.
6. Review the public README and the site before sharing. Make a demo video and post through the tailored drafts under `launch/`, following each community's self-promotion rules. Do not buy/fabricate stars.

The script declines to overwrite an existing repository. If you have already created `karemfree1282-gif/human2api`, publish using ordinary Git commands instead: `git init -b main`, `git add .`, `git commit -m "Initial release"`, `git remote add origin https://github.com/karemfree1282-gif/human2api.git`, and `git push -u origin main`, after authenticating git. Verify `git status` and `.gitignore` before `git add`.

## After publishing

- Inspect CI and security checks before announcing the release.
- To create a v0.1.0 release: `gh release create v0.1.0 --generate-notes`, after confirming CI and repository content.
- Release announcements are drafts in `launch/`; posting them needs an explicitly authenticated social account and compliance with the platform rules.
- Stars, search ranking, adoption, and GitHub Trending are not guaranteed.

## If you already created an empty repository

The publisher now detects an existing **empty, public** `karemfree1282-gif/human2api` repository and pushes the initial `main` branch to it. It refuses to force-push or overwrite a repository containing existing branches. This is also the easiest route when your ChatGPT GitHub integration can edit repositories but cannot create them. Make the public repository without initializing README, .gitignore or license, then run the publisher as usual.

## GitHub Pages via Actions

The repository contains `.github/workflows/pages.yml`. The publisher attempts to turn on GitHub Pages with **GitHub Actions** as the build source. If that is not permitted, open Settings > Pages and set **Build and deployment > Source = GitHub Actions**, then manually run the Pages workflow. Verify that the site is accessible before promoting the link.

## Code security

CodeQL is configured as a separate GitHub Actions workflow. Its checks and browser tests must actually run in the new public repository before their results can be claimed.
