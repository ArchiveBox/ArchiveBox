# Contribution Process

1. Confirm your desired features fit into our bigger project goals roadmap: https://github.com/pirate/ArchiveBox#roadmap
2. Open an issue with your planned implementation to discuss
3. Check in with me before starting development to make sure your work wont conflict with or duplicate existing work
4. Setup your dev environment, make some changes, and test using the test input files
5. Commit, push, and submit a PR and wait for review feedback
6. Have patience, don't abandon your PR! We love contributors but we all have day jobs and don't always have time to respond to notifications instantly. If you want a faster response, ping @theSquashSH on twitter or Patreon.

**Useful links:**

- https://github.com/pirate/ArchiveBox/issues
- https://github.com/pirate/ArchiveBox/pulls
- https://github.com/pirate/ArchiveBox/wiki/Roadmap
- https://github.com/pirate/ArchiveBox/wiki/Install#manual-setup

### Development Setup

```bash
git clone https://github.com/pirate/ArchiveBox
cd ArchiveBox
# Optionally create a virtualenv
pip install -r requirements.txt
pip install -e .
```

### Running Tests

```bash
./bin/archive tests/*
# look for errors in stdout/stderr
# then confirm output html looks right

# if on >v0.4 run the django test suite:
archivebox manage test
```

### Getting Help

Open issues on Github or contact me https://sweeting.me/#contact.
