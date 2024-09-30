# def get_versions_available_on_github(config):
#     """
#     returns a dictionary containing the ArchiveBox GitHub release info for
#     the recommended upgrade version and the currently installed version
#     """
    
#     # we only want to perform the (relatively expensive) check for new versions
#     # when its most relevant, e.g. when the user runs a long-running command
#     subcommand_run_by_user = sys.argv[3] if len(sys.argv) > 3 else 'help'
#     long_running_commands = ('add', 'schedule', 'update', 'status', 'server')
#     if subcommand_run_by_user not in long_running_commands:
#         return None
    
#     github_releases_api = "https://api.github.com/repos/ArchiveBox/ArchiveBox/releases"
#     response = requests.get(github_releases_api)
#     if response.status_code != 200:
#         stderr(f'[!] Warning: GitHub API call to check for new ArchiveBox version failed! (status={response.status_code})', color='lightyellow', config=config)
#         return None
#     all_releases = response.json()

#     installed_version = parse_version_string(config['VERSION'])

#     # find current version or nearest older version (to link to)
#     current_version = None
#     for idx, release in enumerate(all_releases):
#         release_version = parse_version_string(release['tag_name'])
#         if release_version <= installed_version:
#             current_version = release
#             break

#     current_version = current_version or all_releases[-1]
    
#     # recommended version is whatever comes after current_version in the release list
#     # (perhaps too conservative to only recommend upgrading one version at a time, but it's safest)
#     try:
#         recommended_version = all_releases[idx+1]
#     except IndexError:
#         recommended_version = None

#     return {'recommended_version': recommended_version, 'current_version': current_version}

# def can_upgrade(config):
#     if config['VERSIONS_AVAILABLE'] and config['VERSIONS_AVAILABLE']['recommended_version']:
#         recommended_version = parse_version_string(config['VERSIONS_AVAILABLE']['recommended_version']['tag_name'])
#         current_version = parse_version_string(config['VERSIONS_AVAILABLE']['current_version']['tag_name'])
#         return recommended_version > current_version
#     return False
