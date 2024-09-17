import os

from pathlib import Path

from benedict import benedict
from rich.pretty import pprint

from ansible_runner import Runner, RunnerConfig

GLOBAL_CACHE = {}


def run_playbook(playbook_path, data_dir, quiet=False, **kwargs):
    ANSIBLE_TMP_DIR = str(Path(data_dir) / "tmp" / "ansible")
    os.environ['ANSIBLE_INVENTORY_UNPARSED_WARNING'] = 'False'
    os.environ['ANSIBLE_LOCALHOST_WARNING'] = 'False'
    os.environ["ANSIBLE_HOME"] = ANSIBLE_TMP_DIR
    # os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(Path(data_dir).parent / 'archivebox')
    os.environ["ANSIBLE_ROLES_PATH"] = (
        '/Volumes/NVME/Users/squash/Code/archiveboxes/archivebox7/archivebox/builtin_plugins/ansible/roles'
    )
    
    rc = RunnerConfig(
        private_data_dir=ANSIBLE_TMP_DIR,
        playbook=str(playbook_path),
        rotate_artifacts=50000,
        host_pattern="localhost",
        extravars={
            "DATA_DIR": str(data_dir),
            **kwargs,
        },
        quiet=quiet,
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
        if not (key.startswith('ansible_') or key in ('gather_subset', 'module_setup'))
    })

def print_globals():
    pprint(filtered_facts(GLOBAL_CACHE), expand_all=True)



# YTDLP_OUTPUT = run_playbook('extract.yml', {'url': 'https://www.youtube.com/watch?v=cK4REjqGc9w&t=27s'})
# pprint(YTDLP_OUTPUT)
