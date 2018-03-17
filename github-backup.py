import argparse
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

def list_user_repositories():
    next_page = 'https://api.github.com/user/repos?page=1'

    while next_page:
        LOG.debug('Fetching page: %s', next_page)
        r = requests.get(next_page, auth=(USERNAME, TOKEN))

        if r.status_code != 200:
            raise RuntimeError('GitHub returned HTTP {}'.format(r.status_code))

        repos = r.json()
        for repo in repos:
            yield repo

        next_page = None

        if 'link' in r.headers:
            links = map(str.strip, r.headers['link'].split(','))
            for link in links:
                ref, rel = map(str.strip, link.split(';'))
                if rel == 'rel="next"':
                    next_page = ref.strip('<>')

        if 'x-ratelimit-remaining' in r.headers:
            LOG.debug(
                'Rate limit remaining: %s',
                r.headers['x-ratelimit-remaining']
            )

def repo_path(base, repo):
    owner, repo_name = repo['full_name'].split('/')
    return os.path.join(base, owner, repo_name)

def write_repository_info(path, repo):
    LOG.info('Writing repository metadata for %s', repo['full_name'])

    with open(os.path.join(path, 'repository-info.json'), 'w') as f:
        f.write(json.dumps(repo, indent=2))

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
        path = repo_path(dest, repo)
        os.makedirs(path)

        write_repository_info(path, repo)
        clone_repository(path, repo, compress=argv.archive)

if __name__ == '__main__':
    main()
