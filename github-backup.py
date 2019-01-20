import argparse
from datetime import datetime
import json
import logging
import os
import requests
import shutil
import subprocess
import sys
import tarfile

USERNAME = os.getenv('GITHUB_USERNAME')
TOKEN = os.getenv('GITHUB_TOKEN')
LOG = logging.getLogger(name='github-backup')

def next_page_url(r):
    return r.links['next']['url'] if 'next' in r.links else None

def wait_for_rate_limit(r):
    remaining = int(r.headers['x-ratelimit-remaining'])
    LOG.debug('Rate limit remaining: %d', remaining)
    if remaining <= 1:
        reset_at = datetime.fromtimestamp(int(r.headers['x-ratelimit-reset']))
        delay = (reset_at - datetime.now()).seconds + 1
        if delay > 0:
            LOG.info('Delaying %d seconds for rate limit reset', delay)

def list_user_repositories():
    next_page = 'https://api.github.com/user/repos?page=1'

    while next_page:
        LOG.debug('next_page: %s', next_page)
        r = requests.get(next_page, auth=(USERNAME, TOKEN))

        if r.status_code != 200:
            r.raise_for_status()

        next_page = next_page_url(r)
        wait_for_rate_limit(r)

        repos = r.json()
        for repo in repos:
            yield repo

def repo_path(base, repo):
    owner, repo_name = repo['full_name'].split('/')
    return os.path.join(base, owner, repo_name)

def write_repository_info(path, repo):
    LOG.info('Writing repository metadata for %s', repo['full_name'])

    with open(os.path.join(path, 'repository-info.json'), 'w') as f:
        f.write(json.dumps(repo))

def clone_repository(path, repo, compress=True):
    LOG.info('Cloning %s', repo['full_name'])

    repo_dir = os.path.join(path, 'repository')

    args = [
        'git',
        'clone',
        '--mirror',
        repo['clone_url'],
        repo_dir
    ]

    LOG.debug(args)

    subprocess.check_call(args)

    if compress:
        LOG.info('Compressing %s', repo_dir)

        with tarfile.open(os.path.join(path, 'repository.tar.xz'), 'w:xz') as f:
            f.add(repo_dir)

        # Clean up the directory now that the archive is written
        shutil.rmtree(repo_dir)

def save_repository_issues(path, repo):
    issues_dir = os.path.join(path, 'issues')
    os.makedirs(issues_dir)

    LOG.info('Saving issues for %s', repo['full_name'])
    next_page = ('https://api.github.com/repos/{}/issues?'
                 'state=all&direction=asc').format(repo['full_name'])

    while next_page:
        LOG.debug('next_page: %s', next_page)

        r = requests.get(next_page, auth=(USERNAME, TOKEN))
        if r.status_code != 200:
            r.raise_for_status()

        next_page = next_page_url(r)
        wait_for_rate_limit(r)

        for issue in r.json():
            save_issue(issues_dir, issue)

def save_issue(issues_dir, issue):
    comments = []
    next_page = issue['comments_url']
    LOG.info('Saving issue %s', issue['url'])

    while next_page:
        LOG.debug('next_page: %s', next_page)
        r = requests.get(next_page, auth=(USERNAME, TOKEN))
        if r.status_code != 200:
            r.raise_for_status()

        comments.extend(r.json())

        next_page = next_page_url(r)
        wait_for_rate_limit(r)

    issue_file = '{}.json'.format(issue['number'])
    with open(os.path.join(issues_dir, issue_file), 'w') as f:
        f.write(json.dumps(issue))

    comments_file = '{}.comments.json'.format(issue['number'])
    with open(os.path.join(issues_dir, comments_file), 'w') as f:
        f.write(json.dumps(comments))

def main():
    if not USERNAME or not TOKEN:
        print('GITHUB_USERNAME and GITHUB_TOKEN environment variables'
              'are required', file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='Create a backup of your GitHub repositories'
    )

    parser.add_argument('dest',
        nargs=1,
        help='Destination directory (will be created)'
    )
    parser.add_argument(
        '--archive',
        action='store_true',
        help='Compress cloned repositories into an archive'
    )
    parser.add_argument(
        '--backup-issues',
        action='store_true',
        help='Backup issues and issue comments with cloned repository'
    )

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    argv = parser.parse_args(sys.argv[1:])

    logging.basicConfig(
        level=(logging.DEBUG if os.getenv('DEBUG') else logging.INFO),
        format='%(asctime)-15s [%(levelname)s] %(name)s: %(message)s'
    )

    dest = argv.dest[0]
    os.makedirs(dest)

    for repo in list_user_repositories():
        if repo['private']:
            LOG.warn('Skipping %s (private repos are not supported)',
                     repo['full_name'])
            continue

        path = repo_path(dest, repo)
        os.makedirs(path)

        write_repository_info(path, repo)
        clone_repository(path, repo, compress=argv.archive)
        if argv.backup_issues:
            save_repository_issues(path, repo)

if __name__ == '__main__':
    main()
