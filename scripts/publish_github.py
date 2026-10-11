#!/usr/bin/env python3
"""Create or populate an empty public GitHub repository using GitHub CLI.

This publisher never uses force-push, never prints credentials, and refuses to
push onto a populated remote branch. Run only after `gh auth login` locally.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

OWNER = 'karemfree1282-gif'
NAME = 'human2api'
REPOSITORY = f'{OWNER}/{NAME}'
DESCRIPTION = 'Record browser tasks and turn them into inspectable MCP tools, CLI commands, and local REST APIs.'
TOPICS = 'mcp,ai-agents,automation,browser-automation,playwright,local-first,open-source,python'
PROJECT_PATHS = (
    'README.md', 'PUBLISHING.md', 'LICENSE', 'SECURITY.md',
    'CONTRIBUTING.md', 'CODE_OF_CONDUCT.md', 'CHANGELOG.md',
    'GOVERNANCE.md', 'SUPPORT.md', 'CITATION.cff', 'pyproject.toml',
    '.gitignore', '.gitattributes', '.env.example', '.github',
    'src', 'tests', 'workflows', 'schemas', 'docs', 'scripts', 'launch',
)


def execute(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print('+ ' + ' '.join(args), flush=True)
    return subprocess.run(args, check=check, text=True)


def output(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, check=True, text=True).stdout.strip()


def publish() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    for binary in ('git', 'gh'):
        if not shutil.which(binary):
            print(f'{binary} is missing; see PUBLISHING.md', file=sys.stderr)
            return 1
    if subprocess.run(['gh', 'auth', 'status'], capture_output=True).returncode:
        print('GitHub CLI is not connected. Run gh auth login, then retry.', file=sys.stderr)
        return 1
    login = output(['gh', 'api', 'user', '--jq', '.login'])
    if login.lower() != OWNER.lower():
        print(f'Connected to {login}, expected {OWNER}. Refusing to publish to the wrong account.', file=sys.stderr)
        return 1
    exists = subprocess.run(['gh', 'repo', 'view', REPOSITORY], capture_output=True).returncode == 0
    if exists:
        visibility = output(['gh', 'api', f'repos/{REPOSITORY}', '--jq', '.private'])
        if visibility == 'true':
            print('Repository already exists but is private. Change visibility manually first.', file=sys.stderr)
            return 1
    if not (root / '.git').exists():
        execute(['git', 'init', '-b', 'main'])
    if subprocess.run(['git', 'config', '--get', 'user.name'], capture_output=True).returncode:
        execute(['git', 'config', 'user.name', login])
    if subprocess.run(['git', 'config', '--get', 'user.email'], capture_output=True).returncode:
        user_id = output(['gh', 'api', 'user', '--jq', '.id'])
        execute(['git', 'config', 'user.email', f'{user_id}+{login}@users.noreply.github.com'])
    execute(['git', 'add', '-A', '--', *PROJECT_PATHS])
    if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
        execute(['git', 'commit', '-m', 'feat: initial Human2API open-source alpha'])
    if exists:
        remote_url = f'https://github.com/{REPOSITORY}.git'
        current_remote = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True)
        if current_remote.returncode:
            execute(['git', 'remote', 'add', 'origin', remote_url])
        elif current_remote.stdout.strip().rstrip('/') not in {remote_url, f'git@github.com:{REPOSITORY}.git'}:
            print('origin points to another repository; refusing to overwrite it.', file=sys.stderr)
            return 1
        if output(['git', 'ls-remote', '--heads', 'origin']):
            print('Remote repository already has branches. Refusing to push to an existing project.', file=sys.stderr)
            return 1
        execute(['git', 'push', '-u', 'origin', 'HEAD:main'])
    else:
        execute(['gh', 'repo', 'create', REPOSITORY, '--public', '--source=.', '--remote=origin', '--push'])
    execute([
        'gh', 'repo', 'edit', REPOSITORY,
        '--description', DESCRIPTION,
        '--homepage', f'https://{OWNER}.github.io/{NAME}/',
        '--add-topic', TOPICS,
        '--enable-issues', '--enable-discussions',
    ], check=False)
    # GitHub Pages must be configured for the Actions deployment workflow.
    pages = subprocess.run([
        'gh', 'api', '--method', 'POST', f'repos/{REPOSITORY}/pages',
        '-f', 'build_type=workflow',
    ], capture_output=True, text=True)
    if pages.returncode:
        print('Pages may already exist or need activation in Settings > Pages > GitHub Actions.')
    print(f'Published: https://github.com/{REPOSITORY}')
    print('Check Actions and Pages. Do not tag a release until CI and browser tests pass.')
    return 0


if __name__ == '__main__':
    raise SystemExit(publish())
