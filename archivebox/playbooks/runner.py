import os
from ansible_runner import Runner, RunnerConfig
from benedict import benedict
from rich.pretty import pprint


GLOBAL_CACHE = {}

IGNORED_VARS = ('OUTPUT', 'STDOUT', 'STDERR', 'RC', 'CMD')
# IGNORED_VARS = ()

os.environ['ANSIBLE_INVENTORY_UNPARSED_WARNING'] = 'False'
os.environ['ANSIBLE_LOCALHOST_WARNING'] = 'False'

def run_playbook(name, extravars=None, getvars=IGNORED_VARS):
    _discarded = [GLOBAL_CACHE.pop(key) for key in IGNORED_VARS if key in GLOBAL_CACHE]
    rc = RunnerConfig(
        private_data_dir=".",
        playbook=f"/Volumes/NVME/Users/squash/Code/archiveboxes/archivebox7/archivebox/playbooks/{name}",
        rotate_artifacts=50000,
        host_pattern="localhost",
        extravars={
            **(extravars or {}),
            "DATA_DIR": "/Volumes/NVME/Users/squash/Code/archiveboxes/archivebox7/data4",
        },
        # quiet=True,
    )
    rc.prepare()
    r = Runner(config=rc)
    r.set_fact_cache('localhost', GLOBAL_CACHE)
    r.run()
    last_run_facts = r.get_fact_cache('localhost')
    GLOBAL_CACHE.update(filtered_facts(last_run_facts))
    return benedict({
        key: val
        for key, val in last_run_facts.items()
        if not (key.startswith('ansible_') or key in ('gather_subset', 'module_setup'))
    })

def filtered_facts(facts):
    return benedict({
        key: val
        for key, val in facts.items()
        if not (key.startswith('ansible_') or key in ('gather_subset', 'module_setup', *IGNORED_VARS))
    })

def print_globals():
    pprint(filtered_facts(GLOBAL_CACHE), expand_all=True)

# for each_host_event in r.events:
#     print(each_host_event['event'])

# print("Final status:")
# print(r.stats)

ALL_VARS = run_playbook('install_all.yml')
# pprint(ALL_VARS)
print_globals()


# YTDLP_BIN = run_playbook('bin_path.yml', getvars=('OUTPUT', 'STDOUT', 'STDERR', 'RC', 'CMD', 'ytdlp_bin_abs', 'hostvars'))
# pprint(YTDLP_BIN.YTDLP_BIN_ABS)
# print_globals()


# YTDLP_VERSION = run_playbook('version.yml') #, {'YTDLP_BIN': YTDLP_BIN.OUTPUT})
# pprint(YTDLP_VERSION.YTDLP_VERSION)
# print_globals()


# YTDLP_OUTPUT = run_playbook('extract.yml', {'url': 'https://www.youtube.com/watch?v=cK4REjqGc9w&t=27s'})
# pprint(YTDLP_OUTPUT)

# print()
# print()
# print_globals()
